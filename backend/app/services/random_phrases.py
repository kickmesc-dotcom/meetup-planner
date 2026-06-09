"""
Daily «рандомные фразы»: берем сообщения одного юзера за неделю, нарезаем на куски и собираем «Шизо-цитату».
Если за неделю пусто — берем последние 100 сообщений из истории.
"""
from __future__ import annotations
import random
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import ChatMessage, User
from app.services.admin_config import (
    get_phrase_generator_version,
    get_random_phrases_collective_chance,
    get_random_phrases_count_range,
    get_random_phrases_enabled,
    get_random_phrases_lookback_days,
    get_random_phrases_mode,
    get_random_phrases_recency_quarantine_hours,
    get_random_phrases_recency_quarantine_weight,
    get_random_phrases_user_chance,
)

log = structlog.get_logger()

MIN_CHUNK_LEN = 6

# --- P13: вес чанка по возрасту сообщения («порог + плато») ---
# Свежие сообщения (младше quarantine_hours) почти не выбираются — это убирает
# «тупое передразнивание» (бот цитирует одно из 3-5 последних сообщений). Старше
# порога — равновесно. Время отправки уже хранится в ChatMessage.sent_at, вес
# считается в Python на уже-извлечённом пуле → НОЛЬ доп. нагрузки на Neon.
RECENCY_QUARANTINE_HOURS_DEFAULT = 18.0
RECENCY_QUARANTINE_WEIGHT_DEFAULT = 0.05


def _recency_weight(
    age_hours: float,
    *,
    quarantine_hours: float = RECENCY_QUARANTINE_HOURS_DEFAULT,
    quarantine_weight: float = RECENCY_QUARANTINE_WEIGHT_DEFAULT,
) -> float:
    """P13: «порог + плато». Сообщение младше quarantine_hours получает
    околонулевой вес quarantine_weight, старше — полный вес 1.0 (все
    «отстоявшиеся» равны). Отрицательный возраст (часы рассинхрона) трактуем
    как свежее."""
    if age_hours < quarantine_hours:
        return quarantine_weight
    return 1.0


def _weighted_sample(
    pool: list[tuple[str, float]],
    k: int,
    *,
    quarantine_hours: float = RECENCY_QUARANTINE_HOURS_DEFAULT,
    quarantine_weight: float = RECENCY_QUARANTINE_WEIGHT_DEFAULT,
) -> list[str]:
    """P13: выбрать k чанков из пула `(text, age_hours)` с весом по возрасту.

    Замена равновесного `[random.choice(pool) for _ in range(k)]`. Выбор с
    возвращением (как раньше — дедуп делает `dedup_chunks` ниже).
    Фолбэк: если суммарный вес ~0 (весь пул свежий → все веса quarantine_weight,
    но это >0; реальный ноль возможен лишь при quarantine_weight=0 и полностью
    свежем пуле) — выбираем равновесно, чтобы не отдать пустоту."""
    if not pool or k <= 0:
        return []
    texts = [t for t, _ in pool]
    weights = [
        _recency_weight(
            age,
            quarantine_hours=quarantine_hours,
            quarantine_weight=quarantine_weight,
        )
        for _, age in pool
    ]
    if sum(weights) <= 0:
        return [random.choice(texts) for _ in range(k)]
    return random.choices(texts, weights=weights, k=k)

# G1: мини-словарик связок между кусочками. Берётся случайный элемент.
# Часть — без пробела (склейка прямо встык), большинство — со связочным словом.
_CONNECTORS: tuple[str, ...] = (
    ", ", ", ", ", ",  # «нейтральные» — в 3 раза чаще
    " и ", " и ",
    " а ",
    " но ",
    " потом ",
    " короче, ",
    " в общем, ",
    " блин, ",
    " типа ",
    " ну ",
    " ну а ",
    " кстати ",
    " вообще ",
    " как бы ",
    ". И ",
    ". А ",
    "... ",
)


def _split_into_chunks(text: str) -> list[str]:
    """Делим сообщение на фрагменты."""
    parts = re.split(r"(?<=[.!?…])\s+|[,;\n]+", text)
    return [p.strip() for p in parts if len(p.strip()) >= MIN_CHUNK_LEN]


