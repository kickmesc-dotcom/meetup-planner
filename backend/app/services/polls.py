from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone

import structlog
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Poll, PollOption, PollVote, User

log = structlog.get_logger()

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_option(raw: str | datetime | date) -> tuple[datetime, bool]:
    """Принимает ISO datetime, YYYY-MM-DD или объект date/datetime.

    Возвращает (datetime, has_time). `has_time=False` означает, что пользователь
    не указывал время (date-only вариант) — label будет без часа, ends_at = +24ч.
    """
    if isinstance(raw, datetime):
        return raw, True
    if isinstance(raw, date):
        return datetime.combine(raw, time(0, 0)), False
    if not isinstance(raw, str):
        raise ValueError(f"bad_option_type: {type(raw).__name__}")
    s = raw.strip()
    if _DATE_ONLY_RE.match(s):
        d = date.fromisoformat(s)
        return datetime.combine(d, time(0, 0)), False
    # Полный datetime ISO. Поддерживаем `Z` суффикс.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s), True


def _fmt_option(dt: datetime, *, has_time: bool) -> str:
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    if has_time:
        return f"{days[dt.weekday()]} {dt.strftime('%d.%m %H:%M')}"
    return f"{days[dt.weekday()]} {dt.strftime('%d.%m')}"


async def create_poll_in_chat(
    session: AsyncSession,
    bot: Bot,
    *,
    created_by: User,
    chat_id: int,
    question: str,
    options: list[str | datetime | date],
    closes_in_hours: int | None,
) -> Poll:
    closes_at = (
        datetime.now(timezone.utc) + timedelta(hours=closes_in_hours)
        if closes_in_hours
        else None
    )

    parsed: list[tuple[datetime, bool]] = [_parse_option(o) for o in options]
    labels = [_fmt_option(dt, has_time=ht) for dt, ht in parsed]

    msg = await bot.send_poll(
        chat_id=chat_id,
        question=question,
        options=labels,
        is_anonymous=False,
        allows_multiple_answers=True,
        open_period=closes_in_hours * 3600 if closes_in_hours else None,
    )

    poll = Poll(
        created_by=created_by.id,
        question=question,
        closes_at=closes_at,
        tg_message_id=msg.message_id,
        tg_poll_id=msg.poll.id if msg.poll else None,
    )
    session.add(poll)
    await session.flush()

    for (dt, has_time), label in zip(parsed, labels, strict=True):
        ends = dt + (timedelta(hours=2) if has_time else timedelta(hours=24))
        session.add(
            PollOption(
                poll_id=poll.id,
                starts_at=dt,
                ends_at=ends,
                label=label,
            )
        )
    await session.commit()
    await session.refresh(poll)
    return poll


async def record_poll_answer(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    chosen_option_indexes: list[int],
    tg_poll_id: str,
) -> None:
    """Telegram poll_answer: пользователь выбрал эти индексы (пусто = снял голос).
    Матчим строго по `tg_poll_id`, чтобы голоса не утекали в чужой опрос
    при двух параллельных голосованиях."""
    user = (
        await session.scalars(
            select(User).where(User.telegram_id == telegram_user_id)
        )
    ).first()
    if not user:
        log.info("poll.answer_unknown_user", telegram_id=telegram_user_id)
        return

    poll = (
        await session.scalars(select(Poll).where(Poll.tg_poll_id == tg_poll_id))
    ).first()
    if not poll:
        log.info("poll.answer_unknown_poll", tg_poll_id=tg_poll_id)
        return

    options = list(
        (
            await session.scalars(
                select(PollOption).where(PollOption.poll_id == poll.id).order_by(PollOption.id)
            )
        ).all()
    )

    # Drop any prior votes by this user on this poll, then re-insert.
    prior = list(
        (
            await session.scalars(
                select(PollVote)
                .join(PollOption, PollOption.id == PollVote.poll_option_id)
                .where(PollOption.poll_id == poll.id, PollVote.user_id == user.id)
            )
        ).all()
    )
    for v in prior:
        await session.delete(v)

    for idx in chosen_option_indexes:
        if 0 <= idx < len(options):
            session.add(PollVote(poll_option_id=options[idx].id, user_id=user.id))

    await session.commit()
