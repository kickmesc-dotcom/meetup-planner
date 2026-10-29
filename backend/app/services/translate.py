"""Перевод данных на месте: «прочитать задание по-своему» (план, 11).

Зачем это вообще нужно. Интерфейс мы переводим кодом (`tx`), а поручения, пункты
чек-листа, названия залов и стандарты пишет руководитель — их переводить
«в словаре» нечем: это чужие данные, а не наши строки. Часть команды читает
по-русски хуже, чем по-узбекски, и задание, которое не поняли, не выполнено —
даже если галочка стоит.

Что решено и почему именно так.

* **Модель локальная и открытая.** SMaLL-100 (distilled M2M-100, MIT): одна
  модель на 100 языков, включая узбекский, int8 через CTranslate2. Ни токенов,
  ни внешних API, ни счёта за символы — при нашем бюджете это единственный
  вариант, который может работать всегда.
* **Кэш в базе — не оптимизация, а условие работы.** Контейнер Amvera живёт на
  0,5 ГБ RAM (см. S-19 в плане), модель туда не влезает. Поэтому считаем один
  раз и кладём в `translation_cache`; второй хост отдаёт уже посчитанное.
  Где модели нет — честно отвечаем «недоступно», а не выдумываем перевод.
* **В кэше нет исходного текста.** Ключ — `sha256(текст + язык)`, значение —
  перевод. База не превращается во вторую копию переписки и заданий.
* **Переводим только то, что ещё не на языке.** Если кириллицы в строке нет,
  переводить нечего: возвращаем строку как есть. Это и экономит время, и не
  портит уже латинские названия вроде «Wi-Fi».

Граница: сервис переводит данные, но НЕ решает, показывать ли перевод. Решает
человек — кнопкой в блоке (фронтенд). Автоподмена задания, по которому он
отчитывается, была бы подменой смысла.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import TranslationCache

log = structlog.get_logger()

# Языки, на которые переводим. Русский — источник, а не цель: при русском
# интерфейсе кнопки перевода просто нет.
TARGETS: tuple[str, ...] = ("en", "uz")

# Сколько строк за один заход. Блок задания — это заголовок, описание и пара
# подписей; 20 с запасом. Ограничение не про производительность модели, а про
# то, чтобы одна ручка не превращалась в «переведи мне весь экран».
MAX_TEXTS = 20
MAX_TEXT_CHARS = 500

CYRILLIC = re.compile(r"[А-Яа-яЁё]")

# Код языка, прилипший к началу перевода (см. `Ct2Model._decode`).
_LANG_PREFIX = re.compile(r"^(?:__)?(?:ru|en|uz)\s+", re.IGNORECASE)

# Имя провайдера в кэше. Нужно, чтобы потом было видно, чем переведено: если
# однажды сменим модель, старые строки переводить заново не обязательно, но
# понять их происхождение можно будет без раскопок.
PROVIDER_LOCAL = "local"
PROVIDER_CACHE_SAME = "same"

# Русский → английский: SMaLL-100, int8-конверсия (MIT, 330 МБ).
DEFAULT_MODEL_REPO = "solavr/small100-ctranslate2-int8"
# Английский → узбекский: m2m100-418M, дообученная на узбекский (apache-2.0
# поверх MIT). Без неё узбекского перевода нет вовсе: прямая SMaLL-100 на
# узбекский выдаёт мусор (см. докстринг `LocalProvider`).
DEFAULT_UZ_MODEL_REPO = "booba-uz/english-uzbek-translation_v3"


def normalize(text: str) -> str:
    """Единый вид строки перед хэшированием.

    Схлопываем пробелы и обрезаем края: перевод не должен зависеть от того,
    поставил ли управляющий лишний пробел в конце пункта чек-листа. Регистр не
    трогаем — он часть текста, и «Мойка» с «мойка» могут значить разное.
    """
    return " ".join(text.split())


def needs_translation(text: str) -> bool:
    """Есть ли в строке кириллица.

    Проверка нарочно простая: определять язык по статистике здесь нечего —
    данные пишут по-русски, а латиница в них (бренды, «Wi-Fi», «VIP-зал») не
    переводится и не должна.
    """
    return bool(CYRILLIC.search(text))


def cache_key(text: str, target: str) -> str:
    """Ключ кэша: хэш нормализованного текста вместе с языком перевода."""
    payload = f"{normalize(text)}|{target}".encode()
    return hashlib.sha256(payload).hexdigest()


class TranslationProvider(Protocol):
    """Переводчик. Минимум методов — чтобы провайдеров можно было подменять."""

    name: str

    def available(self) -> bool: ...

    def supports(self, target: str) -> bool: ...

    async def translate(self, texts: list[str], target: str) -> list[str]: ...


class Ct2Model:
    """Одна модель CTranslate2 + её токенизатор.

    Два вида токенизаторов, потому что так легли модели: у OPUS/SMaLL-100 это
    `sentencepiece.bpe.model`, у дообученной m2m100 — `tokenizer.json` (быстрый
    токенизатор Hugging Face). Тянуть ради второго `transformers` и тем более
    torch в рантайм незачем: `tokenizers` умеет читать этот файл сам и весит
    мегабайты, а не гигабайты.
    """

    def __init__(self, model_dir: Path, tokenizer: str) -> None:
        self._dir = model_dir
        self._tokenizer = tokenizer
        self._translator: object | None = None
        self._tok: object | None = None
        self._lock = threading.Lock()
        self._failed = False

    @property
    def failed(self) -> bool:
        return self._failed

    def _load(self) -> None:
        if self._translator is not None and self._tok is not None:
            return
        with self._lock:
            if self._translator is not None and self._tok is not None:
                return
            try:
                import ctranslate2

                self._translator = ctranslate2.Translator(
                    str(self._dir),
                    device="cpu",
                    # int8 на CPU быстрее fp32 в разы и меньше по памяти.
                    compute_type="int8_float32",
                    inter_threads=1,
                    # Два потока, а не «все ядра»: рядом живёт API, и забирать
                    # весь CPU под перевод одной фразы — значит гасить сам
                    # интерфейс, который эту фразу и показывает.
                    intra_threads=2,
                )
                if self._tokenizer == "spm":
                    import sentencepiece as spm

                    self._tok = spm.SentencePieceProcessor(
                        model_file=str(self._dir / "sentencepiece.bpe.model")
                    )
                else:
                    from tokenizers import Tokenizer

                    self._tok = Tokenizer.from_file(str(self._dir / "tokenizer.json"))
                log.info("translate.model_loaded", path=str(self._dir), tokenizer=self._tokenizer)
            except Exception as exc:  # noqa: BLE001 — любая причина = «нет перевода»
                # Падение загрузки не должно ронять приложение: перевод — assist,
                # без него приложение обязано работать как раньше.
                self._failed = True
                self._translator = None
                self._tok = None
                log.warning("translate.model_unavailable", path=str(self._dir), error=str(exc))

    def _encode(self, text: str) -> list[str]:
        if self._tokenizer == "spm":
            return list(self._tok.encode(text, out_type=str))  # type: ignore[attr-defined]
        return list(self._tok.encode(text).tokens)  # type: ignore[attr-defined]

    def _decode(self, tokens: list[str]) -> str:
        if self._tokenizer == "spm":
            text = str(self._tok.decode(tokens)).strip()  # type: ignore[attr-defined]
        else:
            ids = [i for i in (self._tok.token_to_id(t) for t in tokens) if i is not None]  # type: ignore[attr-defined]
            text = str(self._tok.decode(ids, skip_special_tokens=True)).strip()  # type: ignore[attr-defined]
        # Быстрый токенизатор m2m100 оставляет в начале код языка («uz Xonada…»):
        # `skip_special_tokens` его не ловит, потому что в словаре это обычный
        # токен «uz», а не служебный. Срезаем — иначе каждая переведённая
        # строка начинается с двух лишних букв.
        return _LANG_PREFIX.sub("", text)

    def run(self, texts: list[str], target_token: str) -> list[str]:
        self._load()
        translator = self._translator
        if translator is None or self._tok is None:
            raise RuntimeError("model_not_loaded")

        # M2M-100 (и его дистилляты) ожидают токен языка ПЕРЕД исходным текстом.
        batch = [[target_token, *self._encode(text), "</s>"] for text in texts]
        results = translator.translate_batch(  # type: ignore[attr-defined]
            batch,
            # beam 3 вместо 5: на коротких поручениях разницы в смысле не
            # видно, а времени уходит заметно меньше.
            beam_size=3,
            max_decoding_length=256,
        )
        return [
            self._decode(result.hypotheses[0] if result.hypotheses else [])
            for result in results
        ]


class LocalProvider:
    """Перевод на своём железе: ru→en одной моделью, ru→uz — через английский.

    Почему на узбекский через английский. Первая попытка была прямой: та же
    SMaLL-100 с токеном `__uz__`. На живых фразах из заведения она выдавала
    мусор — «XA XA XA XA…» и «Soʻng pol.» вместо «Помыть пол». Проверять это
    на сотруднике нельзя: он получил бы уверенный, но бессмысленный текст.
    Отдельной ru→uz модели с открытой лицензией в каталогах нет (проверено:
    ни у OPUS-MT, ни у Argos такой пары нет, а NLLB и её дообучения —
    CC-BY-NC, то есть не для платного тарифа).

    Зато en→uz модель есть: `booba-uz/english-uzbek-translation_v3` —
    m2m100-418M, дообученная на узбекский, apache-2.0 поверх MIT. Поэтому
    цепочка: русский → английский (SMaLL-100) → узбекский. Смысл теряется
    дважды, но текст остаётся настоящим узбекским, а не повтором одного слога.

    Модели грузятся лениво и не на старте: 330 + 450 МБ весов задерживали бы
    подъём контейнера ради функции, которой могут не воспользоваться.
    """

    name = PROVIDER_LOCAL

    def __init__(
        self,
        model_dir: str | None = None,
        model_repo: str | None = None,
        uz_model_dir: str | None = None,
        uz_model_repo: str | None = None,
    ) -> None:
        self._model_dir = (
            model_dir if model_dir is not None else os.getenv("TRANSLATE_MODEL_DIR", "")
        ).strip()
        self._model_repo = (
            model_repo if model_repo is not None else os.getenv("TRANSLATE_MODEL_REPO", "")
        ).strip()
        self._uz_model_dir = (
            uz_model_dir if uz_model_dir is not None else os.getenv("TRANSLATE_UZ_MODEL_DIR", "")
        ).strip()
        self._uz_model_repo = (
            uz_model_repo
            if uz_model_repo is not None
            else os.getenv("TRANSLATE_UZ_MODEL_REPO", "")
        ).strip()
        self._ru_en: Ct2Model | None = None
        self._en_uz: Ct2Model | None = None

    # ------------------------------------------------------------------ модели

    @staticmethod
    def _snapshot(directory: str, repo: str, fallback: str) -> Path:
        if directory:
            return Path(directory)
        # Скачивание при первом обращении: в образ модели не кладём — иначе
        # сборка на 0,5 ГБ хосте станет невозможной, а модель нужна только там,
        # где хватает памяти.
        from huggingface_hub import snapshot_download  # тяжёлый импорт — только здесь

        return Path(snapshot_download(repo_id=repo or fallback))

    def _primary(self) -> Ct2Model | None:
        if self._ru_en is not None:
            return None if self._ru_en.failed else self._ru_en
        if not (self._model_dir or self._model_repo):
            return None
        try:
            path = self._snapshot(self._model_dir, self._model_repo, DEFAULT_MODEL_REPO)
        except Exception as exc:  # noqa: BLE001
            log.warning("translate.download_failed", repo=self._model_repo, error=str(exc))
            self._ru_en = Ct2Model(Path("/nonexistent"), "spm")
            self._ru_en._failed = True  # noqa: SLF001 — внутренняя пометка «не пробовать снова»
            return None
        self._ru_en = Ct2Model(path, "spm")
        return self._ru_en

    def _uz(self) -> Ct2Model | None:
        if self._en_uz is not None:
            return None if self._en_uz.failed else self._en_uz
        if not (self._uz_model_dir or self._uz_model_repo):
            return None
        try:
            path = self._snapshot(self._uz_model_dir, self._uz_model_repo, DEFAULT_UZ_MODEL_REPO)
        except Exception as exc:  # noqa: BLE001
            log.warning("translate.download_failed", repo=self._uz_model_repo, error=str(exc))
            self._en_uz = Ct2Model(Path("/nonexistent"), "hf")
            self._en_uz._failed = True  # noqa: SLF001
            return None
        # Токенизатор определяем по файлам: у конверсий OPUS лежит spm, у
        # дообученных m2m100 — tokenizer.json.
        kind = "spm" if (path / "sentencepiece.bpe.model").exists() else "hf"
        self._en_uz = Ct2Model(path, kind)
        return self._en_uz

    # ---------------------------------------------------------------- интерфейс

    def available(self) -> bool:
        return self._primary() is not None

    def supports(self, target: str) -> bool:
        if target == "en":
            return self.available()
        if target == "uz":
            return self.available() and self._uz() is not None
        return False

    def _translate_sync(self, texts: list[str], target: str) -> list[str]:
        primary = self._primary()
        if primary is None:
            raise RuntimeError("model_not_loaded")
        if target == "en":
            return primary.run(texts, "__en__")
        # Узбекский: английский посередине. Прямой токен `__uz__` у SMaLL-100
        # в int8 разваливается — см. докстринг класса.
        secondary = self._uz()
        if secondary is None:
            raise RuntimeError("model_not_loaded")
        english = primary.run(texts, "__en__")
        return secondary.run(english, "__uz__")

    async def translate(self, texts: list[str], target: str) -> list[str]:
        if not texts:
            return []
        return await asyncio.to_thread(self._translate_sync, texts, target)


@dataclass
class TranslateItem:
    """Одна строка ответа. `translated is None` — перевода нет и не будет."""

    translated: str | None
    provider: str | None


# Один провайдер на процесс: модели грузятся один раз и живут в памяти.
# Создавать новый объект на запрос — значит грузить 780 МБ весов на каждое
# нажатие кнопки.
_PROVIDER: TranslationProvider | None = None
_PROVIDER_READY = False


def get_provider() -> TranslationProvider | None:
    """Провайдер перевода или `None`, если он выключен или не настроен.

    `TRANSLATE_PROVIDER=off` — выключатель на случай, когда модель мешает
    (мало памяти, отладка). Тихого «попробуем и упадём» здесь нет.
    """
    global _PROVIDER, _PROVIDER_READY
    if _PROVIDER_READY:
        return _PROVIDER
    _PROVIDER_READY = True
    if (os.getenv("TRANSLATE_PROVIDER") or "").strip().lower() in {"off", "0", "no", "none"}:
        _PROVIDER = None
        return None
    provider = LocalProvider()
    _PROVIDER = provider if provider.available() else None
    return _PROVIDER


async def warm_up() -> None:
    """Прогреть модели в фоне сразу после старта (план, 11).

    Зачем. Весов 780 МБ (330 + 450), и если грузить их в момент нажатия кнопки
    человеком, первый запрос ждёт скачивание и загрузку — а на бесплатном
    хосте это легко дольше любого разумного таймаута. В фоне же к моменту,
    когда кто-то нажмёт «перевести», всё уже в памяти.

    Ничего не делает, если модели не настроены (Amvera на 0,5 ГБ) — там
    функции просто нет, и греть нечего.
    """
    provider = get_provider()
    if provider is None:
        return
    for target in TARGETS:
        if not provider.supports(target):
            continue
        try:
            # Короткая фраза: важен сам факт загрузки весов, а не результат.
            await provider.translate(["Проверка перевода"], target)
            log.info("translate.warmed_up", target=target)
        except Exception as exc:  # noqa: BLE001 — прогрев не должен ничего ронять
            log.warning("translate.warm_up_failed", target=target, error=str(exc))


async def translate_texts(
    session: AsyncSession,
    texts: list[str],
    target: str,
    *,
    provider: TranslationProvider | None = None,
) -> tuple[list[TranslateItem], str | None]:
    """Перевести пачку строк, по возможности не считая дважды.

    Возвращает `(items, reason)`. `reason` заполняется, только если перевода не
    будет и человека об этом стоит сказать (`model_unavailable`). Если часть
    строк нашлась в кэше, а часть нет — переводим недостающие; при недоступной
    модели кэш всё равно отдаём: он уже посчитан и бесплатен.
    """
    provider = provider if provider is not None else get_provider()

    cleaned = [normalize(t)[:MAX_TEXT_CHARS] for t in texts]
    # Ключи считаем один раз: ими же отвечаем, поэтому порядок и дубликаты
    # важны — ответ должен совпадать с запросом один в один.
    keys = [cache_key(t, target) for t in cleaned]

    todo: list[str] = []
    for text, key in zip(cleaned, keys, strict=True):
        if text and needs_translation(text) and key not in todo:
            todo.append(key)

    known: dict[str, str] = {}
    if todo:
        rows = await session.execute(
            select(TranslationCache.source_hash, TranslationCache.translated).where(
                TranslationCache.target == target,
                TranslationCache.source_hash.in_(todo),
            )
        )
        known = {row.source_hash: row.translated for row in rows}

    missing = [key for key in todo if key not in known]
    reason: str | None = None

    if missing and provider is not None:
        # Пары «ключ → текст» для тех, кого не нашли в кэше.
        by_key = {cache_key(t, target): t for t in cleaned}
        batch = [by_key[key] for key in missing]
        try:
            translated = await provider.translate(batch, target)
        except Exception as exc:  # noqa: BLE001
            log.warning("translate.failed", target=target, count=len(batch), error=str(exc))
            translated = []
        if len(translated) == len(missing):
            # Пишем построчно через savepoint, а не `INSERT … ON CONFLICT`:
            # `ON CONFLICT` есть только у Postgres, а тесты идут на sqlite, и
            # две ветки кода (одна для боевой базы, другая для тестов) — это
            # две разные ошибки, из которых проверена будет одна.
            #
            # Гонка при этом закрыта тем же способом, что и ограничением в
            # схеме: второй контейнер, успевший вставить ту же пару, получит
            # `IntegrityError`, откатит ТОЛЬКО свою вставку (savepoint) и
            # продолжит. Без savepoint откатилась бы вся транзакция запроса.
            for key, text in zip(missing, translated, strict=True):
                if not text.strip():
                    continue
                try:
                    async with session.begin_nested():
                        session.add(
                            TranslationCache(
                                source_hash=key,
                                target=target,
                                translated=text,
                                provider=provider.name,
                            )
                        )
                        await session.flush()
                except IntegrityError as exc:
                    # Проглатываем ТОЛЬКО конфликт по нашей паре «хэш + язык»:
                    # второй контейнер мог успеть вставить ту же строку. Любая
                    # другая ошибка целостности - это наша поломка, и молчать
                    # о ней нельзя (на sqlite именно так и скрывался нерабочий
                    # первичный ключ: вставка не проходила вовсе).
                    if "uq_translation_hash_target" not in str(exc.orig):
                        raise
                known.setdefault(key, text)

    missing_after = [key for key in missing if key not in known]
    if missing_after:
        reason = "model_unavailable"

    items: list[TranslateItem] = []
    for text, key in zip(cleaned, keys, strict=True):
        if not text:
            items.append(TranslateItem(translated=None, provider=None))
        elif not needs_translation(text):
            # Уже на латинице — переводить нечего, и показывать кнопку незачем.
            items.append(TranslateItem(translated=None, provider=PROVIDER_CACHE_SAME))
        else:
            value = known.get(key)
            items.append(
                TranslateItem(
                    translated=value,
                    provider=None if value is None else PROVIDER_LOCAL,
                )
            )
    return items, reason
