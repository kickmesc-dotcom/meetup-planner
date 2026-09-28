"""GHG10 Э6: недельный итог активности — «Рупор поколения» и «Read only».

Задание: «рупор поколения — стать самым активным участником чата за неделю
(набрать больше всех отправленных сообщений)», «Read only — стать самым
НЕактивным». Подсчёт идёт по durable-счётчику `chat_activity_daily` (его
наполняет `awards.message` вместе с опытом одним commit'ом).

Как и `holidays.py`, этот модуль — только обвязка job'а: чистое решение «кто
самый/самый неактивный» принимает `achievements.pick_week_extremes`, а выдачу
ачивок и анонс в чат — `awards.week_activity`. Здесь — окно недели, один
агрегатный SELECT и идемпотентность по ISO-неделе.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import structlog
from aiogram import Bot

from app.db.base import get_sessionmaker
from app.services.game import achievements, awards
from app.services.game.flags import is_game_enabled

log = structlog.get_logger()


def week_bounds(at: datetime | None = None) -> tuple[date, date]:
    """Понедельник..воскресенье ПРЕДЫДУЩЕЙ ISO-недели (UTC).

    Job запускается в начале новой недели и подводит итог только что
    закончившейся — так в подведении итога участвуют все 7 дней целиком.
    """
    moment = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    monday_this = moment.date() - timedelta(days=moment.weekday())
    monday_prev = monday_this - timedelta(days=7)
    return monday_prev, monday_prev + timedelta(days=6)


def iso_week_key(day: date) -> str:
    """Ключ ISO-недели — тот же формат, что у окон `xp.window_key` (`2026-W39`)."""
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


async def run_week_activity_job(
    bot: Bot | None = None, *, now: datetime | None = None
) -> tuple[int | None, int | None]:
    """Подвести итог недели и выдать звания. Возвращает (самый, самый неактивный).

    `bot` принимается для единства с другими job'ами (`run_holidays_job`), но не
    используется: анонс ачивок сам достаёт бота из диспетчера.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        if not await is_game_enabled(session):
            return (None, None)
        start, end = week_bounds(now)
        counts = await achievements.week_activity_counts(session, start, end)
        most, least = achievements.pick_week_extremes(counts)
        if most is None and least is None:
            log.info("game.week_activity_skipped", week=iso_week_key(start))
            return (None, None)
        await awards.week_activity(
            session,
            most_active_id=most,
            least_active_id=least,
            week_key=iso_week_key(start),
        )
    log.info(
        "game.week_activity_processed",
        week=iso_week_key(start),
        most_active_id=most,
        least_active_id=least,
    )
    return most, least
