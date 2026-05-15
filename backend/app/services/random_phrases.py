"""
Daily «рандомные фразы»: берем сообщения одного юзера за неделю, нарезаем на куски и собираем «Шизо-цитату».
Если за неделю пусто — берем последние 100 сообщений из истории.
"""
from __future__ import annotations
import random
import re
from datetime import datetime, timedelta, timezone
import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import ChatMessage, User
from app.services.admin_config import (
    get_random_phrases_collective_chance,
    get_random_phrases_count_range,
    get_random_phrases_enabled,
    get_random_phrases_lookback_days,
    get_random_phrases_user_chance,
)

log = structlog.get_logger()

MIN_CHUNK_LEN = 6

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

async def compose_random_phrase(
    session: AsyncSession,
    n: int,
    *,
    lookback_days: int = 7,
    collective_chance: float = 0.1,
) -> str | None:
    # Защита от некорректного n
    n = max(1, n or 3)

    # 1. Сначала пробуем за последние lookback_days дней
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    stmt = select(ChatMessage.user_id, ChatMessage.text).where(ChatMessage.sent_at >= cutoff)
    rows = list((await session.execute(stmt)).all())
        
    # 2. Если за неделю пусто — откатываемся к последним 100 сообщениям вообще
    if not rows:
        log.info("random_phrases.weekly_empty_falling_back")
        stmt = (
            select(ChatMessage.user_id, ChatMessage.text)
            .order_by(ChatMessage.sent_at.desc())
            .limit(100)
        )
        rows = list((await session.execute(stmt)).all())

    if not rows:
        return "<i>(В чате подозрительно тихо... Мне нечего цитировать)</i>"

    # 3. Группируем чанки
    by_user: dict[int, list[str]] = {}
    all_chunks: list[str] = []
    for uid, text in rows:
        chunks = _split_into_chunks(text or "")
        if chunks:
            by_user.setdefault(int(uid), []).extend(chunks)
            all_chunks.extend(chunks)

    # Видимость пула: сколько фраз есть на каждого участника.
    pool_sizes = {uid: len(chunks) for uid, chunks in by_user.items()}
    log.info(
        "random_phrases.pool_ready",
        total_chunks=len(all_chunks),
        users_with_chunks=len(by_user),
        pool_sizes=pool_sizes,
    )

    if not all_chunks:
        return "<i>(Сообщения есть, но они слишком короткие для цитат)</i>"

    # 4. Решаем: Шизо-цитата юзера (1 - collective_chance) или Голос Шестерки.
    is_collective = (random.random() < collective_chance) or (len(by_user) < 2)
        
    if is_collective:
        picked = random.sample(all_chunks, min(len(all_chunks), n))
        glued = _glue_chunks(picked)
        return f"🗣 <b>Сводный хор Шестёрки:</b>\n\n«<i>{glued}</i>»"

    # 5. Шизо-цитата конкретного автора
    target_uid = random.choice(list(by_user.keys()))
    user_pool = by_user[target_uid]

    picked = [random.choice(user_pool) for _ in range(n)]
    glued = _glue_chunks(picked)

    user = await session.get(User, target_uid)
    author_name = user.display_name if user else "Кто-то из наших"
    return f"👤 <b>{author_name} вещает:</b>\n\n«<i>{glued}</i>»"

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
        n = random.randint(cmin, cmax)
        log.info(
            "random_phrases.starting",
            n=n,
            cmin=cmin,
            cmax=cmax,
            lookback_days=lookback_days,
            collective_chance=collective_chance,
            chat_id=settings.group_chat_id,
        )

        try:
            text = await compose_random_phrase(
                session,
                n,
                lookback_days=lookback_days,
                collective_chance=collective_chance,
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