# GHG6 L: режим 'words' — отдельные слова длиной ≥ 3 (буквы/цифры в любых
# алфавитах). Цифры тоже считаем словами (`2024` — это слово). Эмодзи и одиночные
# символы пунктуации не считаем словом.
_WORD_RE = re.compile(r"[^\W_]{3,}", re.UNICODE)
MIN_WORD_LEN = 3


def _split_into_words(text: str) -> list[str]:
    """GHG6 L: режим 'words'. Возвращает отдельные слова длиной ≥3.

    Без нормализации регистра — `_glue_words`/`dedup_chunks` сами нормализуют.
    """
    if not text:
        return []
    return [m.group(0) for m in _WORD_RE.finditer(text)]


def _glue_words(words: list[str]) -> str:
    """GHG6 L: склейка слов через пробел. Без connector'ов / запятых, чтобы
    не «надувать» N: пользователь просил 2 слова — должен увидеть 2 слова,
    а не «два слова, и связка». Капитализируем первое, точку в конце ставим
    только если её ещё нет."""
    if not words:
        return "..."
    head = words[0][0].upper() + words[0][1:]
    out = " ".join([head, *words[1:]])
    if not out.endswith((".", "!", "?", "…")):
        out += "..."
    return out


_DUP_WORD_RE = re.compile(r"\b(\w+)(\s+\1\b)+", re.IGNORECASE)
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.!?;:…])")


def _glue_chunks(chunks: list[str]) -> str:
    """G1: сшиваем куски через случайные связки + чистим артефакты.

    Куски, стоящие после связки со словом-склейкой, начинаются со строчной —
    «продолжение мысли». Куски после «.» — с заглавной. В конце:
    схлопываем повторы слов («блин блин» → «блин»), множественные пробелы,
    пробел перед знаком пунктуации.
    """
    if not chunks:
        return "..."

    cleaned = [c.rstrip(".!?,;…") for c in chunks if c]
    if not cleaned:
        return "..."

    out = cleaned[0]
    for nxt in cleaned[1:]:
        conn = random.choice(_CONNECTORS)
        if conn.endswith(", ") or conn.endswith(" ") and conn.strip() not in {".", "..."}:
            piece = nxt[0].lower() + nxt[1:] if nxt else nxt
        else:
            piece = nxt[0].upper() + nxt[1:] if nxt else nxt
        out = f"{out}{conn}{piece}"

    out = _DUP_WORD_RE.sub(r"\1", out)
    out = _MULTI_SPACE_RE.sub(" ", out)
    out = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", out)
    out = out.strip()
    if out:
        out = out[0].upper() + out[1:]
    if out and not out.endswith((".", "!", "?", "…")):
        out += "..."
    return out

# --- GHG6 E4: дедуп цитат внутри одного сообщения ---

_NORMALIZE_WS_RE = re.compile(r"\s+")


def _normalize_chunk(s: str) -> str:
    """Нормализация для сравнения «похожести»: lower + схлопывание пробелов.

    Знаки препинания оставляем — SequenceMatcher всё равно даст высокий ratio
    для «привет, как дела» vs «Привет как дела!», а для коротких фраз сильное
    отличие в пунктуации обычно сигнализирует о разных мыслях.
    """
    return _NORMALIZE_WS_RE.sub(" ", s.strip().lower())


def dedup_chunks(
    picked: list[str],
    *,
    all_pool: list[str],
    target_n: int,
    similarity_threshold: float = 0.85,
) -> list[str]:
    """Удалить почти-дубли из `picked`, добрать недостающее из `all_pool`.

    Алгоритм:
      1. Идём по picked в исходном порядке. Каждый кандидат сравниваем со
         всеми уже отобранными через `SequenceMatcher.ratio()` на
         нормализованных строках. Если max ratio > `similarity_threshold` —
         кандидата отбрасываем.
      2. Если уникальных < target_n — пробуем добрать из `all_pool` (опять же
         избегая похожих). Перемешиваем pool перед добором, чтобы выбор был
         стохастичным.
      3. Если и так не хватает — возвращаем что есть (вызывающий код может
         склеить меньше n кусочков, это не ошибка).
    """
    if target_n <= 0 or not picked:
        return []

    seen_norms: list[str] = []
    unique: list[str] = []

    def _is_dup(candidate: str) -> bool:
        cn = _normalize_chunk(candidate)
        if not cn:
            return True  # пустые строки/whitespace-only считаем дублями
        for prev in seen_norms:
            if SequenceMatcher(None, cn, prev).ratio() > similarity_threshold:
                return True
        seen_norms.append(cn)
        return False

    for c in picked:
        if not _is_dup(c):
            unique.append(c)
        if len(unique) >= target_n:
            return unique

    # Добор: проходим по перемешанному пулу, пропускаем уже взятые и похожие.
    leftovers = [c for c in all_pool if c not in unique]
    random.shuffle(leftovers)
    for c in leftovers:
        if len(unique) >= target_n:
            break
        if not _is_dup(c):
            unique.append(c)

    return unique


