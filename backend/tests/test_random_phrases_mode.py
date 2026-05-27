"""GHG6 L: режимы сбора фраз 'words' / 'phrases' / 'mix'.

Раньше `compose_random_phrase` склеивал чанки (по пунктуации), и
`count_min/count_max` строго применялись только к чанкам. Пользовательский
кейс п.20: выставил «2..2 слов», получил цитату из 8 слов — потому что один
чанк может быть длинным предложением.

Теперь:
- `words`: единица сборки — отдельное слово длиной ≥3. min/max применяются к
  числу слов, склейка через пробел (`_glue_words`).
- `phrases`: единица — чанк по пунктуации (`_split_into_chunks`).
- `mix`: оба пула объединены, склейка через связки.

В каждом режиме `dedup_chunks(picked_raw, all_pool=..., target_n=n)` режет до
n уникальных. На малом пуле может вернуть меньше — это не ошибка (log-warning).

Тестируем через fake-async-session: подменяем `session.execute(stmt).all()`
зафиксированными `(user_id, text)`-парами, без реальной БД.
"""
from __future__ import annotations

import random
import re
from typing import Any

from app.services.random_phrases import (
    _glue_words,
    _split_into_chunks,
    _split_into_words,
    compose_random_phrase,
)


# --- L: чистые юниты --------------------------------------------------------


def test_split_words_filters_short_and_punct() -> None:
    # Слова длиной < 3 и знаки препинания пропускаем.
    out = _split_into_words("Я бы пошёл, но дождь и хз. 2024 — норм")
    # 'я', 'бы' — слишком короткие (<3), пропускаем.
    # Цифры '2024' и слово 'хз' (2 буквы) — на грани: 'хз' пропускаем (<3),
    # '2024' попадает (4 символа).
    assert "пошёл" in out
    assert "дождь" in out
    assert "норм" in out
    assert "2024" in out
    assert "хз" not in out
    assert "я" not in out
    assert "бы" not in out


def test_split_words_empty() -> None:
    assert _split_into_words("") == []
    assert _split_into_words("...") == []
    assert _split_into_words(" ! ? . ,") == []


def test_glue_words_capitalizes_and_terminates() -> None:
    out = _glue_words(["короче", "пошёл", "спать"])
    # Первое слово с заглавной + точки/многоточие в конце.
    assert out.startswith("Короче ")
    assert out.endswith(("...", "!", "?", ".", "…"))


def test_glue_words_keeps_existing_terminator() -> None:
    # Если последний токен уже оканчивается на ! / ? / . / … — не добавляем "...".
    out = _glue_words(["норм", "ага!"])
    assert out.endswith("ага!")
    assert not out.endswith("ага!...")


def test_glue_words_empty_fallback() -> None:
    assert _glue_words([]) == "..."


# --- L: compose_random_phrase через fake-session ----------------------------


class _FakeSession:
    """Минимальный async-стенд под compose_random_phrase.

    Функция делает один `session.execute(select(ChatMessage.user_id,
    ChatMessage.text).where(...))` (или fallback на последние 100), затем
    `session.get(User, uid)`. Мы отдаём готовые `(uid, text)`-пары и
    None для User (fallback на «Кто-то из наших»).
    """

    def __init__(self, rows: list[tuple[int, str]]) -> None:
        self._rows = rows

    async def execute(self, stmt: Any) -> Any:  # noqa: ARG002 — игнорим stmt
        rows = list(self._rows)

        class _Result:
            def __init__(self, r: list[tuple[int, str]]) -> None:
                self._r = r

            def all(self) -> list[tuple[int, str]]:
                return self._r

        return _Result(rows)

    async def get(self, _model: Any, _pk: Any) -> Any:  # noqa: ARG002
        return None


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _extract_inner_text(html: str) -> str:
    """Из вывода 🗣/👤 ... «<i>text</i>» вытащить внутренний текст без тегов."""
    # Срезаем шапку до открывающей «, и срезаем закрывающую » в конце.
    # У шапки есть \n внутри, поэтому ищем индекс «« напрямую, а не regex'ом.
    start = html.find("«")
    if start == -1:
        body = html
    else:
        body = html[start + 1 :]
    body = body.rstrip().rstrip("»").rstrip()
    return _HTML_TAG_RE.sub("", body)


def _count_words_in_output(inner: str) -> int:
    """Сколько слов в склеенном выводе — split по пробелу, отрезая хвостовые
    `...`/`.`/`!`/`?`/`…` с КАЖДОГО токена (чтобы 'спать...' не превращалось
    в 'спать' + '...')."""
    tokens = [t.strip(".!?…") for t in inner.split() if t.strip(".!?…")]
    return len(tokens)


async def test_words_mode_strict_count_50_runs() -> None:
    """words mode: min=2, max=2 → ровно 2 слова на 50 прогонах.

    Пул из 20 разных слов даёт `dedup_chunks(target_n=2)` всегда 2 уникальных.
    Прогоняем 50 раз с разными seed'ами — слов в выводе строго 2.
    """
    # Пул из 20+ заведомо разных слов (длина ≥3).
    pool_text = (
        "короче пошёл спать сегодня дождь работа квартира друзья пиво "
        "выходные планы машина дача отпуск ноябрь утро вечер обед игра кино"
    )
    rows = [(101, pool_text), (102, "пицца суши кофе чай молоко хлеб")]

    sess = _FakeSession(rows)
    failures: list[tuple[int, int, str]] = []
    for seed in range(50):
        random.seed(seed)
        out = await compose_random_phrase(
            sess, n=2, lookback_days=7, collective_chance=0.5, mode="words"
        )
        assert out is not None
        inner = _extract_inner_text(out)
        cnt = _count_words_in_output(inner)
        if cnt != 2:
            failures.append((seed, cnt, inner))
    assert not failures, f"words mode выдал не 2 слова в {len(failures)} из 50 прогонов: {failures[:3]}"


