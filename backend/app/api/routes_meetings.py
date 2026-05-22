from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta

import structlog
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.config import get_settings
from app.db.models import LoserRoll, Meeting, MeetingAttendance, User
from app.schemas.meetings import (
    AutoPickRequest,
    AutoPickResponse,
    AutoPickSlotOut,
    LoserRollOut,
    LoserRollResponse,
    LoserStatsOut,
    MeetingAttendeeOut,
    MeetingCreateRequest,
    MeetingDetail,
    MeetingOut,
    RsvpRequest,
    fmt_remaining,
)
from app.services.auto_pick import find_best_slots
from app.services.ical import make_token, render_calendar, verify_token
from app.services.loser import (
    CooldownError,
    delete_last_loser,
    compose_loser_message,
    last_loser,
    loser_stats,
    roll_loser,
    time_until_next_roll,
)
from app.services.reminders import (
    cancel_meeting_reminders,
    schedule_meeting_reminders,
)

log = structlog.get_logger()
router = APIRouter(tags=["meetings"])


async def _build_detail(
    session: AsyncSession, meeting: Meeting, *, me_id: int
) -> MeetingDetail:
    rows = list(
        (
            await session.scalars(
                select(MeetingAttendance).where(
                    MeetingAttendance.meeting_id == meeting.id
                )
            )
        ).all()
    )
    my_rsvp = 0
    attendees: list[MeetingAttendeeOut] = []
    for r in rows:
        attendees.append(MeetingAttendeeOut(user_id=r.user_id, rsvp=r.rsvp))
        if r.user_id == me_id:
            my_rsvp = r.rsvp
    return MeetingDetail(
        id=meeting.id,
        created_by=meeting.created_by,
        title=meeting.title,
        starts_at=meeting.starts_at,
        ends_at=meeting.ends_at,
        location=meeting.location,
        status=meeting.status,
        auto_picked=meeting.auto_picked,
        score=float(meeting.score) if meeting.score is not None else None,
        attendees=attendees,
        my_rsvp=my_rsvp,
    )


@router.get("/meetings", response_model=list[MeetingDetail])
async def list_meetings(
    session: SessionDep,
    user: CurrentUser,
    from_: datetime = Query(..., alias="from"),
    to: datetime = Query(...),
) -> list[MeetingDetail]:
    stmt = (
        select(Meeting)
        .where(and_(Meeting.starts_at < to, Meeting.ends_at > from_))
        .order_by(Meeting.starts_at)
    )
    result = await session.scalars(stmt)
    return [await _build_detail(session, m, me_id=user.id) for m in result.all()]


@router.patch("/meetings/{meeting_id}/rsvp", response_model=MeetingDetail)
async def set_rsvp(
    meeting_id: int,
    body: RsvpRequest,
    session: SessionDep,
    user: CurrentUser,
) -> MeetingDetail:
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    row = await session.get(MeetingAttendance, (meeting_id, user.id))
    if row is None:
        session.add(
            MeetingAttendance(
                meeting_id=meeting_id, user_id=user.id, rsvp=body.rsvp
            )
        )
    else:
        row.rsvp = body.rsvp
    await session.commit()
    return await _build_detail(session, meeting, me_id=user.id)


@router.post("/meetings", response_model=MeetingOut, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    body: MeetingCreateRequest,
    session: SessionDep,
    user: CurrentUser,
) -> Meeting:
    if body.ends_at <= body.starts_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad_window")
    meeting = Meeting(
        created_by=user.id,
        title=body.title,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        location=body.location,
        auto_picked=body.auto_picked,
        score=body.score,
        status="proposed",
    )
    session.add(meeting)
    await session.commit()
    await session.refresh(meeting)
    await schedule_meeting_reminders(session, meeting)
    return meeting


@router.delete("/meetings/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_meeting(
    meeting_id: int,
    session: SessionDep,
    _: CurrentUser,
) -> Response:
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    
    meeting.status = "cancelled"
    await session.commit()
    await cancel_meeting_reminders(session, meeting_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/meetings/auto-pick", response_model=AutoPickResponse)
async def auto_pick(
    body: AutoPickRequest,
    session: SessionDep,
    _: CurrentUser,
) -> AutoPickResponse:
    if body.window_end <= body.window_start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad_window")
    from app.services.admin_config import get_poll_time_presets

    presets = await get_poll_time_presets(session) if body.use_presets else None
    slots = await find_best_slots(
        session,
        window_start=body.window_start,
        window_end=body.window_end,
        duration=timedelta(minutes=body.duration_minutes),
        step=timedelta(minutes=body.step_minutes),
        top_n=body.top_n,
        presets=presets,
    )
    return AutoPickResponse(
        slots=[
            AutoPickSlotOut(
                starts_at=s.starts_at,
                ends_at=s.ends_at,
                score=s.score,
                available_user_ids=s.available_user_ids,
                maybe_user_ids=s.maybe_user_ids,
            )
            for s in slots
        ]
    )


@router.get("/meetings/ical/url")
async def get_ical_url(user: CurrentUser) -> dict[str, str]:
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    if not base:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "public_base_url_not_set"
        )
    token = make_token(user.id)
    https_url = f"{base}/api/meetings/ical/{user.id}.ics?t={token}"
    webcal_url = https_url.replace("https://", "webcal://", 1).replace(
        "http://", "webcal://", 1
    )
    return {"https": https_url, "webcal": webcal_url}


