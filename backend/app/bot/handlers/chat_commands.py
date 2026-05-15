"""P4: чат-команды для шестёрки.

Все четыре команды доступны только участникам whitelist (WHITELIST_TG_IDS).
Чужие вызовы игнорируются молча — не хотим, чтобы бот «отзывался» вне группы.

Реролл чухана НЕ выносим в чат (по чеклисту) — остаётся в админке.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def _whitelist_set() -> set[int]:
    return {tg_id for tg_id, _ in get_settings().whitelist_pairs}


def _is_member(tg_id: int | None) -> bool:
    if tg_id is None:
        return False
    return tg_id in _whitelist_set()


# ---------------------- C1: /phrase ----------------------

@router.message(Command("phrase"))
async def on_phrase(message: Message) -> None:
    if not message.from_user or not _is_member(message.from_user.id):
        return
    from app.bot.dispatcher import get_bot
    from app.services.random_phrases import run_random_phrases_job

    try:
        await run_random_phrases_job(get_bot())
    except Exception:
        log.exception("chat.phrase_failed", by=message.from_user.id)
        await message.answer("⚠️ Не получилось сочинить фразу — посмотри логи.")


# ---------------------- C2: /loser ----------------------

@router.message(Command("loser"))
async def on_loser(message: Message) -> None:
    if not message.from_user or not _is_member(message.from_user.id):
        return

    from app.bot.dispatcher import get_bot
    from app.services.loser import CooldownError, roll_loser

    settings = get_settings()
    chat_id = settings.group_chat_id
    bot = get_bot()

    sm = get_sessionmaker()
    async with sm() as session:
        caller = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        if caller is None:
            log.warning("chat.loser_caller_not_in_db", tg_id=message.from_user.id)
            return

        async def _announce(roll, loser):
            text = f"🤡 <b>Лох дня:</b> {loser.display_name}\n<i>{roll.reason_text}</i>"
            target = chat_id if chat_id else message.chat.id
            await bot.send_message(chat_id=target, text=text, parse_mode="HTML")

        try:
            await roll_loser(session, rolled_by=caller, on_announce=_announce)
        except CooldownError as exc:
            mins = int(exc.remaining.total_seconds() // 60)
            await message.answer(f"⏳ Ещё рано — подожди ~{mins} мин.")
        except Exception:
            log.exception("chat.loser_failed", by=message.from_user.id)
            await message.answer("⚠️ Не получилось.")


# ---------------------- C3: /meetings ----------------------

@router.message(Command("meetings"))
async def on_meetings(message: Message) -> None:
    if not message.from_user or not _is_member(message.from_user.id):
        return

    settings = get_settings()
    tz = ZoneInfo(settings.scheduler_tz)
    tz_label = "МСК" if settings.scheduler_tz == "Europe/Moscow" else settings.scheduler_tz
    now = datetime.now(timezone.utc)

    sm = get_sessionmaker()
    async with sm() as session:
        meetings = list((await session.scalars(
            select(Meeting)
            .where(and_(Meeting.starts_at >= now, Meeting.status != "cancelled"))
            .order_by(Meeting.starts_at.asc())
            .limit(5)
        )).all())
        if not meetings:
            await message.answer("📭 Запланированных встреч нет.")
            return

        meeting_ids = [m.id for m in meetings]
        attendance = list((await session.scalars(
            select(MeetingAttendance).where(
                MeetingAttendance.meeting_id.in_(meeting_ids)
            )
        )).all())
        user_ids = {a.user_id for a in attendance}
        users_by_id = {
            u.id: u
            for u in (await session.scalars(
                select(User).where(User.id.in_(user_ids))
            )).all()
        }
        att_by_meeting: dict[int, list[MeetingAttendance]] = {}
        for a in attendance:
            att_by_meeting.setdefault(a.meeting_id, []).append(a)

    lines: list[str] = [f"📅 <b>Ближайшие встречи ({len(meetings)}):</b>"]
    for m in meetings:
        starts_local = m.starts_at.astimezone(tz).strftime("%a %d.%m %H:%M")
        ends_local = m.ends_at.astimezone(tz).strftime("%H:%M")
        lines.append("")
        lines.append(f"<b>{m.title}</b>")
        lines.append(f"  {starts_local}–{ends_local} {tz_label}")
        if m.location:
            lines.append(f"  📍 {m.location}")
        rsvp_line_parts: list[str] = []
        for a in att_by_meeting.get(m.id, []):
            u = users_by_id.get(a.user_id)
            name = u.display_name if u else f"#{a.user_id}"
            rsvp_line_parts.append(f"{RSVP_EMOJI.get(a.rsvp, '❔')} {name}")
        if rsvp_line_parts:
            lines.append("  " + ", ".join(rsvp_line_parts))

    await message.answer("\n".join(lines))


# ---------------------- C4: /tasks ----------------------

# Дублируем словарь меток из routes_admin, чтобы не тащить FastAPI-роутер в импортах.
_JOB_LABELS: dict[str, str] = {
    "chukhan_weekly": "💩 Чухан недели",
    "meeting_reminders_tick": "⏰ Тик напоминаний",
    "avatar_sync_daily": "🖼️ Синхронизация аватарок",
    "random_phrases": "💬 Автопост рандомных фраз",
    "autoloser": "🤡 Автолох",
    "birthdays_daily": "🎂 Дни рождения",
}


@router.message(Command("tasks"))
async def on_tasks(message: Message) -> None:
    if not message.from_user or not _is_member(message.from_user.id):
        return
    from app.bot.scheduler import get_scheduler

    settings = get_settings()
    tz = ZoneInfo(settings.scheduler_tz)
    sched = get_scheduler()
    jobs = list(sched.get_jobs())
    if not jobs:
        await message.answer("🕳️ Запланированных задач нет.")
        return

    rows: list[tuple[datetime | None, str]] = []
    for j in jobs:
        # Скрываем «extra»-fixed-times, чтобы не засорять выдачу
        if j.id.startswith("random_phrases:extra:"):
            continue
        label = _JOB_LABELS.get(j.id, j.id)
        nxt = j.next_run_time
        rows.append((nxt, label))

    rows.sort(key=lambda r: (r[0] is None, r[0] or datetime.max.replace(tzinfo=timezone.utc)))

    lines = ["📋 <b>Запланированные задачи:</b>", ""]
    now = datetime.now(timezone.utc)
    for nxt, label in rows:
        if nxt is None:
            lines.append(f"• {label} — <i>не запланировано</i>")
            continue
        local = nxt.astimezone(tz).strftime("%a %d.%m %H:%M")
        delta = nxt - now
        eta = _humanize_delta(delta)
        lines.append(f"• {label} — {local} <i>({eta})</i>")

    await message.answer("\n".join(lines))


def _humanize_delta(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 0:
        return "скоро"
    if total < 60:
        return f"{total} c"
    if total < 3600:
        return f"{total // 60} мин"
    if total < 86400:
        h = total // 3600
        return f"{h} ч"
    d = total // 86400
    return f"{d} дн"
