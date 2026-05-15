from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import structlog
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import and_, select

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import Meeting, MeetingAttendance, User

log = structlog.get_logger()
router = Router()

RSVP_EMOJI = {0: "❔", 1: "✅", 2: "🤔", 3: "🙅"}


@router.message(Command("next"))
async def on_next(message: Message) -> None:
    settings = get_settings()
    tz = ZoneInfo(settings.scheduler_tz)
    now = datetime.now(timezone.utc)

    sm = get_sessionmaker()
    async with sm() as session:
        meeting = await session.scalar(
            select(Meeting)
            .where(
                and_(
                    Meeting.starts_at >= now,
                    Meeting.status != "cancelled",
                )
            )
            .order_by(Meeting.starts_at.asc())
            .limit(1)
        )
        if meeting is None:
            await message.answer("📭 Запланированных встреч нет.")
            return

        attendance = list(
            (
                await session.scalars(
                    select(MeetingAttendance).where(
                        MeetingAttendance.meeting_id == meeting.id
                    )
                )
            ).all()
        )
        users_by_id: dict[int, User] = {
            u.id: u
            for u in (
                await session.scalars(
                    select(User).where(
                        User.id.in_([a.user_id for a in attendance])
                    )
                )
            ).all()
        }

    starts_local = meeting.starts_at.astimezone(tz).strftime("%a %d.%m %H:%M")
    ends_local = meeting.ends_at.astimezone(tz).strftime("%H:%M")
    tz_label = "МСК" if settings.scheduler_tz == "Europe/Moscow" else settings.scheduler_tz

    lines = [f"📅 <b>{meeting.title}</b>", f"{starts_local}–{ends_local} {tz_label}"]
    if meeting.location:
        lines.append(f"📍 {meeting.location}")
    if attendance:
        lines.append("")
        for a in attendance:
            u = users_by_id.get(a.user_id)
            name = u.display_name if u else f"#{a.user_id}"
            lines.append(f"{RSVP_EMOJI.get(a.rsvp, '❔')} {name}")

    await message.answer("\n".join(lines))