async def compose_random_phrase(
    session: AsyncSession,
    n: int,
    *,
    lookback_days: int = 7,
    collective_chance: float = 0.1,
    mode: str = "mix",
    recency_quarantine_hours: float = RECENCY_QUARANTINE_HOURS_DEFAULT,
    recency_quarantine_weight: float = RECENCY_QUARANTINE_WEIGHT_DEFAULT,
) -> str | None:
    """Собрать случайную «шизо-цитату» по N единиц выбранного `mode`.

    `mode` ∈ {'words','phrases','mix'} — единица сборки:
      - words: отдельные слова длиной ≥3 (см. _split_into_words). Склейка пробелом.
      - phrases: чанки по пунктуации (см. _split_into_chunks). Склейка через связки.
      - mix: оба пула объединены, склейка через связки.

    P13: выбор единиц взвешен по возрасту сообщения («порог + плато», см.
    `_recency_weight`) — свежие почти не цитируются, «настоявшиеся» равны.

    Возвращает HTML-готовый текст или None/fallback при пустых данных.
    Если пул < n — отдаёт «сколько есть» с log-warning (это не ошибка).
    """
    # Защита от некорректного n
    n = max(1, n or 3)
    if mode not in ("words", "phrases", "mix"):
        log.warning("random_phrases.bad_mode_fallback_mix", got=mode)
        mode = "mix"

    now = datetime.now(timezone.utc)

    # 1. Сначала пробуем за последние lookback_days дней
    cutoff = now - timedelta(days=lookback_days)
    stmt = select(ChatMessage.user_id, ChatMessage.text, ChatMessage.sent_at).where(
        ChatMessage.sent_at >= cutoff
    )
    rows = list((await session.execute(stmt)).all())

    # 2. Если за неделю пусто — откатываемся к последним 100 сообщениям вообще
    if not rows:
        log.info("random_phrases.weekly_empty_falling_back")
        stmt = (
            select(ChatMessage.user_id, ChatMessage.text, ChatMessage.sent_at)
            .order_by(ChatMessage.sent_at.desc())
            .limit(100)
        )
        rows = list((await session.execute(stmt)).all())

    if not rows:
        return "<i>(В чате подозрительно тихо... Мне нечего цитировать)</i>"

    # 3. Группируем единицы по mode. P13: каждая единица несёт возраст своего
    # сообщения (часы) — кортеж (text, age_hours) для взвешенного выбора.
    by_user: dict[int, list[tuple[str, float]]] = {}
    all_units: list[tuple[str, float]] = []
    for uid, text, sent_at in rows:
        if mode == "words":
            units = _split_into_words(text or "")
        elif mode == "phrases":
            units = _split_into_chunks(text or "")
        else:  # mix
            units = _split_into_chunks(text or "") + _split_into_words(text or "")
        if units:
            age_hours = max(0.0, (now - sent_at).total_seconds() / 3600.0)
            aged = [(u, age_hours) for u in units]
            by_user.setdefault(int(uid), []).extend(aged)
            all_units.extend(aged)

    pool_sizes = {uid: len(units) for uid, units in by_user.items()}
    log.info(
        "random_phrases.pool_ready",
        mode=mode,
        total_units=len(all_units),
        users_with_units=len(by_user),
        pool_sizes=pool_sizes,
        recency_quarantine_hours=recency_quarantine_hours,
        recency_quarantine_weight=recency_quarantine_weight,
    )

    if not all_units:
        return "<i>(Сообщения есть, но они слишком короткие для цитат)</i>"

    # 4. Решаем: Шизо-цитата юзера (1 - collective_chance) или Голос Шестерки.
    is_collective = (random.random() < collective_chance) or (len(by_user) < 2)

    if is_collective:
        all_texts = [t for t, _ in all_units]
        picked_raw = _weighted_sample(
            all_units,
            n * 2,
            quarantine_hours=recency_quarantine_hours,
            quarantine_weight=recency_quarantine_weight,
        )
        picked = dedup_chunks(picked_raw, all_pool=all_texts, target_n=n)
        if len(picked) < n:
            log.warning(
                "random_phrases.pool_undersized",
                mode=mode,
                requested=n,
                got=len(picked),
                pool=len(all_units),
            )
        glued = _glue_words(picked) if mode == "words" else _glue_chunks(picked)
        return f"🗣 <b>Сводный хор Шестёрки:</b>\n\n«<i>{glued}</i>»"

    # 5. Шизо-цитата конкретного автора
    target_uid = random.choice(list(by_user.keys()))
    user_pool = by_user[target_uid]
    user_texts = [t for t, _ in user_pool]

    picked_raw = _weighted_sample(
        user_pool,
        n * 2,
        quarantine_hours=recency_quarantine_hours,
        quarantine_weight=recency_quarantine_weight,
    )
    picked = dedup_chunks(picked_raw, all_pool=user_texts, target_n=n)
    if len(picked) < n:
        log.warning(
            "random_phrases.pool_undersized",
            mode=mode,
            requested=n,
            got=len(picked),
            pool=len(user_pool),
            user_id=target_uid,
        )
    glued = _glue_words(picked) if mode == "words" else _glue_chunks(picked)

    user = await session.get(User, target_uid)
    author_name = user.display_name if user else "Кто-то из наших"
    return f"👤 <b>{author_name} вещает:</b>\n\n«<i>{glued}</i>»"

