from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
# УДАЛЕН импорт get_bot сверху для предотвращения Circular Import
from app.config import get_settings
from app.db.models import Poll, PollOption, PollVote
from app.schemas.meetings import (
    PollAutoPickRequest,
    PollCreateRequest,
    PollOptionOut,
    PollOut,
)
from app.services.auto_pick import find_best_slots
from app.services.polls import PollSendFailed, create_poll_in_chat

log = structlog.get_logger()
router = APIRouter(tags=["polls"])


@router.post("/polls", response_model=PollOut)
async def create_poll(
    body: PollCreateRequest,
    session: SessionDep,
    user: CurrentUser,
) -> PollOut:
    settings = get_settings()
    chat_id = body.chat_id or settings.group_chat_id
    if not chat_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "no_chat_id: set GROUP_CHAT_ID env var or pass chat_id",
        )

    # ЛОКАЛЬНЫЙ ИМПОРТ
    from app.bot.dispatcher import get_bot
    bot = get_bot()

    try:
        poll = await create_poll_in_chat(
            session,
            bot,
            created_by=user,
            chat_id=chat_id,
            question=body.question,
            options=body.options,
            closes_in_hours=body.closes_in_hours,
        )
    except PollSendFailed as exc:
        # GHG6 hotfix: send_poll упал по таймауту/network — отдаём 503,
        # не вешаем ASGI.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"telegram_send_failed:{exc.reason}",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        log.warning("poll.create_failed", error=str(exc))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"telegram_error:{exc}") from exc

    options = list(
        (
            await session.scalars(
                select(PollOption).where(PollOption.poll_id == poll.id).order_by(PollOption.id)
            )
        ).all()
    )
    return PollOut(
        id=poll.id,
        question=poll.question,
        closes_at=poll.closes_at,
        options=[
            PollOptionOut(id=o.id, starts_at=o.starts_at, label=o.label, voter_user_ids=[])
            for o in options
        ],
        my_vote_option_id=None,
    )


@router.post("/polls/auto-pick", response_model=PollOut)
async def create_auto_pick_poll(
    body: PollAutoPickRequest,
    session: SessionDep,
    user: CurrentUser,
) -> PollOut:
    settings = get_settings()
    chat_id = body.chat_id or settings.group_chat_id
    if not chat_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "no_chat_id: set GROUP_CHAT_ID env var or pass chat_id",
        )
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

    if len(slots) < 2:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "not_enough_slots: hide busy days or widen the window",
        )

    options = [s.starts_at for s in slots]

    # ЛОКАЛЬНЫЙ ИМПОРТ
    from app.bot.dispatcher import get_bot
    bot = get_bot()

    try:
        poll = await create_poll_in_chat(
            session,
            bot,
            created_by=user,
            chat_id=chat_id,
            question=body.question,
            options=options,
            closes_in_hours=body.closes_in_hours,
        )
    except PollSendFailed as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"telegram_send_failed:{exc.reason}",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        log.warning("poll.auto_pick_failed", error=str(exc))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"telegram_error:{exc}") from exc

    poll_options = list(
        (
            await session.scalars(
                select(PollOption).where(PollOption.poll_id == poll.id).order_by(PollOption.id)
            )
        ).all()
    )
    return PollOut(
        id=poll.id,
        question=poll.question,
        closes_at=poll.closes_at,
        options=[
            PollOptionOut(id=o.id, starts_at=o.starts_at, label=o.label, voter_user_ids=[])
            for o in poll_options
        ],
        my_vote_option_id=None,
    )


@router.get("/polls", response_model=list[PollOut])
async def list_polls(
    session: SessionDep,
    user: CurrentUser,
) -> list[PollOut]:
    polls = list(
        (await session.scalars(select(Poll).order_by(Poll.id.desc()).limit(20))).all()
    )
    if not polls:
        return []

    poll_ids = [p.id for p in polls]
    options = list(
        (
            await session.scalars(
                select(PollOption)
                .where(PollOption.poll_id.in_(poll_ids))
                .order_by(PollOption.id)
            )
        ).all()
    )

    options_by_poll: dict[int, list[PollOption]] = defaultdict(list)
    for o in options:
        options_by_poll[o.poll_id].append(o)

    option_ids = [o.id for o in options]
    voters_by_option: dict[int, list[int]] = defaultdict(list)
    my_vote_by_poll: dict[int, int] = {}

    if option_ids:
        votes = list(
            (
                await session.scalars(
                    select(PollVote).where(PollVote.poll_option_id.in_(option_ids))
                )
            ).all()
        )
        option_to_poll = {o.id: o.poll_id for o in options}
        for v in votes:
            voters_by_option[v.poll_option_id].append(v.user_id)
            if v.user_id == user.id:
                pid = option_to_poll.get(v.poll_option_id)
                if pid is not None:
                    my_vote_by_poll[pid] = v.poll_option_id

    out: list[PollOut] = []
    for p in polls:
        out.append(
            PollOut(
                id=p.id,
                question=p.question,
                closes_at=p.closes_at,
                options=[
                    PollOptionOut(
                        id=o.id,
                        starts_at=o.starts_at,
                        label=o.label,
                        voter_user_ids=voters_by_option.get(o.id, []),
                    )
                    for o in options_by_poll.get(p.id, [])
                ],
                my_vote_option_id=my_vote_by_poll.get(p.id),
            )
        )
    return out