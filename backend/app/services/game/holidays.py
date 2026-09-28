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

# Сколько символов в поздравлении. Длинное сообщение не влезает в анонс чата и
# ломает ритм праздника, поэтому режем, а не отклоняем.
MAX_HOLIDAY_MESSAGE = 200

# Длины месяцев: 29 февраля принимаем (праздник ежегодный, в високосный год он
# существует - запрещать его из-за трёх невисокосных лет подряд глупо).
_DAYS_IN_MONTH = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


class HolidayError(ValueError):
    """Некорректный праздник. `code` уезжает в API как `detail` (Э10.3).

    Коды, а не текст: фронт переводит их сам (`humanizeApiError`), а бот —
    в `denial_message`. Так одна ошибка обслуживает обе поверхности.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def normalize_message(raw: str | None) -> str:
    """Текст поздравления: края срезаем, пустое - ошибка.

    Праздник без сообщения бессмыслен: анонс в чат состоит из него.
    """
    text = (raw or "").strip()
    if not text:
        raise HolidayError("holiday_message_empty")
    return text[:MAX_HOLIDAY_MESSAGE]


def validate_month_day(month: int, day: int) -> None:
    """Месяц 1-12 и день в пределах месяца. Чистая - тестируется без БД."""
    if not 1 <= month <= 12:
        raise HolidayError("holiday_month_invalid")
    if not 1 <= day <= _DAYS_IN_MONTH[month - 1]:
        raise HolidayError("holiday_day_invalid")


async def list_holidays(
    session: AsyncSession, *, only_enabled: bool = False
) -> list[GameHoliday]:
    """Все праздники в календарном порядке (Э10.3 - для админской поверхности)."""
    stmt = select(GameHoliday).order_by(GameHoliday.month, GameHoliday.day)
    if only_enabled:
        stmt = stmt.where(GameHoliday.enabled.is_(True))
    return list((await session.scalars(stmt)).all())


async def add_holiday(
    session: AsyncSession,
    *,
    month: int,
    day: int,
    message: str | None,
    created_by_user_id: int | None = None,
) -> GameHoliday:
    """Добавить праздник. Дубликат даты - `HolidayError('holiday_date_taken')`.

    Одна дата = один праздник (unique в БД): иначе в день начислилось бы дважды,
    а анонс стал бы неоднозначным (что именно празднуем?).
    """
    validate_month_day(month, day)
    text = normalize_message(message)
    existing = await session.scalar(
        select(GameHoliday).where(
            GameHoliday.month == month, GameHoliday.day == day
        )
    )
    if existing is not None:
        raise HolidayError("holiday_date_taken")
    row = GameHoliday(
        month=month,
        day=day,
        message=text,
        enabled=True,
        created_by_user_id=created_by_user_id,
    )
    session.add(row)
    await session.commit()
    return row


async def remove_holiday(session: AsyncSession, *, holiday_id: int) -> bool:
    """Удалить праздник. False - такого нет (роут отдаст 404)."""
    row = await session.get(GameHoliday, holiday_id)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


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