def format_bot_reply(
    chunks: list[str],
    *,
    n: int = 2,
    aged_chunks: list[tuple[str, float]] | None = None,
    recency_quarantine_hours: float = RECENCY_QUARANTINE_HOURS_DEFAULT,
    recency_quarantine_weight: float = RECENCY_QUARANTINE_WEIGHT_DEFAULT,
) -> str:
    """GHG6 hotfix: чистая функция форматирования reply-фразы бота.

    Без префиксов 🗣/👤 — это голос самого бота, не цитата участника.
    На вход — пул чанков (любого размера, в т.ч. пустой). Берёт случайные
    `n*2`, фильтрует через `dedup_chunks` до `n`, склеивает.

    P13: если передан `aged_chunks` (`(text, age_hours)`) — выбор взвешен по
    возрасту (см. `_recency_weight`): reply на @mention — главный источник
    «передразнивания» свежих сообщений. Без `aged_chunks` поведение прежнее
    (равновесный `random.sample`) — обратная совместимость.
    """
    if not chunks:
        return "<i>(нет слов...)</i>"
    n = max(1, n)
    if aged_chunks:
        picked_raw = _weighted_sample(
            aged_chunks,
            min(len(aged_chunks), n * 2),
            quarantine_hours=recency_quarantine_hours,
            quarantine_weight=recency_quarantine_weight,
        )
    else:
        picked_raw = random.sample(chunks, min(len(chunks), n * 2))
    picked = dedup_chunks(picked_raw, all_pool=chunks, target_n=n)
    glued = _glue_chunks(picked)
    return f"<i>{glued}</i>"


