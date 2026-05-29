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

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, SessionDep
from app.db.models import LoserOutbox, LoserRoll, Meeting, User, WeeklyChukhan

router = APIRouter(tags=["calendar"])


class CalendarMark(BaseModel):
    date: date
    user_id: int
    type: str  # "loser" | "chukhan"
    # GHG6 H2: source='auto' | 'manual' для loser-марок. Фронт рисует две
    # короны рядом, если за день есть оба источника у одного юзера; для
    # 'chukhan' поле всегда None.
    source: str | None = None


def build_marks(
    *,
    start_date: date,
    end_date: date,
    loser_rolls: list[tuple[date, int, str]],
    chukhan_weeks: list[tuple[date, int]],
) -> list[CalendarMark]:
    """Чистая логика для теста: на входе уже распакованные строки
    (`loser_rolls`: [(rolled_at::date, loser_user_id, source), ...],
     `chukhan_weeks`: [(week_start::date, user_id), ...]), на выходе —
    отсортированный дедуплицированный список marks для окна [start, end).

    GHG6 H2: дедуп loser-меток по `(date, user_id, source)` — за один день
    у одного юзера может быть две короны (auto и manual), и обе попадают
    в выдачу. Старый дедуп по `(date, user_id, type)` не различал источники.
    """
    out: list[CalendarMark] = []
    seen_loser: set[tuple[date, int, str]] = set()
    seen_chukhan: set[tuple[date, int]] = set()

    for d, uid, src in loser_rolls:
        if not (start_date <= d < end_date):
            continue
        key = (d, uid, src)
        if key in seen_loser:
            continue
        seen_loser.add(key)
        out.append(CalendarMark(date=d, user_id=uid, type="loser", source=src))

    for ws, uid in chukhan_weeks:
        for offset in range(7):
            d = ws + timedelta(days=offset)
            if not (start_date <= d < end_date):
                continue
            key = (d, uid)
            if key in seen_chukhan:
                continue
            seen_chukhan.add(key)
            out.append(CalendarMark(date=d, user_id=uid, type="chukhan"))

    out.sort(key=lambda m: (m.date, m.user_id, m.type, m.source or ""))
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
    #
    # GHG7 P0.2.b.5: для source='auto' дополнительный фильтр через LEFT JOIN
    # с loser_outbox — корону показываем только если запись доставлена
    # (`outbox.status='sent'`), либо если outbox-записи нет (legacy роллы до
    # миграции 0014). source='manual' (UI/chat/admin force-reroll) outbox
    # не пишут — для них фильтр прозрачно пропускает по `LoserOutbox.id IS NULL`.
    loser_rows = list(
        (
            await session.execute(
                select(LoserRoll)
                .outerjoin(LoserOutbox, LoserOutbox.loser_roll_id == LoserRoll.id)
                .where(LoserRoll.rolled_at >= from_)
                .where(LoserRoll.rolled_at < to)
                .where(
                    or_(
                        LoserOutbox.id.is_(None),
                        LoserOutbox.status == "sent",
                    )
                )
                .order_by(LoserRoll.rolled_at)
            )
        )
        .scalars()
        .all()
    )
    loser_pairs = [
        (r.rolled_at.date(), r.loser_user_id, r.source or "manual") for r in loser_rows
    ]

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


# --- GHG7 P0.2.e: причина ролла по клику на корону ---


class LoserReasonOut(BaseModel):
    """Детали loser-ролла за конкретный (date, user_id).

    Если за один день у юзера несколько роллов — берём САМЫЙ ПОЗДНИЙ
    (rolled_at DESC), как и видит юзер «последнюю корону». Worm-роллы
    (reason_text=WORM_REASON_TEXT) маркируются полем `was_worm=true`,
    фронт может показать другую стилизацию попапа.
    """
    rolled_at: datetime
    reason_text: str | None = None
    source: str | None = None  # 'auto' | 'manual' | None для legacy
    rolled_by_name: str | None = None  # display_name инициатора
    was_worm: bool = False


@router.get(
    "/calendar/loser/{day}/{user_id}",
    response_model=LoserReasonOut,
)
async def get_loser_reason(
    day: date,
    user_id: int,
    session: SessionDep,
    _user: CurrentUser,
) -> LoserReasonOut:
    """Вернуть последний loser-ролл за день для юзера. 404 если ничего нет.

    Фильтрация по outbox — НЕ применяется: попап открывается по клику на
    уже-видимую корону, значит соответствующий ролл либо доставлен, либо
    legacy/manual. Если корону всё-таки рисует фронт без записи на бэке
    (например клиент догнал кэш), отдаём 404 — попап не открыть.
    """
    from app.services.loser import WORM_REASON_TEXT

    # rolled_at в UTC, day — локальная дата клиента. Берём окно [day, day+1)
    # в UTC — для шестёрки одного TZ-пояса этого достаточно. Если когда-нибудь
    # появятся юзеры в разных TZ, нужно будет передавать tz клиента.
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    row = await session.scalar(
        select(LoserRoll)
        .where(LoserRoll.loser_user_id == user_id)
        .where(LoserRoll.rolled_at >= start)
        .where(LoserRoll.rolled_at < end)
        .order_by(LoserRoll.rolled_at.desc())
        .limit(1)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no roll for this day/user")

    roller = await session.get(User, row.rolled_by)
    return LoserReasonOut(
        rolled_at=row.rolled_at,
        reason_text=row.reason_text,
        source=row.source,
        rolled_by_name=roller.display_name if roller else None,
        was_worm=(row.reason_text == WORM_REASON_TEXT),
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
