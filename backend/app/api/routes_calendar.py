"""GHG6 BD4 — отметки «лох/чухан» на календаре.

Возвращает плоский список `{date, user_id, type}` для окна [from, to).
Фронт по этим отметкам рисует 👑/💩 в ячейке участника на прошедших днях.

- type="loser" — каждая запись `LoserRoll` маппится в свой день (`rolled_at::date`).
  Если в один день было несколько роллов одного и того же юзера — дедуп
  внутри `(date, user_id)`.
- type="chukhan" — каждая `WeeklyChukhan` раскрывается в 7 дней (с понедельника
  по воскресенье). Чухан «висит» на участнике всю неделю.

Источник записи:
- Лох: `services/loser.py::roll_loser` — пишет `LoserRoll(rolled_by, loser_user_id,
  reason_text)` с `rolled_at=server_default(now())`. Используется и admin
  `/admin/loser/roll-now`, и слэш-командой `/loser`, и autoloser-job.
- Чухан: `services/chukhan.py::announce_chukhan` — пишет `WeeklyChukhan(
  week_start, user_id, weights_snapshot)` с `posted_at=now()` после
  успешной TG-публикации. Идемпотентно по `week_start`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.db.models import LoserRoll, Meeting, User, WeeklyChukhan

router = APIRouter(tags=["calendar"])


class CalendarMark(BaseModel):
    date: date
    user_id: int
    type: str  # "loser" | "chukhan"


def build_marks(
    *,
    start_date: date,
    end_date: date,
    loser_rolls: list[tuple[date, int]],
    chukhan_weeks: list[tuple[date, int]],
) -> list[CalendarMark]:
    """Чистая логика для теста: на входе уже распакованные строки
    (`loser_rolls`: [(rolled_at::date, loser_user_id), ...],
     `chukhan_weeks`: [(week_start::date, user_id), ...]), на выходе —
    отсортированный дедуплицированный список marks для окна [start, end).
    """
    out: list[CalendarMark] = []
    seen: set[tuple[date, int, str]] = set()

    for d, uid in loser_rolls:
        if not (start_date <= d < end_date):
            continue
        key = (d, uid, "loser")
        if key in seen:
            continue
        seen.add(key)
        out.append(CalendarMark(date=d, user_id=uid, type="loser"))

    for ws, uid in chukhan_weeks:
        for offset in range(7):
            d = ws + timedelta(days=offset)
            if not (start_date <= d < end_date):
                continue
            key = (d, uid, "chukhan")
            if key in seen:
                continue
            seen.add(key)
            out.append(CalendarMark(date=d, user_id=uid, type="chukhan"))

    out.sort(key=lambda m: (m.date, m.user_id, m.type))
    return out


@router.get("/calendar/marks", response_model=list[CalendarMark])
async def calendar_marks(
    session: SessionDep,
    _: CurrentUser,
    from_: datetime = Query(..., alias="from"),
    to: datetime = Query(...),
) -> list[CalendarMark]:
    """Отметки лох/чухан в окне [from, to)."""
    if to <= from_:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "to must be after from")

    # LoserRoll: фильтр по timestamp, чтобы не натянуть лишний день из-за TZ
    # (`rolled_at` хранится в UTC).
    loser_rows = list(
        (
            await session.scalars(
                select(LoserRoll)
                .where(LoserRoll.rolled_at >= from_)
                .where(LoserRoll.rolled_at < to)
                .order_by(LoserRoll.rolled_at)
            )
        ).all()
    )
    loser_pairs = [(r.rolled_at.date(), r.loser_user_id) for r in loser_rows]

    # WeeklyChukhan: с запасом ±7 дней (неделя может «зацепиться» одним концом).
    chukhan_rows = list(
        (
            await session.scalars(
                select(WeeklyChukhan)
                .where(WeeklyChukhan.week_start >= from_ - timedelta(days=7))
                .where(WeeklyChukhan.week_start < to)
                .order_by(WeeklyChukhan.week_start)
            )
        ).all()
    )
    chukhan_pairs = [(r.week_start.date(), r.user_id) for r in chukhan_rows]

    return build_marks(
        start_date=from_.date(),
        end_date=to.date(),
        loser_rolls=loser_pairs,
        chukhan_weeks=chukhan_pairs,
    )


# --- E8: активный «червь-пидор» ---

class WormCurrentOut(BaseModel):
    """Активный червь-пидор (или поля=None, если никого не назначено).
    Доступно всем участникам (не только админу) — иконка 🪱 нужна в
    `ParticipantRow` у всех клиентов."""
    user_id: int | None = None
    display_name: str | None = None
    started_at: datetime | None = None


@router.get("/worm/current", response_model=WormCurrentOut)
async def get_worm_current(session: SessionDep, _user: CurrentUser) -> WormCurrentOut:
    from app.services.loser import get_current_worm

    row = await get_current_worm(session)
    if row is None:
        return WormCurrentOut()
    target = await session.get(User, row.user_id)
    return WormCurrentOut(
        user_id=row.user_id,
        display_name=target.display_name if target else None,
        started_at=row.started_at,
    )


# --- E6: запланированные игры на календаре ---

class GameSessionOut(BaseModel):
    """Запланированная игра — meeting с tag='game'.

    Фронт рисует иконку 🎮 в углу дня (без привязки к участнику —
    это коллективное событие, не индивидуальная отметка)."""
    meeting_id: int
    title: str
    date: date
    starts_at: datetime


@router.get("/games/scheduled", response_model=list[GameSessionOut])
async def get_scheduled_games(
    session: SessionDep,
    _user: CurrentUser,
    from_: datetime = Query(..., alias="from"),
    to: datetime = Query(...),
) -> list[GameSessionOut]:
    if to <= from_:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "to must be after from")
    rows = list(
        (
            await session.scalars(
                select(Meeting)
                .where(Meeting.tag == "game")
                .where(Meeting.starts_at >= from_)
                .where(Meeting.starts_at < to)
                .where(Meeting.status != "cancelled")
                .order_by(Meeting.starts_at)
            )
        ).all()
    )
    return [
        GameSessionOut(
            meeting_id=m.id,
            title=m.title,
            date=m.starts_at.date(),
            starts_at=m.starts_at,
        )
        for m in rows
    ]