async def compose_bot_reply_phrase(
    session: AsyncSession,
    *,
    n: int = 2,
    lookback_days: int = 7,
    recency_quarantine_hours: float = RECENCY_QUARANTINE_HOURS_DEFAULT,
    recency_quarantine_weight: float = RECENCY_QUARANTINE_WEIGHT_DEFAULT,
) -> str | None:
    """GHG6 hotfix: короткая «шизо-цитата» от лица БОТА, без шапки автора.

    Используется в `bot_reactions._react` для ответа на @mention / reply.
    Семантика отличается от `compose_random_phrase`:
    - НЕТ префиксов 🗣 «Сводный хор» / 👤 «Имя вещает» — иначе reply бота
      выглядит как цитата от другого участника (что вводило в заблуждение).
    - Берём чанки из общего пула (всех whitelist-юзеров) — это «голос
      бота», не пересказ конкретного участника.
    - По умолчанию короче автопоста (n=2), чтобы reply не растекался.

    P13: выбор чанков взвешен по возрасту сообщения (см. `_recency_weight`) —
    reply больше не «передразнивает» 3-5 последних сообщений.

    Возвращает HTML-готовый текст (`<i>…</i>`) или короткий fallback при
    пустом пуле.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    stmt = select(ChatMessage.text, ChatMessage.sent_at).where(
        ChatMessage.sent_at >= cutoff
    )
    rows = list((await session.execute(stmt)).all())

    if not rows:
        stmt = (
            select(ChatMessage.text, ChatMessage.sent_at)
            .order_by(ChatMessage.sent_at.desc())
            .limit(100)
        )
        rows = list((await session.execute(stmt)).all())

    all_chunks: list[str] = []
    aged_chunks: list[tuple[str, float]] = []
    for text, sent_at in rows:
        chunks = _split_into_chunks(text or "")
        if chunks:
            age_hours = max(0.0, (now - sent_at).total_seconds() / 3600.0)
            all_chunks.extend(chunks)
            aged_chunks.extend((c, age_hours) for c in chunks)

    return format_bot_reply(
        all_chunks,
        n=n,
        aged_chunks=aged_chunks,
        recency_quarantine_hours=recency_quarantine_hours,
        recency_quarantine_weight=recency_quarantine_weight,
    )


async def run_random_phrases_job(bot: Bot) -> None:
    settings = get_settings()
    if not settings.group_chat_id:
        log.error("random_phrases.no_chat_id_configured")
        return

    sm = get_sessionmaker()
    async with sm() as session:
        if not await get_random_phrases_enabled(session):
            log.info("random_phrases.disabled_in_settings")
            return

        user_chance = await get_random_phrases_user_chance(session)
        if user_chance < 1.0 and random.random() > user_chance:
            log.info("random_phrases.skipped_by_chance", chance=user_chance)
            return

        cmin, cmax = await get_random_phrases_count_range(session)
        lookback_days = await get_random_phrases_lookback_days(session)
        collective_chance = await get_random_phrases_collective_chance(session)
        mode = await get_random_phrases_mode(session)
        recency_hours = await get_random_phrases_recency_quarantine_hours(session)
        recency_weight = await get_random_phrases_recency_quarantine_weight(session)
        # GHG8 P6.3: версия генератора. Расписание/шанс/кулдауны выше — общие
        # для обеих версий (P6.2.b), переключается только composer.
        generator_version = await get_phrase_generator_version(session)
        n = random.randint(cmin, cmax)
        log.info(
            "random_phrases.starting",
            n=n,
            cmin=cmin,
            cmax=cmax,
            mode=mode,
            generator_version=generator_version,
            lookback_days=lookback_days,
            collective_chance=collective_chance,
            recency_quarantine_hours=recency_hours,
            recency_quarantine_weight=recency_weight,
            chat_id=settings.group_chat_id,
        )

        try:
            text = None
            if generator_version == "personas":
                # P6.2: v2 «с типажами». None (нет пригодных персоналий) →
                # фолбэк на legacy ниже — пост не срывается (GHG7.txt стр. 162).
                from app.services.personas import compose_persona_phrase

                text = await compose_persona_phrase(
                    session, lookback_days=lookback_days
                )
                if text is None:
                    log.info("random_phrases.personas_empty_fallback_legacy")
            if text is None:
                text = await compose_random_phrase(
                    session,
                    n,
                    lookback_days=lookback_days,
                    collective_chance=collective_chance,
                    mode=mode,
                    recency_quarantine_hours=recency_hours,
                    recency_quarantine_weight=recency_weight,
                )
        except Exception:
            log.exception("random_phrases.compose_failed")
            text = "<i>(Ошибка при сборке цитаты, техник уже выехал)</i>"

    if not text:
        log.warning("random_phrases.empty_text_after_compose")
        return

    try:
        await bot.send_message(
            chat_id=settings.group_chat_id,
            text=text,
            parse_mode="HTML",
            disable_notification=True,
        )
        log.info("random_phrases.posted", chat_id=settings.group_chat_id)
    except TelegramAPIError as exc:
        log.warning("random_phrases.telegram_api_error", error=str(exc))
    except Exception:
        log.exception("random_phrases.unexpected_error")