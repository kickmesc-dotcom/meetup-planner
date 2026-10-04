"""GHG11: «сегодня висит звание» — лох дня / чухан недели / червь-пидор.

Единый источник правды для плашек над головой в ленте и в чужом профиле. Логика
та же, что у `/api/titles/current` (шапки аватарки на календаре), но здесь мы
отдаём ещё и ПРИЧИНУ («за что») и умеем строить срез по всем участникам одним
проходом (для ленты — без N+1).

Звание — «сегодняшнее»:
* лох дня    — последний официальный ролл за текущий UTC-день (без `source=duel`);
* чухан недели — неделя, начавшаяся в понедельник, и только ДОСТАВЛЕННАЯ;
* червь-пидор — активная переходящая запись (`worm_assignments.ended_at IS NULL`).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LoserRoll, WeeklyChukhan
from app.services.chukhan import current_week_start
from app.services.loser import get_current_worm

EMOJI_LOSER = "👑"
EMOJI_CHUKHAN = "💩"
EMOJI_WORM = "🪱"


async def today_loser_roll(session: AsyncSession) -> LoserRoll | None:
    """Последний официальный лох-ролл за текущий UTC-день. None — не было."""
    now = datetime.now(timezone.utc)
    day_start = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc)
    day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999999)
    return await session.scalar(
        select(LoserRoll)
        .where(
            LoserRoll.rolled_at >= day_start,
            LoserRoll.rolled_at <= day_end,
            or_(LoserRoll.source != "duel", LoserRoll.source.is_(None)),
        )
        .order_by(LoserRoll.rolled_at.desc())
        .limit(1)
    )


async def current_chukhan_row(session: AsyncSession) -> WeeklyChukhan | None:
    """Чухан текущей недели — только доставленный (posted_at IS NOT NULL)."""
    return await session.scalar(
        select(WeeklyChukhan).where(
            WeeklyChukhan.week_start == current_week_start(),
            WeeklyChukhan.posted_at.is_not(None),
        )
    )


async def titles_for_user(session: AsyncSession, user_id: int) -> dict:
    """Звания одного участника сегодня: флаги + причины (для профиля)."""
    worm = await get_current_worm(session)
    chukhan = await current_chukhan_row(session)
    loser = await today_loser_roll(session)
    return {
        "loser": loser is not None and loser.loser_user_id == user_id,
        "loser_reason": (
            (loser.reason_text or "").strip() or None
            if loser is not None and loser.loser_user_id == user_id
            else None
        ),
        "chukhan": chukhan is not None and chukhan.user_id == user_id,
        "chukhan_reason": (
            (chukhan.reason_text or "").strip() or None
            if chukhan is not None and chukhan.user_id == user_id
            else None
        ),
        "worm": worm is not None and worm.user_id == user_id,
    }


async def badge_map(session: AsyncSession) -> dict[int, list[str]]:
    """user_id → список эмодзи-плашек сегодня (для ленты, одним проходом)."""
    out: dict[int, list[str]] = {}
    worm = await get_current_worm(session)
    if worm is not None:
        out.setdefault(worm.user_id, []).append(EMOJI_WORM)
    chukhan = await current_chukhan_row(session)
    if chukhan is not None:
        out.setdefault(chukhan.user_id, []).append(EMOJI_CHUKHAN)
    loser = await today_loser_roll(session)
    if loser is not None:
        out.setdefault(loser.loser_user_id, []).append(EMOJI_LOSER)
    return out