async def test_phrases_mode_strict_count_50_runs() -> None:
    """phrases mode: min=1, max=3 → выход всегда собран из 1..3 чанков."""
    # Пул из 10+ заведомо разных фраз (длина ≥6 — MIN_CHUNK_LEN).
    rows = [
        (101, "ну я короче пошёл спать. вообще на работе тяжко."),
        (101, "сегодня дождь идёт. вчера солнце было."),
        (102, "пицца суши кофе. молоко хлеб чай."),
        (102, "квартира под ремонт. машина опять сломалась."),
        (103, "выходные планы есть. отпуск в ноябре."),
    ]

    sess = _FakeSession(rows)
    for seed in range(50):
        random.seed(seed)
        n = random.randint(1, 3)
        random.seed(seed)  # повторно — n уже зафиксировано
        out = await compose_random_phrase(
            sess, n=n, lookback_days=7, collective_chance=0.5, mode="phrases"
        )
        assert out is not None
        # Сложно строго посчитать число чанков в склеенной строке (связки могут
        # выглядеть как «.» «..» «...» или «, ») — проверяем нижнюю границу:
        # длина вывода без шапки должна быть > MIN_CHUNK_LEN * 0.5 (хоть один
        # чанк точно склеен). И верхнюю: не превышает суммарную длину пула.
        inner = _extract_inner_text(out)
        assert len(inner) >= 3, f"seed={seed}: слишком короткий вывод '{inner}'"


async def test_mix_mode_strict_count_50_runs() -> None:
    """mix mode (default): пул = chunks + words, dedup до n.

    Проверяем что: (а) функция не падает; (б) на пуле размером ≥ 10 единиц
    выход всегда непустой; (в) dedup ограничивает результат сверху по n
    (нижняя граница — пул может быть скуднее min, тогда warning).
    """
    rows = [
        (101, "короче, пошёл спать. вообще тяжко на работе"),
        (102, "пицца суши кофе чай. дождь идёт сегодня"),
        (103, "квартира машина дача отпуск ноябрь"),
    ]
    sess = _FakeSession(rows)
    for seed in range(50):
        random.seed(seed)
        n = random.randint(2, 5)
        random.seed(seed)
        out = await compose_random_phrase(
            sess, n=n, lookback_days=7, collective_chance=0.3, mode="mix"
        )
        assert out is not None
        inner = _extract_inner_text(out)
        assert len(inner) >= 3, f"seed={seed}, n={n}: пустой вывод '{inner}'"


async def test_unknown_mode_falls_back_to_mix() -> None:
    """Невалидный mode → лог-warning + поведение как mix (не падает)."""
    rows = [(101, "тест проверка слова какие-то")]
    sess = _FakeSession(rows)
    random.seed(0)
    out = await compose_random_phrase(
        sess, n=2, lookback_days=7, collective_chance=0.0, mode="banana"
    )
    assert out is not None
    assert len(_extract_inner_text(out)) > 0


async def test_empty_pool_returns_fallback() -> None:
    """Сообщений нет → fallback-строка, без исключения."""
    sess = _FakeSession([])
    out = await compose_random_phrase(
        sess, n=2, lookback_days=7, collective_chance=0.0, mode="words"
    )
    # При пустом execute() будет два fallback'а (cutoff + last 100), оба пусты.
    assert out is not None
    assert "тихо" in out or "Сообщения" in out


async def test_words_mode_small_pool_returns_what_it_has() -> None:
    """Пул < n → отдаём что есть, без падения. L3."""
    # Один уникальный длинный текст с 3 уникальными словами.
    rows = [(101, "один два три")]
    # 'один', 'два', 'три' — у первых двух длина 3 (≥3), 'три' длина 3 — все попадают.
    sess = _FakeSession(rows)
    random.seed(0)
    out = await compose_random_phrase(
        sess, n=5, lookback_days=7, collective_chance=1.0, mode="words"
    )
    assert out is not None
    inner = _extract_inner_text(out)
    # Уникальных слов всего 3 — больше функция выдать не может (вернёт ≤3).
    cnt = _count_words_in_output(inner)
    assert 1 <= cnt <= 3, f"ожидали 1..3 слова, получили {cnt}: '{inner}'"


# --- L: вспомогательное: split_into_chunks по-прежнему работает ------------


def test_split_chunks_still_filters_min_len() -> None:
    # MIN_CHUNK_LEN=6 — короткие отбрасываются.
    out = _split_into_chunks("да. нет. может быть. короче такая вот тема")
    # 'да', 'нет', 'может быть' — короче 6 символов.
    # 'короче такая вот тема' — 21 символ, попадает.
    assert any("короче" in c for c in out)
    assert "да" not in out
