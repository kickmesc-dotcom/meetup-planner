"""GHG6 N2: пост-фактум опрос «как собрались?» с 5★ + опцией «меня не было».

Логика:
1. `enumerate_pending_meetings(session)` — найти все Meeting со status='confirmed',
   у которых `starts_at + 1 day <= now`, и для которых ещё нет ни одной записи
   в `meeting_feedback`. (Не запускать опрос второй раз для одной встречи.)
2. `start_feedback_poll(bot, session, meeting)` — публикует Telegram-poll с
   6 вариантами «★/★★/★★★/★★★★/★★★★★/меня не было». tg_poll_id записывается в
   `polls`-таблицу с `kind='meeting_feedback'`, чтобы `on_poll_update` мог
   найти связанную Meeting.
3. `submit_feedback(session, meeting_id, user_id, rating?|was_absent, reason?)` —
   ON CONFLICT UPDATE по `(meeting_id, user_id)`. При `was_absent=True` зовёт
   `add_chukhan_weight(tg_id=..., delta=absence_weight)` и (если notify_absence)
   шлёт тост в group_chat_id.

Scheduler-job `JOB_MEETING_FEEDBACK` — крутится раз в день (12:07 по
`scheduler_tz`); проходит по `enumerate_pending_meetings`, для каждого зовёт
`start_feedback_poll`. Идемпотентен: если опрос уже запущен, дубликата не будет
(check по `polls.kind='meeting_feedback'` + `polls.tg_poll_id`-link через
`Meeting.id` — хранится в `Poll.game_nomination_id` как «meeting_id», т.к.
отдельной колонки в schema мы не вводим, переиспользуем существующее int-поле).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Meeting, MeetingFeedback, Poll, User
from app.services.admin_config import (
    add_chukhan_weight,
    get_meeting_feedback_absence_weight,
    get_meeting_feedback_enabled,
    get_meeting_feedback_notify_absence,
)

log = structlog.get_logger()

# Telegram-poll опции (порядок совпадает с rating_for_option_index).
FEEDBACK_OPTIONS: tuple[str, ...] = (
    "★",
    "★★",
    "★★★",
    "★★★★",
    "★★★★★",
    "меня не было",
)
# Индекс 0..4 → rating 1..5; индекс 5 → was_absent.
FEEDBACK_ABSENT_INDEX = 5

# Метка kind для Poll-таблицы. Не путать с 'game_choice'/'game_when'/'zaebal'.
POLL_KIND_MEETING_FEEDBACK = "meeting_feedback"


async def enumerate_pending_meetings(
    session: AsyncSession, *, now: datetime | None = None
) -> list[Meeting]:
    """Встречи, для которых нужно запустить feedback-опрос.

    Критерии:
    - `status = 'confirmed'`
    - `starts_at + 1 day <= now` (встреча прошла больше суток назад — фронт-граница
      «следующий день после события»; меньше суток — даём людям проспаться).
    - ещё нет ни одной записи в `meeting_feedback` И ещё нет открытого
      `Poll(kind='meeting_feedback', game_nomination_id=meeting.id)`.

    `now` параметр — для тестов; в проде None → datetime.now(UTC).
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=1)
    # Window: встречи за последние 14 дней — старые feedback не запускаем
    # (даже если их пропустили), пользователю это уже неинтересно.
    earliest = now - timedelta(days=14)
    rows: list[Meeting] = list(
        (
            await session.scalars(
                select(Meeting)
                .where(
                    and_(
                        Meeting.status == "confirmed",
                        Meeting.starts_at <= cutoff,
                        Meeting.starts_at >= earliest,
                    )
                )
                .order_by(Meeting.starts_at.desc())
            )
        ).all()
    )
    if not rows:
        return []

    # Отфильтровать те, где уже есть открытый poll или хотя бы один feedback-row.
    meeting_ids = [m.id for m in rows]
    existing_polls = set(
        (
            await session.scalars(
                select(Poll.game_nomination_id).where(
                    and_(
                        Poll.kind == POLL_KIND_MEETING_FEEDBACK,
                        Poll.game_nomination_id.in_(meeting_ids),
                    )
                )
            )
        ).all()
    )
    existing_feedback = set(
        (
            await session.scalars(
                select(MeetingFeedback.meeting_id).where(
                    MeetingFeedback.meeting_id.in_(meeting_ids)
                )
            )
        ).all()
    )
    skipped = existing_polls | existing_feedback
    return [m for m in rows if m.id not in skipped]


async def start_feedback_poll(
    bot: Bot, session: AsyncSession, meeting: Meeting
) -> Poll | None:
    """Опубликовать Telegram-poll «как собрались?» и записать в Poll-таблицу.

    Возвращает Poll-row или None если group_chat_id не настроен / TG отказал.
    Caller (scheduler) сам решает что делать с None — обычно просто залогировать.
    """
    settings = get_settings()
    if not settings.group_chat_id:
        log.warning("meeting_feedback.no_chat_id", meeting_id=meeting.id)
        return None
    question = (
        f"Как собрались «{meeting.title}»? "
        f"({meeting.starts_at.strftime('%d.%m')})"
    )
    try:
        sent = await bot.send_poll(
            chat_id=settings.group_chat_id,
            question=question,
            options=list(FEEDBACK_OPTIONS),
            is_anonymous=False,  # нужно знать кто голосовал для weight-delta
            allows_multiple_answers=False,
            type="regular",
        )
    except TelegramAPIError as exc:
        log.warning(
            "meeting_feedback.send_failed",
            meeting_id=meeting.id,
            error=str(exc),
        )
        return None

    db_poll = Poll(
        created_by=meeting.created_by,
        question=question,
        tg_message_id=sent.message_id,
        tg_poll_id=sent.poll.id if sent.poll else None,
        kind=POLL_KIND_MEETING_FEEDBACK,
        # Используем game_nomination_id как generic int-link на Meeting.id
        # — отдельной FK-колонки не добавляли (миграция бы тогда тянула
        # ALTER TABLE polls; обошлись типизацией kind).
        game_nomination_id=meeting.id,
    )
    session.add(db_poll)
    await session.commit()
    log.info(
        "meeting_feedback.poll_started",
        meeting_id=meeting.id,
        poll_id=db_poll.id,
        tg_poll_id=db_poll.tg_poll_id,
    )
    return db_poll


