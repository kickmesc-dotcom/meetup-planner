from __future__ import annotations

import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LoserRoll, User
from app.services.admin_config import get_loser_reasons

COOLDOWN = timedelta(hours=12)

LOSER_REASONS = [
    "слился с последней встречи",
    "неделю не заходил в чат",
    "тусуется с левыми типами",
    "выбирает семью",
    "воняет говной",
    "дохера умничает",
    "кидает протухшие мемы",
    "его реакции — это просто 👌",
    "ушёл в себя на неделю",
    "снова ставит \"под вопросом\"",
    "не признает, кто здесь батя",
    "всплывает только когда ему что-то надо",
    "вечно ноет",
    "сидит онлайн и молчит как труп",
    "слишком занят своей важной жопой",
    "не выкупает рофлы",
    "не выкупает за метаиронию",
    "опять не выпил таблетки",
    "путает чат с доской объявлений",
    "забыл дорогу в конфу",
    "снова пропал без вести",
    "ведёт себя как NPC",
    "отвечает раз в трое суток",
    "как обычно дал заднюю",
    "пришёл, увидел, обосрался",
    "ссыт нормального движняка",
    "вечно на серьёзных щах",
    "мутит мутные схемы",
    "потерялся между диваном и кухней",
    "ждёт особого приглашения как принцесса",
    "его юмор умер в 2017",
    "вечно в режиме энергосбережения",
    "опять включил режим призрака",
    "разболталось гнездо",
    "сидит на морозе как неродной",
    "воюет не в ту сторону",
    "обитает где-то между кринжем и позором",
    "общается как будто делает одолжение",
    "давно не трогал траву",
    "строит из себя занятого миллиардера",
    "тонет в своей драме",
    "выходит на связь только по праздникам",
    "путает дружбу с подпиской",
    "слишком нестабилен даже для мемов",
    "маячит, аки говно в проруби",
]


async def time_until_next_roll(session: AsyncSession) -> timedelta:
    last = await session.scalar(select(func.max(LoserRoll.rolled_at)))
    if last is None:
        return timedelta(0)
    elapsed = datetime.now(timezone.utc) - last
    remaining = COOLDOWN - elapsed
    return max(timedelta(0), remaining)


async def roll_loser(
    session: AsyncSession,
    *,
    rolled_by: User,
    on_announce: Callable[[LoserRoll, User], Awaitable[None]] | None = None,
) -> LoserRoll:
    """Roll a loser atomically with the chat announcement.

    If `on_announce` is provided, it's invoked AFTER flushing the row but
    BEFORE commit. If it raises, the transaction is rolled back so the
    roll can be retried — no «phantom» DB row without a TG message.
    """
    remaining = await time_until_next_roll(session)
    if remaining > timedelta(0):
        raise CooldownError(remaining)

    users = list((await session.scalars(select(User))).all())
    if not users:
        raise RuntimeError("no users in DB")

    loser = random.choice(users)
    # Берём актуальный список из admin_config (с фолбэком на in-code LOSER_REASONS).
    reasons = await get_loser_reasons(session)
    reason = random.choice(reasons or LOSER_REASONS)
    row = LoserRoll(
        rolled_by=rolled_by.id,
        loser_user_id=loser.id,
        reason_text=reason,
    )
    session.add(row)
    await session.flush()  # populate row.id without committing

    if on_announce is not None:
        try:
            await on_announce(row, loser)
        except Exception:
            await session.rollback()
            raise

    await session.commit()
    await session.refresh(row)
    return row


async def delete_last_loser(session: AsyncSession) -> LoserRoll | None:
    """Drop the most recent loser roll (for manual re-roll). Returns the
    deleted row or None if there was nothing to delete."""
    row = await session.scalar(
        select(LoserRoll).order_by(desc(LoserRoll.rolled_at)).limit(1)
    )
    if row is None:
        return None
    await session.delete(row)
    await session.commit()
    return row


async def loser_stats(session: AsyncSession) -> dict[int, int]:
    rows = (
        await session.execute(
            select(LoserRoll.loser_user_id, func.count())
            .group_by(LoserRoll.loser_user_id)
        )
    ).all()
    return {uid: int(cnt) for uid, cnt in rows}


async def last_loser(session: AsyncSession) -> LoserRoll | None:
    return await session.scalar(select(LoserRoll).order_by(desc(LoserRoll.rolled_at)).limit(1))


class CooldownError(Exception):
    def __init__(self, remaining: timedelta):
        self.remaining = remaining
        super().__init__(f"cooldown {remaining}")
