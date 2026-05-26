from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, time, timedelta, timezone

import structlog
from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Poll, PollOption, PollVote, User

log = structlog.get_logger()

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# GHG6 hotfix: send-isolation для meetup-полла (см. games_poll._POLL_SEND_TIMEOUT).
_POLL_SEND_TIMEOUT = 8.0


class PollSendFailed(Exception):
    """`bot.send_poll` упал по таймауту/network — Poll в БД НЕ создан.

    HTTP-роут ловит и возвращает 503 — фронт показывает понятную ошибку,
    висячих записей в БД без TG-сообщения не остаётся.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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
    pin: bool = False,
) -> Poll:
    closes_at = (
        datetime.now(timezone.utc) + timedelta(hours=closes_in_hours)
        if closes_in_hours
        else None
    )

    parsed: list[tuple[datetime, bool]] = [_parse_option(o) for o in options]
    labels = [_fmt_option(dt, has_time=ht) for dt, ht in parsed]

    try:
        msg = await asyncio.wait_for(
            bot.send_poll(
                chat_id=chat_id,
                question=question,
                options=labels,
                is_anonymous=False,
                allows_multiple_answers=True,
                open_period=closes_in_hours * 3600 if closes_in_hours else None,
            ),
            timeout=_POLL_SEND_TIMEOUT,
        )
    except (
        TelegramRetryAfter,
        TelegramForbiddenError,
        TelegramNetworkError,
        TelegramAPIError,
        asyncio.TimeoutError,
    ) as exc:
        log.warning(
            "polls.send_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise PollSendFailed(type(exc).__name__) from exc

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

    # GHG6 G2: пин опционально, ошибки глотает помощник — опрос важнее закрепа.
    if pin:
        from app.bot.utils.pinning import pin_message_safely
        await pin_message_safely(bot, chat_id=chat_id, message_id=msg.message_id)

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

    # G3: авто-закрытие при кворуме. Считаем уникальных голосовавших по этому
    # опросу. Если ≥ live_participants_count и фича включена — зовём
    # force_close_poll. Защита от двойного срабатывания — `poll.is_closed`.
    if poll.is_closed:
        return
    from app.services.admin_config import (
        get_polls_live_participants,
        get_polls_quorum_auto_close,
    )

    if not await get_polls_quorum_auto_close(session):
        return
    threshold = await get_polls_live_participants(session)
    unique_voters: int = (
        await session.scalar(
            select(func.count(func.distinct(PollVote.user_id)))
            .join(PollOption, PollOption.id == PollVote.poll_option_id)
            .where(PollOption.poll_id == poll.id)
        )
    ) or 0
    if unique_voters < threshold:
        return

    from app.bot.dispatcher import get_bot

    settings = get_settings()
    if not settings.group_chat_id:
        return
    try:
        bot = get_bot()
    except Exception as exc:  # noqa: BLE001
        log.warning("polls.quorum_no_bot", error=str(exc))
        return
    await force_close_poll(session, bot, poll, chat_id=settings.group_chat_id)


async def force_close_poll(
    session: AsyncSession,
    bot: Bot,
    poll: Poll,
    *,
    chat_id: int,
) -> bool:
    """G3: закрыть полл досрочно (кворум достигнут).

    Зовёт `bot.stop_poll` — TG пришлёт `poll_update` с `is_closed=True`, который
    дальше уйдёт через существующий `on_poll_update` handler и объявит результат.
    Здесь же помечаем `poll.is_closed=True`, чтобы повторный `record_poll_answer`
    не пытался закрывать ещё раз.

    Возвращает True, если stop_poll прошёл успешно.
    """
    if poll.is_closed:
        return False
    if poll.tg_message_id is None:
        return False
    poll.is_closed = True
    await session.commit()
    try:
        await asyncio.wait_for(
            bot.stop_poll(chat_id=chat_id, message_id=poll.tg_message_id),
            timeout=_POLL_SEND_TIMEOUT,
        )
        log.info("polls.force_closed", poll_id=poll.id, tg_poll_id=poll.tg_poll_id)
        return True
    except (
        TelegramRetryAfter,
        TelegramForbiddenError,
        TelegramNetworkError,
        TelegramAPIError,
        asyncio.TimeoutError,
    ) as exc:
        log.warning(
            "polls.stop_poll_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            poll_id=poll.id,
        )
        return False