async def submit_feedback(
    session: AsyncSession,
    *,
    meeting_id: int,
    user_id: int,
    rating: int | None = None,
    was_absent: bool = False,
    reason_text: str | None = None,
    bot: Bot | None = None,
) -> MeetingFeedback:
    """ON CONFLICT UPDATE по (meeting_id, user_id).

    При `was_absent=True`:
      - rating игнорируется (записываем NULL),
      - chukhan-weight юзера поднимается на `absence_weight_delta` (default 0.5),
      - если `notify_absence` true и `bot` передан — шлём тост в group_chat.

    Валидация:
      - либо rating ∈ 1..5 (и was_absent=false), либо was_absent=True (rating=None).
      - смешанное → ValueError.
    """
    if was_absent:
        rating = None
    else:
        if rating is None or rating < 1 or rating > 5:
            raise ValueError("rating must be in 1..5 when was_absent is False")

    existing = await session.scalar(
        select(MeetingFeedback).where(
            and_(
                MeetingFeedback.meeting_id == meeting_id,
                MeetingFeedback.user_id == user_id,
            )
        )
    )
    if existing is not None:
        # Если предыдущий голос НЕ был was_absent, а новый — был, начисляем delta.
        # Если предыдущий БЫЛ was_absent — повтор не штрафуем повторно.
        previously_absent = existing.was_absent
        existing.rating = rating
        existing.was_absent = was_absent
        if reason_text is not None:
            existing.reason_text = reason_text
        fb = existing
    else:
        fb = MeetingFeedback(
            meeting_id=meeting_id,
            user_id=user_id,
            rating=rating,
            was_absent=was_absent,
            reason_text=reason_text,
        )
        session.add(fb)
        previously_absent = False

    await session.commit()
    await session.refresh(fb)

    if was_absent and not previously_absent:
        # Поднимаем вес чухана. Идём через User → telegram_id, потому что
        # admin_config хранит веса по tg_id, не по DB-user-id.
        user = await session.get(User, user_id)
        if user is None:
            log.warning("meeting_feedback.user_not_found", user_id=user_id)
            return fb
        delta = await get_meeting_feedback_absence_weight(session)
        new_weight = await add_chukhan_weight(
            session, tg_id=user.telegram_id, delta=delta
        )
        log.info(
            "meeting_feedback.absence_recorded",
            meeting_id=meeting_id,
            user_id=user_id,
            tg_id=user.telegram_id,
            new_weight=new_weight,
            delta=delta,
        )
        # Тост в чат (если включено и есть bot).
        if bot and await get_meeting_feedback_notify_absence(session):
            settings = get_settings()
            if settings.group_chat_id:
                try:
                    await bot.send_message(
                        chat_id=settings.group_chat_id,
                        text=(
                            f"💩 <b>{user.display_name}</b> пропустил встречу — "
                            f"+{delta:g} к весу чухана."
                        ),
                        parse_mode="HTML",
                        disable_notification=True,
                    )
                except TelegramAPIError as exc:
                    log.warning(
                        "meeting_feedback.notify_failed",
                        user_id=user_id,
                        error=str(exc),
                    )
    return fb


async def run_meeting_feedback_job(bot: Bot) -> None:
    """Scheduler-job: запустить feedback-опросы по всем pending-встречам.

    Идемпотентность гарантируется `enumerate_pending_meetings`.
    """
    from app.db.base import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as session:
        if not await get_meeting_feedback_enabled(session):
            log.info("meeting_feedback.disabled")
            return
        pending = await enumerate_pending_meetings(session)
        if not pending:
            log.info("meeting_feedback.no_pending")
            return
        log.info("meeting_feedback.pending_count", count=len(pending))
        for meeting in pending:
            await start_feedback_poll(bot, session, meeting)


def feedback_index_to_payload(option_index: int) -> tuple[int | None, bool]:
    """TG poll option_id → (rating, was_absent). Используется `on_poll_update`.

    Возвращает (None, False) если index вне диапазона — caller проигнорирует.
    """
    if option_index == FEEDBACK_ABSENT_INDEX:
        return (None, True)
    if 0 <= option_index <= 4:
        return (option_index + 1, False)
    return (None, False)


__all__ = (
    "FEEDBACK_OPTIONS",
    "FEEDBACK_ABSENT_INDEX",
    "POLL_KIND_MEETING_FEEDBACK",
    "enumerate_pending_meetings",
    "start_feedback_poll",
    "submit_feedback",
    "run_meeting_feedback_job",
    "feedback_index_to_payload",
)


# Не используется напрямую в этом файле, но импортируется в тестах.
_ = Iterable, Sequence
