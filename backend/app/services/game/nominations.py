"""GHG11: номинации игр и голосование «во что сыграем» прямо в мини-аппе.

Список номинированных игр уже живёт в `game_nominations` (сервис `games`), а
голосование в чате шло Telegram-поллом. Мини-аппу нужна своя поверхность
голосования, которую чат не требует: голос храним в `event_log`
(kind=``game_vote``), без миграций.

Голос — ОДИН на участника (single choice): новая номинация заменяет прежнюю,
повторный голос за ту же — снимает.
"""
from __future__ import annotations

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EventLog

log = structlog.get_logger()

VOTE_KIND = "game_vote"


async def vote_counts(session: AsyncSession, nomination_ids: list[int]) -> dict[int, int]:
    """nomination_id → число голосов."""
    if not nomination_ids:
        return {}
    rows = await session.execute(
        select(EventLog.payload["nomination_id"].as_integer()).where(
            EventLog.kind == VOTE_KIND,
            EventLog.payload["nomination_id"].as_integer().in_(nomination_ids),
        )
    )
    counts: dict[int, int] = {}
    for (nid,) in rows.all():
        if nid is None:
            continue
        counts[int(nid)] = counts.get(int(nid), 0) + 1
    return counts


async def my_vote(session: AsyncSession, user_id: int) -> int | None:
    """За какую номинацию голосовал участник (None — ни за какую)."""
    row = await session.scalar(
        select(EventLog.payload["nomination_id"].as_integer())
        .where(
            EventLog.kind == VOTE_KIND,
            EventLog.payload["user_id"].as_integer() == int(user_id),
        )
        .order_by(EventLog.id.desc())
        .limit(1)
    )
    return int(row) if row is not None else None


async def toggle_vote(
    session: AsyncSession, *, nomination_id: int, user_id: int
) -> tuple[bool, int]:
    """Проголосовать/снять голос. Возвращает (проголосовал_за_неё, число голосов)."""
    current = await my_vote(session, user_id)
    if current == nomination_id:
        await session.execute(
            sa_delete(EventLog).where(
                EventLog.kind == VOTE_KIND,
                EventLog.payload["user_id"].as_integer() == int(user_id),
            )
        )
        await session.commit()
        voted = False
    else:
        # single choice: убираем прежний голос, ставим новый.
        await session.execute(
            sa_delete(EventLog).where(
                EventLog.kind == VOTE_KIND,
                EventLog.payload["user_id"].as_integer() == int(user_id),
            )
        )
        session.add(
            EventLog(
                kind=VOTE_KIND,
                actor_user_id=user_id,
                payload={"nomination_id": int(nomination_id), "user_id": int(user_id)},
            )
        )
        await session.commit()
        voted = True
    counts = await vote_counts(session, [nomination_id])
    log.info("game.nomination_vote", nomination_id=nomination_id, user_id=user_id, voted=voted)
    return voted, counts.get(nomination_id, 0)
