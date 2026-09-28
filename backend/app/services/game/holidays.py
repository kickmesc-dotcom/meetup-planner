"""GHG10 (Э10): праздники — пул «дата + сообщение», по умолчанию Новый год.

Задание: «в настройки добавим пул праздников, по умолчанию там только новый год,
но можно добавить свой в формате дата + сообщение». Дата — месяц+день без года
(праздник ежегодный, как ДР), поэтому сравнение идёт по паре (месяц, день).

Идемпотентность двойная и не требует своей таблицы:

* опыт — окно `year` + дискриминатор = id праздника (`xp_grants`), поэтому
  повторный прогон job'а в тот же день ничего не начислит;
* анонс — отправляется, только если хотя бы у кого-то опыт начислился ИМЕННО
  СЕЙЧАС (см. `awards.holiday`, возвращает число начислений).

Дефолтная запись (1 января) приезжает миграцией `0019_game_counters`, поэтому
пустая таблица = фича молча ничего не делает, а не падает.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import structlog
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import GameHoliday, User
from app.services.game import awards

log = structlog.get_logger()


async def holidays_today(
    session: AsyncSession, *, today: date | None = None
) -> list[GameHoliday]:
    """Включённые праздники на дату (по месяцу и дню, без года)."""
    d = today or datetime.now(timezone.utc).date()
    rows = (
        await session.scalars(
            select(GameHoliday).where(
                GameHoliday.enabled.is_(True),
                GameHoliday.month == d.month,
                GameHoliday.day == d.day,
            )
        )
    ).all()
    return list(rows)


def holiday_announcement(holiday: GameHoliday, *, points: int) -> str:
    """Текст анонса. Чистая функция — тестируется без БД."""
    return f"🎊 <b>{holiday.message}</b>\n\n<i>Праздник: +{points} XP каждому.</i>"


async def run_holidays_job(bot: Bot, *, today: date | None = None) -> int:
    """Ежедневный обход: поздравить и начислить. Возвращает число анонсов."""
    settings = get_settings()
    sm = get_sessionmaker()
    announced = 0
    async with sm() as session:
        rows = await holidays_today(session, today=today)
        if not rows:
            return 0
        user_ids = [int(uid) for uid in (await session.scalars(select(User.id))).all()]
        if not user_ids:
            return 0
        for holiday in rows:
            granted = await awards.holiday(session, user_ids, holiday_id=holiday.id)
            if not granted:
                # Уже начисляли (повторный прогон в тот же день) — молчим.
                continue
            announced += 1
            if not settings.group_chat_id:
                continue
            text = holiday_announcement(holiday, points=awards_points())
            try:
                await bot.send_message(
                    chat_id=settings.group_chat_id,
                    text=text,
                    parse_mode="HTML",
                )
            except Exception as exc:  # noqa: BLE001 — праздник не стоит падения job'а
                log.warning("game.holiday_announce_failed", error=str(exc))
    if announced:
        log.info("game.holidays_processed", announced=announced)
    return announced


def awards_points() -> int:
    """Сколько XP даёт праздник — берём из единственной точки тюнинга."""
    from app.services.game.config import points_for

    return points_for("holiday")