@router.get("/meetings/ical/{user_id}.ics")
async def ical_feed(
    user_id: int,
    session: SessionDep,
    t: str = Query(...),
) -> Response:
    if not verify_token(user_id, t):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bad_token")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    rows = list(
        (
            await session.scalars(
                select(Meeting)
                .where(Meeting.status != "cancelled")
                .order_by(Meeting.starts_at.asc())
            )
        ).all()
    )
    body = render_calendar(rows, calendar_name=f"Встречи {user.display_name}")
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="meetings.ics"',
            "Cache-Control": "public, max-age=900",
        },
    )


# GHG6 E3 (2026-05-21): унификация с админским force-reroll.
# Раньше публичный /loser/roll делал atomic send+commit с таймаутом 15с — при
# сбоях прокси аиограм висел и пользователь получал 504/502 «telegram_error»,
# а ролл откатывался. Админский /admin/loser/roll-now всегда срабатывал, потому
# что _announce там глотает ошибки и roll_loser коммитит. Приводим к тому же
# поведению: запись сохраняется всегда, send в чат — best-effort. На фронте
# UX-крутилка живёт независимо (LoserSheet.tsx — локальный setInterval).
_LOSER_SEND_TIMEOUT = 8.0  # короче 15с — фронт всё равно крутит ≥1.1с, а 15с никто не ждёт.


@router.post("/loser/roll", response_model=LoserRollResponse)
async def loser_roll_endpoint(
    session: SessionDep,
    user: CurrentUser,
) -> LoserRollResponse:
    settings = get_settings()
    target_chat = settings.group_chat_id
    sent_flag = {"ok": False}
    timings: dict[str, float] = {}
    t0 = time.monotonic()

    async def _announce(row: LoserRoll, loser: User, extras=None) -> None:
        """Best-effort публикация в группу. Любое исключение глотается —
        запись ролла всё равно коммитится. Принцип: «лучше зафиксированный
        ролл без объявления, чем зависший HTTP-запрос с 504»."""
        if not target_chat:
            return  # No chat configured — silent success, row still saved.
        from app.bot.dispatcher import get_bot

        try:
            # Count BEFORE commit: existing rolls only. +1 for this one.
            counts = await loser_stats(session)
            cnt = counts.get(row.loser_user_id, 0) + 1
            text = compose_loser_message(
                roller_name=user.display_name,
                loser_name=loser.display_name,
                reason_text=row.reason_text or "",
                loser_count=cnt,
                extras=extras,
                header_emoji="🎲",
                header_label="Лох дня",
            )
            send_started = time.monotonic()
            await asyncio.wait_for(
                get_bot().send_message(
                    chat_id=target_chat,
                    text=text,
                    parse_mode="HTML",
                ),
                timeout=_LOSER_SEND_TIMEOUT,
            )
            timings["send_ms"] = round((time.monotonic() - send_started) * 1000, 1)
            sent_flag["ok"] = True
        except TelegramRetryAfter as exc:
            log.warning("loser.tg_retry_after", retry=exc.retry_after, **timings)
        except TelegramForbiddenError as exc:
            log.warning("loser.tg_forbidden", error=str(exc), **timings)
        except (TelegramNetworkError, asyncio.TimeoutError) as exc:
            log.warning(
                "loser.tg_network_failed",
                error=str(exc),
                total_ms=round((time.monotonic() - t0) * 1000, 1),
                **timings,
            )
        except TelegramAPIError as exc:
            log.warning("loser.tg_api_error", error=str(exc), **timings)
        except Exception as exc:  # noqa: BLE001
            log.warning("loser.announce_unexpected", error=str(exc), **timings)

    try:
        row = await roll_loser(session, rolled_by=user, on_announce=_announce)
    except CooldownError as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"cooldown:{int(exc.remaining.total_seconds())}",
        ) from exc
    except Exception as exc:  # noqa: BLE001 — row уже откачен внутри roll_loser, нам сюда дойти не должно (announce не raise'ит). Если дошло — это уже не TG, а БД.
        log.exception("loser.roll_failed", error=str(exc), **timings)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="loser_roll_failed",
        ) from exc

    log.info(
        "loser.rolled_ok",
        loser_id=row.loser_user_id,
        rolled_by=user.id,
        sent_to_chat=sent_flag["ok"],
        total_ms=round((time.monotonic() - t0) * 1000, 1),
        **timings,
    )

    return LoserRollResponse(
        roll=LoserRollOut.model_validate(row),
        sent_to_chat=sent_flag["ok"],
    )


@router.delete("/loser/last", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def loser_delete_last(
    session: SessionDep,
    user: CurrentUser,
) -> Response:
    """Manual cleanup: drop the most recent loser roll so it can be re-rolled
    without touching SQL by hand. Admins only."""
    admin_ids = get_settings().admin_tg_id_set
    if user.telegram_id not in admin_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not_admin")
    deleted = await delete_last_loser(session)
    if deleted is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no_loser_to_delete")
    log.info("loser.last_deleted", roll_id=deleted.id, by=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/loser/stats", response_model=LoserStatsOut)
async def loser_stats_endpoint(
    session: SessionDep,
    _: CurrentUser,
) -> LoserStatsOut:
    counts = await loser_stats(session)
    last_row = await last_loser(session)
    remaining = await time_until_next_roll(session)
    return LoserStatsOut(
        counts=counts,
        last=LoserRollOut.model_validate(last_row) if last_row else None,
        cooldown_remaining_seconds=int(remaining.total_seconds()),
    )


@router.get("/loser/history", response_model=list[LoserRollOut])
async def loser_history(
    session: SessionDep,
    _: CurrentUser,
    limit: int = Query(20, ge=1, le=100),
) -> list[LoserRoll]:
    rows = await session.scalars(
        select(LoserRoll).order_by(LoserRoll.rolled_at.desc()).limit(limit)
    )
    return list(rows.all())