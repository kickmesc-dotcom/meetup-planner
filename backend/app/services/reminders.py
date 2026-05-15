"""Напоминания о встречах: за 24ч / 12ч / 3ч до старта.

При создании встречи в БД пишутся три строки `meeting_reminders`. APScheduler
раз в минуту опрашивает таблицу и шлёт сообщения, выставляя `sent_at`.
Перезапуск процесса не теряет задачи — состояние в БД."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import Meeting, MeetingReminder

log = structlog.get_logger()

REMINDER_OFFSETS_MIN = (24 * 60, 12 * 60, 3 * 60)


async def schedule_meeting_reminders(
    session: AsyncSession,
    meeting: Meeting,
) -> None:
    """Создаёт три записи `meeting_reminders` для встречи. Идемпотентно
    благодаря UNIQUE(meeting_id, offset_minutes)."""
    now = datetime.now(timezone.utc)
    for off in REMINDER_OFFSETS_MIN:
        due = meeting.starts_at - timedelta(minutes=off)
        if due <= now:
            continue
        existing = await session.scalar(
            select(MeetingReminder).where(
                MeetingReminder.meeting_id == meeting.id,
                MeetingReminder.offset_minutes == off,
            )
        )
        if existing:
            existing.due_at = due
            existing.sent_at = None
        else:
            session.add(
                MeetingReminder(
                    meeting_id=meeting.id,
                    offset_minutes=off,
                    due_at=due,
                )
            )
    await session.commit()


async def cancel_meeting_reminders(session: AsyncSession, meeting_id: int) -> None:
    rows = list(
        (
            await session.scalars(
                select(MeetingReminder).where(MeetingReminder.meeting_id == meeting_id)
            )
        ).all()
    )
    for r in rows:
        await session.delete(r)
    await session.commit()


def _format_reminder(meeting: Meeting, offset_minutes: int) -> str:
    if offset_minutes >= 24 * 60:
        when = "через 24 часа"
    elif offset_minutes >= 12 * 60:
        when = "через 12 часов"
    else:
        when = "через 3 часа"

    tz_name = get_settings().scheduler_tz
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
        tz_name = "UTC"
    starts_local = meeting.starts_at.astimezone(tz)
    tz_label = "МСК" if tz_name == "Europe/Moscow" else tz_name
    head = f"⏰ <b>Напоминание</b> — встреча {when}"
    body = (
        f"\n📌 <b>{meeting.title}</b>\n"
        f"🕒 {starts_local:%d.%m в %H:%M} {tz_label}"
    )
    if meeting.location:
        body += f"\n📍 {meeting.location}"
    return head + body


async def _send_reminder(
    bot: Bot, session: AsyncSession, reminder: MeetingReminder
) -> None:
    settings = get_settings()
    if not settings.group_chat_id:
        return
    meeting = await session.get(Meeting, reminder.meeting_id)
    if meeting is None or meeting.status == "cancelled":
        await session.delete(reminder)
        await session.commit()
        return

    text = _format_reminder(meeting, reminder.offset_minutes)
    try:
        await bot.send_message(chat_id=settings.group_chat_id, text=text)
        reminder.sent_at = datetime.now(timezone.utc)
        await session.commit()
        log.info(
            "reminder.sent",
            meeting_id=reminder.meeting_id,
            offset=reminder.offset_minutes,
        )
    except TelegramAPIError as exc:
        log.warning("reminder.send_failed", error=str(exc))


async def run_due_reminders(bot: Bot) -> None:
    """APScheduler-job: вытащить все due, ещё не отправленные, и разослать."""
    now = datetime.now(timezone.utc)
    sm = get_sessionmaker()
    async with sm() as session:
        rows = list(
            (
                await session.scalars(
                    select(MeetingReminder)
                    .where(
                        MeetingReminder.sent_at.is_(None),
                        MeetingReminder.due_at <= now,
                    )
                    .order_by(MeetingReminder.due_at)
                    .limit(50)
                )
            ).all()
        )
        for r in rows:
            await _send_reminder(bot, session, r)


