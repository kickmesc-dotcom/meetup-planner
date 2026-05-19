from __future__ import annotations

import random
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.db.models import Birthday, User
from app.services.admin_config import (
    get_birthdays_greeting_templates,
    get_poll_time_presets,
)

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


class GreetingOut(BaseModel):
    text: str
    template_index: int  # для теста/дебага — какой именно шаблон зашёл


def _age_phrase(age: int | None) -> tuple[str, str, str]:
    """Возвращает (age_text, age_phrase, age_or_year) для подстановки в шаблон.

    - age=None (year_known=False) → возраст не показываем,
      `age_phrase` пустеет, `age_or_year` = "новый год жизни".
    - age=20 → "20 лет"; склонение по RU-правилам.
    """
    if age is None:
        return "", "", "новый год жизни"
    last_two = age % 100
    last = age % 10
    if 11 <= last_two <= 14:
        word = "лет"
    elif last == 1:
        word = "год"
    elif 2 <= last <= 4:
        word = "года"
    else:
        word = "лет"
    age_text = f"{age} {word}"
    return age_text, age_text, age_text


def render_greeting(template: str, *, name: str, age: int | None) -> str:
    """Безопасный рендер: только наши плейсхолдеры, без `str.format` целиком
    (на случай, если в шаблоне юзера окажется случайная `{...}` от себя).
    """
    age_text, age_phrase, age_or_year = _age_phrase(age)
    out = template
    out = out.replace("{name}", name)
    out = out.replace("{age_phrase}", age_phrase)
    out = out.replace("{age_or_year}", age_or_year)
    out = out.replace("{age}", age_text)
    return out


@router.post(
    "/birthdays/{user_id}/greeting",
    response_model=GreetingOut,
)
async def birthday_greeting(
    session: SessionDep,
    _: CurrentUser,
    user_id: int,
    target_date: date = Query(..., alias="date"),
) -> GreetingOut:
    """Собрать случайный шаблон поздравления для именинника `user_id` на
    конкретную дату `target_date`. LLM не зовём — берём из
    `admin_config["birthdays.greeting_templates"]` (или дефолта).

    Возраст считаем как `target_date.year - bday.year`, минус 1 если ДР
    в этом году ещё не наступил. Если `year_known=False` — возраст не
    подставляем.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    bday = await session.get(Birthday, user_id)
    if bday is None or bday.bday is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "birthday_not_set")

    age: int | None = None
    if bday.year_known:
        age = target_date.year - bday.bday.year
        # До ДР в этом году — возраст ещё прошлогодний.
        if (target_date.month, target_date.day) < (bday.bday.month, bday.bday.day):
            age -= 1
        if age < 0:
            age = 0

    templates = await get_birthdays_greeting_templates(session)
    if not templates:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no_templates")
    idx = random.randrange(len(templates))
    text = render_greeting(templates[idx], name=user.display_name, age=age)
    return GreetingOut(text=text, template_index=idx)
