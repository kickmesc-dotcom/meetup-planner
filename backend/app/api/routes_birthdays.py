from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.db.models import Birthday, User
from app.services.admin_config import get_poll_time_presets

router = APIRouter(tags=["birthdays"])


class PollPresetPublicItem(BaseModel):
    start: str
    end: str
    label: str | None = None


@router.get("/poll-presets", response_model=list[PollPresetPublicItem])
async def public_poll_presets(
    session: SessionDep,
    _: CurrentUser,
) -> list[PollPresetPublicItem]:
    """Текущие пресеты времени для UI опросов/авто-подбора.
    Whitelist-only (через `CurrentUser`); не admin-only — нужен фронту, чтобы
    показать дефолтный выбор при создании опроса."""
    presets = await get_poll_time_presets(session)
    return [PollPresetPublicItem(**p) for p in presets]


class BirthdayCalendarOut(BaseModel):
    """Конкретная дата ДР внутри запрошенного окна."""

    user_id: int
    display_name: str
    date: date  # реальная дата в окне (29.02 в невисокосный год -> 28.02)
    bday: date  # исходная дата из БД
    year_known: bool


def _safe_in_year(month: int, day: int, year: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        # 29.02 в невисокосный год -> 28.02
        return date(year, 2, 28)


@router.get("/birthdays/calendar", response_model=list[BirthdayCalendarOut])
async def birthdays_calendar(
    session: SessionDep,
    _: CurrentUser,
    from_: datetime = Query(..., alias="from"),
    to: datetime = Query(...),
) -> list[BirthdayCalendarOut]:
    """Возвращает др-шки, которые попадают в окно [from, to).

    Используется фронтовым календарём, чтобы рисовать 🎂 в ячейках дня
    сразу после ввода даты в админке — без ожидания cron-уведомлений.
    """
    if to <= from_:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "to must be after from")

    rows = (
        await session.execute(
            select(Birthday, User)
            .join(User, User.id == Birthday.user_id)
            .where(Birthday.bday.is_not(None))
        )
    ).all()

    start_date = from_.date()
    end_date = to.date()  # exclusive

    out: list[BirthdayCalendarOut] = []
    for b, u in rows:
        if b.bday is None:
            continue
        # Окно может пересекать несколько лет → проверяем каждый год от start до end.
        for year in range(start_date.year, end_date.year + 1):
            d = _safe_in_year(b.bday.month, b.bday.day, year)
            if start_date <= d < end_date:
                out.append(
                    BirthdayCalendarOut(
                        user_id=u.id,
                        display_name=u.display_name,
                        date=d,
                        bday=b.bday,
                        year_known=b.year_known,
                    )
                )
    out.sort(key=lambda x: (x.date, x.user_id))
    return out
