"""BD3: ежедневный birthday-обход.

Раз в сутки (~09:07) для каждой записи `birthdays`:
  * вычисляем days_until до ближайшего ДР с учётом 29 февраля (для невисокосных лет — 28.02);
  * если матчится один из интервалов (30 / 7 / 1 / 0 / 7-hint) и соответствующий
    флаг включён — шлём сообщение в group_chat;
  * пишем запись в `birthday_notifications` (UNIQUE по user_id+year+kind),
    чтобы повторный заход в тот же день/год не отправил дубль.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterable

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import Birthday, BirthdayNotification, User
from app.services.random_phrases import compose_random_phrase

log = structlog.get_logger()


# kind → days_until (порядок важен: первый совпавший выбирается)
_INTERVALS: list[tuple[str, int]] = [
    ("on_day", 0),
    ("day", 1),
    ("week", 7),
    ("hint_week", 7),  # same day as `week` — но другой kind в журнале
    ("month", 30),
]


def _enabled_flag(b: Birthday, kind: str) -> bool:
    return {
        "on_day": b.remind_on_day,
        "day": b.remind_day,
        "week": b.remind_week,
        "hint_week": b.remind_hint_week,
        "month": b.remind_month,
    }[kind]


def _next_occurrence(bday: date, today: date) -> date:
    """Ближайшая дата (≥ today), когда наступит ДР.
    Висок 29.02 → если в текущем году нет — берём 28.02 этого года или 29.02 следующего."""
    month, day = bday.month, bday.day
    year = today.year

    def _safe(y: int) -> date:
        try:
            return date(y, month, day)
        except ValueError:
            # 29 февраля в невисокосный год → отмечаем 28.02
            return date(y, 2, 28)

    this_year = _safe(year)
    if this_year >= today:
        return this_year
    return _safe(year + 1)


async def _send_for(
    session,
    bot: Bot,
    chat_id: int,
    user: User,
    b: Birthday,
    kind: str,
    today: date,
) -> None:
    """Отправить одно напоминание и записать в журнал.
    UNIQUE(user_id, year, kind) гарантирует, что повторный вызов в тот же
    календарный год не отошлёт дубль."""
    notif = BirthdayNotification(user_id=b.user_id, year=today.year, kind=kind)
    session.add(notif)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        log.info("birthdays.already_sent", user_id=b.user_id, kind=kind, year=today.year)
        return

    text = await _render(session, user, b, kind, today)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        await session.commit()
        log.info("birthdays.sent", user_id=b.user_id, kind=kind)
    except TelegramAPIError:
        await session.rollback()
        log.exception("birthdays.send_failed", user_id=b.user_id, kind=kind)


async def _render(
    session, user: User, b: Birthday, kind: str, today: date
) -> str:
    name = user.display_name
    age_part = ""
    if b.year_known and b.bday is not None:
        # возраст, который человеку исполнится в ближайшее ДР
        upcoming = _next_occurrence(b.bday, today)
        age = upcoming.year - b.bday.year
        age_part = f" ({age})"

    if kind == "month":
        return f"📅 Через месяц — день рождения у <b>{name}</b>{age_part}. Самое время начать думать над подарком."
    if kind == "week":
        return f"🗓️ Через неделю ДР у <b>{name}</b>{age_part}. Не забудьте."
    if kind == "hint_week":
        return (
            f"💡 За неделю до ДР <b>{name}</b>{age_part}. "
            f"Кто хочет — задайте встречу в Mini App, чтобы отметить."
        )
    if kind == "day":
        return f"📌 Завтра ДР у <b>{name}</b>{age_part}. Последняя возможность дописать в групповуху."
    # on_day → креативное поздравление через генератор фраз
    phrase = await compose_random_phrase(session, n=3, lookback_days=30, collective_chance=0.0)
    quote = ""
    if phrase:
        quote = f"\n\n{phrase}"
    return f"🎉🎂 Сегодня день рождения у <b>{name}</b>{age_part}! Поздравляем!{quote}"


def _days_diff(today: date, occ: date) -> int:
    return (occ - today).days


async def run_birthdays_job(bot: Bot) -> None:
    """Запускается раз в сутки. Идемпотентно — журнал отбрасывает повторы."""
    settings = get_settings()
    chat_id = settings.group_chat_id
    if not chat_id:
        log.warning("birthdays.no_group_chat_id")
        return

    today = datetime.now(timezone.utc).date()
    sm = get_sessionmaker()
    async with sm() as session:
        rows = (await session.scalars(select(Birthday))).all()
        if not rows:
            log.info("birthdays.empty")
            return
        users_by_id = {
            u.id: u
            for u in (await session.scalars(
                select(User).where(User.id.in_([b.user_id for b in rows]))
            )).all()
        }
        for b in rows:
            if b.bday is None:
                continue
            user = users_by_id.get(b.user_id)
            if user is None:
                continue
            occ = _next_occurrence(b.bday, today)
            diff = _days_diff(today, occ)
            for kind, target in _INTERVALS:
                if diff != target:
                    continue
                if not _enabled_flag(b, kind):
                    continue
                await _send_for(session, bot, chat_id, user, b, kind, today)
