from __future__ import annotations
from datetime import date, datetime, timezone
import structlog
# Добавлен импорт Response
from fastapi import APIRouter, HTTPException, status, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import CurrentUser, SessionDep
from app.bot.scheduler import get_scheduler, reload_dynamic_jobs
from app.config import get_settings
from app.db.models import Birthday, LoserRoll, Meeting, MeetingReminder, Poll, User, WeeklyChukhan
from app.services.admin_config import (
    get_autoloser_settings,
    get_chukhan_weights,
    get_loser_reasons,
    get_poll_time_presets,
    get_random_phrases_collective_chance,
    get_random_phrases_count,
    get_random_phrases_count_range,
    get_random_phrases_enabled,
    get_random_phrases_lookback_days,
    get_random_phrases_mode,
    get_random_phrases_schedule,
    get_random_phrases_user_chance,
    get_reminders_tick_minutes,
    reset_chukhan_weight,
    set_autoloser_settings,
    set_chukhan_weight,
    set_loser_reasons,
    set_poll_time_presets,
    set_random_phrases_collective_chance,
    set_random_phrases_count,
    set_random_phrases_count_range,
    set_random_phrases_enabled,
    set_random_phrases_lookback_days,
    set_random_phrases_mode,
    set_random_phrases_schedule,
    set_random_phrases_user_chance,
    set_reminders_tick_minutes,
)
from app.services.random_phrases import run_random_phrases_job
from app.services.chukhan import announce_chukhan, current_week_start

log = structlog.get_logger()
router = APIRouter(tags=["admin"])

def _ensure_admin(user: User) -> None:
    admin_ids = get_settings().admin_tg_id_set
    if user.telegram_id not in admin_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not_admin")

class WeightOut(BaseModel):
    user_id: int
    telegram_id: int
    display_name: str
    weight: float

class WeightUpdate(BaseModel):
    weight: float = Field(..., ge=0.0, le=100.0)

class ChukhanWeekOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    week_start: datetime
    user_id: int
    posted_at: datetime | None
    tg_message_id: int | None

class ChukhanLeaderRow(BaseModel):
    user_id: int
    count: int

class ScheduledJobOut(BaseModel):
    id: str
    kind: str
    label: str
    next_run_at: datetime | None
    detail: str | None = None

class RandomPhrasesSettings(BaseModel):
    enabled: bool
    count: int = Field(..., ge=2, le=6)

@router.get("/admin/chukhan/weights", response_model=list[WeightOut])
async def list_weights(session: SessionDep, user: CurrentUser) -> list[WeightOut]:
    _ensure_admin(user)
    weights = await get_chukhan_weights(session)
    users = list((await session.scalars(select(User).order_by(User.id))).all())
    return [
        WeightOut(
            user_id=u.id,
            telegram_id=u.telegram_id,
            display_name=u.display_name,
            weight=weights.get(u.telegram_id, 1.0),
        )
        for u in users
    ]

@router.put("/admin/chukhan/weights/{telegram_id}", response_model=WeightOut)
async def update_weight(
    telegram_id: int,
    body: WeightUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> WeightOut:
    _ensure_admin(user)
    target = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    await set_chukhan_weight(session, tg_id=telegram_id, weight=body.weight)
    return WeightOut(
        user_id=target.id,
        telegram_id=target.telegram_id,
        display_name=target.display_name,
        weight=body.weight,
    )

# Исправленный Reset Weight
@router.delete(
    "/admin/chukhan/weights/{telegram_id}", 
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response # Явно указываем класс ответа
)
async def reset_weight(
    telegram_id: int,
    session: SessionDep,
    user: CurrentUser,
):
    _ensure_admin(user)
    await reset_chukhan_weight(session, tg_id=telegram_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post("/admin/chukhan/reroll", response_model=ChukhanWeekOut | None)
async def force_reroll(
    session: SessionDep,
    user: CurrentUser,
) -> WeeklyChukhan | None:
    _ensure_admin(user)
    from app.bot.dispatcher import get_bot
    ws = current_week_start()
    existing = await session.scalar(
        select(WeeklyChukhan).where(WeeklyChukhan.week_start == ws)
    )
    if existing is not None:
        await session.delete(existing)
        await session.commit()
    row = await announce_chukhan(get_bot(), session)
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no_group_chat_id")
    return row

@router.get("/admin/chukhan/history", response_model=list[ChukhanWeekOut])
async def chukhan_history(
    session: SessionDep,
    user: CurrentUser,
) -> list[WeeklyChukhan]:
    _ensure_admin(user)
    rows = await session.scalars(
        select(WeeklyChukhan).order_by(desc(WeeklyChukhan.week_start)).limit(20)
    )
    return list(rows.all())

_JOB_LABELS: dict[str, str] = {
    "chukhan_weekly": "💩 Чухан недели (cron)",
    "meeting_reminders_tick": "⏰ Тик напоминаний",
    "avatar_sync_daily": "🖼️ Синхронизация аватарок",
    "random_phrases": "💬 Автопост рандомных фраз",
    "autoloser": "🤡 Автолох",
    "birthdays_daily": "🎂 Дни рождения (ежедневная проверка)",
}

@router.get("/admin/jobs", response_model=list[ScheduledJobOut])
async def list_scheduled_jobs(
    session: SessionDep,
    user: CurrentUser,
) -> list[ScheduledJobOut]:
    _ensure_admin(user)
    out: list[ScheduledJobOut] = []
    sched = get_scheduler()
    for job in sched.get_jobs():
        if job.id.startswith("random_phrases:extra:"):
            label = f"💬 Автопост фраз (доп. {job.id.rsplit(':', 1)[-1]})"
        else:
            label = _JOB_LABELS.get(job.id, job.id)
        out.append(
            ScheduledJobOut(
                id=job.id,
                kind="cron" if "cron" in str(type(job.trigger)).lower() else "interval",
                label=label,
                next_run_at=job.next_run_time,
                detail=str(job.trigger),
            )
        )
    reminder_rows = list(
        (
            await session.execute(
                select(MeetingReminder, Meeting)
                .join(Meeting, Meeting.id == MeetingReminder.meeting_id)
                .where(MeetingReminder.sent_at.is_(None))
                .where(Meeting.status != "cancelled")
                .order_by(MeetingReminder.due_at.asc())
                .limit(20)
            )
        ).all()
    )
    for rem, meeting in reminder_rows:
        out.append(
            ScheduledJobOut(
                id=f"reminder:{rem.id}",
                kind="reminder",
                label=f"📅 «{meeting.title}» (-{rem.offset_minutes} мин)",
                next_run_at=rem.due_at,
                detail=f"meeting_id={meeting.id}",
            )
        )
    return out

# Исправленный Cancel Job
@router.delete(
    "/admin/jobs/{job_id:path}", 
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response # Явно указываем класс ответа
)
async def cancel_job(
    job_id: str,
    session: SessionDep,
    user: CurrentUser,
):
    _ensure_admin(user)
    if job_id.startswith("reminder:"):
        try:
            rem_id = int(job_id.split(":", 1)[1])
        except (ValueError, IndexError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad_job_id")
        rem = await session.get(MeetingReminder, rem_id)
        if rem is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "reminder_not_found")
        if rem.sent_at is not None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        rem.sent_at = datetime.now(timezone.utc)
        await session.commit()
        log.info("admin.reminder_cancelled", reminder_id=rem_id, by=user.id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "system_job_not_cancellable")

@router.get("/admin/random-phrases", response_model=RandomPhrasesSettings)
async def get_random_phrases(
    session: SessionDep,
    user: CurrentUser,
) -> RandomPhrasesSettings:
    _ensure_admin(user)
    return RandomPhrasesSettings(
        enabled=await get_random_phrases_enabled(session),
        count=await get_random_phrases_count(session),
    )

@router.put("/admin/random-phrases", response_model=RandomPhrasesSettings)
async def update_random_phrases(
    body: RandomPhrasesSettings,
    session: SessionDep,
    user: CurrentUser,
) -> RandomPhrasesSettings:
    _ensure_admin(user)
    await set_random_phrases_enabled(session, body.enabled)
    await set_random_phrases_count(session, body.count)
    log.info("admin.random_phrases_updated", enabled=body.enabled, count=body.count)
    return body

@router.post("/admin/random-phrases/run-now", status_code=status.HTTP_202_ACCEPTED)
async def trigger_random_phrases(user: CurrentUser) -> dict[str, str]:
    _ensure_admin(user)
    from app.bot.dispatcher import get_bot
    await run_random_phrases_job(get_bot())
    return {"status": "triggered"}


# --- G3: Pool stats (сколько фраз доступно на каждого юзера сейчас) ---

class RandomPhrasesPoolRow(BaseModel):
    user_id: int
    display_name: str
    chunks_count: int


class RandomPhrasesPoolOut(BaseModel):
    lookback_days: int
    total_chunks: int
    rows: list[RandomPhrasesPoolRow]


@router.get("/admin/random-phrases/pool", response_model=RandomPhrasesPoolOut)
async def get_rp_pool(session: SessionDep, user: CurrentUser) -> RandomPhrasesPoolOut:
    _ensure_admin(user)
    from datetime import timedelta as _td
    from app.db.models import ChatMessage as _CM
    from app.services.random_phrases import _split_into_chunks

    lookback_days = await get_random_phrases_lookback_days(session)
    cutoff = datetime.now(timezone.utc) - _td(days=lookback_days)
    rows = list((await session.execute(
        select(_CM.user_id, _CM.text).where(_CM.sent_at >= cutoff)
    )).all())

    by_user: dict[int, int] = {}
    total = 0
    for uid, text in rows:
        if uid is None:
            continue
        cnt = len(_split_into_chunks(text or ""))
        if cnt:
            by_user[int(uid)] = by_user.get(int(uid), 0) + cnt
            total += cnt

    users = (await session.scalars(select(User).order_by(User.id))).all()
    out_rows = [
        RandomPhrasesPoolRow(
            user_id=u.id,
            display_name=u.display_name,
            chunks_count=by_user.get(u.id, 0),
        )
        for u in users
    ]
    out_rows.sort(key=lambda r: (-r.chunks_count, r.display_name))
    return RandomPhrasesPoolOut(
        lookback_days=lookback_days, total_chunks=total, rows=out_rows
    )

class AdminPollOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    question: str
    closes_at: datetime | None
    created_at: datetime
    tg_message_id: int | None
    is_open: bool


@router.get("/admin/polls", response_model=list[AdminPollOut])
async def list_admin_polls(
    session: SessionDep,
    user: CurrentUser,
) -> list[AdminPollOut]:
    """Последние 20 опросов с признаком is_open (closes_at в будущем или null)."""
    _ensure_admin(user)
    rows = list(
        (await session.scalars(select(Poll).order_by(desc(Poll.id)).limit(20))).all()
    )
    now = datetime.now(timezone.utc)
    return [
        AdminPollOut(
            id=p.id,
            question=p.question,
            closes_at=p.closes_at,
            created_at=p.created_at,
            tg_message_id=p.tg_message_id,
            is_open=p.closes_at is None or p.closes_at > now,
        )
        for p in rows
    ]


@router.post("/admin/polls/{poll_id}/close", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def close_admin_poll(
    poll_id: int,
    session: SessionDep,
    user: CurrentUser,
) -> Response:
    """Закрыть зависший опрос: попытка stopPoll в TG (best-effort), потом фиксируем closes_at=now."""
    _ensure_admin(user)
    poll = await session.get(Poll, poll_id)
    if poll is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "poll_not_found")

    settings = get_settings()
    chat_id = settings.group_chat_id
    if chat_id and poll.tg_message_id is not None:
        from app.bot.dispatcher import get_bot
        bot = get_bot()
        try:
            await bot.stop_poll(chat_id=chat_id, message_id=poll.tg_message_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "admin.poll_stop_failed",
                poll_id=poll_id,
                tg_message_id=poll.tg_message_id,
                error=str(exc),
            )

    poll.closes_at = datetime.now(timezone.utc)
    await session.commit()
    log.info("admin.poll_closed", poll_id=poll_id, by=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/admin/polls/{poll_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_admin_poll(
    poll_id: int,
    session: SessionDep,
    user: CurrentUser,
) -> Response:
    """Полностью удалить опрос: stopPoll + deleteMessage (best-effort) + delete row.
    options/votes уезжают каскадом по FK."""
    _ensure_admin(user)
    poll = await session.get(Poll, poll_id)
    if poll is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "poll_not_found")

    settings = get_settings()
    chat_id = settings.group_chat_id
    if chat_id and poll.tg_message_id is not None:
        from app.bot.dispatcher import get_bot
        bot = get_bot()
        try:
            await bot.stop_poll(chat_id=chat_id, message_id=poll.tg_message_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("admin.poll_stop_failed", poll_id=poll_id, error=str(exc))
        try:
            await bot.delete_message(chat_id=chat_id, message_id=poll.tg_message_id)
        except Exception as exc:  # noqa: BLE001
            # delete_message в TG разрешён только в течение 48 часов — лог, не ошибка.
            log.warning("admin.poll_delete_msg_failed", poll_id=poll_id, error=str(exc))

    await session.delete(poll)
    await session.commit()
    log.info("admin.poll_deleted", poll_id=poll_id, by=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- G2.10 + G3.6: единый endpoint настроек опросов в чате ---

class PollsDefaultsIO(BaseModel):
    """Дефолты опросов в чате — единый блок для UI «Опросы в чате».

    `pin_default` (G2): пинить ли создаваемые опросы. PUT-запросы создания
    опроса с `pin=null` берут это значение как дефолт.
    `quorum_auto_close` (G3): закрывать ли опрос досрочно при достижении
    кворума уникальных голосовавших.
    `live_participants_count` (G3): сколько уникальных голосов = «все живые».
    Default 5 (шестёрка минус автор/админ обычно).
    `pin_result` (G3): пинить ли announce-сообщение с результатами после
    закрытия опроса (game_choice/game_when/zaebal).
    """

    pin_default: bool
    quorum_auto_close: bool
    live_participants_count: int = Field(..., ge=1, le=10)
    pin_result: bool


@router.get("/admin/polls/defaults", response_model=PollsDefaultsIO)
async def get_polls_defaults(
    session: SessionDep,
    user: CurrentUser,
) -> PollsDefaultsIO:
    _ensure_admin(user)
    from app.services.admin_config import (
        get_polls_live_participants,
        get_polls_pin_default,
        get_polls_pin_result,
        get_polls_quorum_auto_close,
    )

    return PollsDefaultsIO(
        pin_default=await get_polls_pin_default(session),
        quorum_auto_close=await get_polls_quorum_auto_close(session),
        live_participants_count=await get_polls_live_participants(session),
        pin_result=await get_polls_pin_result(session),
    )


@router.put("/admin/polls/defaults", response_model=PollsDefaultsIO)
async def put_polls_defaults(
    body: PollsDefaultsIO,
    session: SessionDep,
    user: CurrentUser,
) -> PollsDefaultsIO:
    _ensure_admin(user)
    from app.services.admin_config import (
        set_polls_live_participants,
        set_polls_pin_default,
        set_polls_pin_result,
        set_polls_quorum_auto_close,
    )

    await set_polls_pin_default(session, body.pin_default)
    await set_polls_quorum_auto_close(session, body.quorum_auto_close)
    await set_polls_live_participants(session, body.live_participants_count)
    await set_polls_pin_result(session, body.pin_result)
    return body


@router.get("/chukhan/leaderboard", response_model=list[ChukhanLeaderRow])
async def chukhan_leaderboard(
    session: SessionDep,
    _: CurrentUser,
) -> list[ChukhanLeaderRow]:
    rows = (
        await session.execute(
            select(WeeklyChukhan.user_id, func.count())
            .group_by(WeeklyChukhan.user_id)
            .order_by(func.count().desc())
        )
    ).all()
    return [ChukhanLeaderRow(user_id=int(uid), count=int(cnt)) for uid, cnt in rows]


# =================== P2 (A1–A7) admin endpoints ===================

# --- A1: Loser reasons CRUD ---

class LoserReasonsOut(BaseModel):
    reasons: list[str]


class LoserReasonsUpdate(BaseModel):
    reasons: list[str] = Field(..., max_length=500)


@router.get("/admin/loser-reasons", response_model=LoserReasonsOut)
async def list_loser_reasons(session: SessionDep, user: CurrentUser) -> LoserReasonsOut:
    _ensure_admin(user)
    return LoserReasonsOut(reasons=await get_loser_reasons(session))


@router.put("/admin/loser-reasons", response_model=LoserReasonsOut)
async def update_loser_reasons(
    body: LoserReasonsUpdate, session: SessionDep, user: CurrentUser
) -> LoserReasonsOut:
    _ensure_admin(user)
    await set_loser_reasons(session, body.reasons)
    saved = await get_loser_reasons(session)
    log.info("admin.loser_reasons_updated", count=len(saved), by=user.id)
    return LoserReasonsOut(reasons=saved)


# --- GHG6 AD6: chukhan reasons (по образцу loser_reasons) ---

from app.services.admin_config import (
    get_chukhan_reasons as _get_chukhan_reasons,
    set_chukhan_reasons as _set_chukhan_reasons,
    get_scheduled_settings as _get_sched,
    set_scheduled_settings as _set_sched,
)


class ChukhanReasonsOut(BaseModel):
    reasons: list[str]


class ChukhanReasonsUpdate(BaseModel):
    reasons: list[str] = Field(..., max_length=500)


@router.get("/admin/chukhan-reasons", response_model=ChukhanReasonsOut)
async def admin_get_chukhan_reasons(
    session: SessionDep, user: CurrentUser
) -> ChukhanReasonsOut:
    _ensure_admin(user)
    return ChukhanReasonsOut(reasons=await _get_chukhan_reasons(session))


@router.put("/admin/chukhan-reasons", response_model=ChukhanReasonsOut)
async def admin_update_chukhan_reasons(
    body: ChukhanReasonsUpdate, session: SessionDep, user: CurrentUser
) -> ChukhanReasonsOut:
    _ensure_admin(user)
    await _set_chukhan_reasons(session, body.reasons)
    saved = await _get_chukhan_reasons(session)
    log.info("admin.chukhan_reasons_updated", count=len(saved), by=user.id)
    return ChukhanReasonsOut(reasons=saved)


# --- GHG6 E5.3: счётчики использований фраз (для подписи `(use:N)` в UI) ---
# Хранятся в admin_config как `{phrase_hash: count}` — формат, удобный для
# weighted_choice (вес = 1/(1+count)). Фронту удобнее {phrase: count}, поэтому
# мерджим прямо здесь. Лишних счётчиков «осиротевших» хешей в ответе нет —
# UI рисует подпись только напротив актуальных фраз.

from app.services.phrase_weights import (
    CHUKHAN_USE_COUNTS_KEY,
    LOSER_USE_COUNTS_KEY,
    clear_use_counts,
    get_use_counts,
    phrase_hash,
)


class ReasonUseCountsOut(BaseModel):
    """Словарь `{phrase: count}` для всех актуальных фраз. Фразы без записи
    в счётчиках попадают со значением 0 — фронту не надо угадывать.
    """
    counts: dict[str, int]


class ReasonUseCountsCleared(BaseModel):
    cleared: int


async def _merge_counts_by_phrase(
    reasons: list[str], counts_by_hash: dict[str, int]
) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in reasons:
        out[p] = int(counts_by_hash.get(phrase_hash(p), 0))
    return out


@router.get(
    "/admin/loser-reasons/use-counts", response_model=ReasonUseCountsOut
)
async def admin_get_loser_reason_use_counts(
    session: SessionDep, user: CurrentUser
) -> ReasonUseCountsOut:
    _ensure_admin(user)
    reasons = await get_loser_reasons(session)
    counts = await get_use_counts(session, LOSER_USE_COUNTS_KEY)
    return ReasonUseCountsOut(counts=await _merge_counts_by_phrase(reasons, counts))


@router.delete(
    "/admin/loser-reasons/use-counts", response_model=ReasonUseCountsCleared
)
async def admin_clear_loser_reason_use_counts(
    session: SessionDep, user: CurrentUser
) -> ReasonUseCountsCleared:
    _ensure_admin(user)
    n = await clear_use_counts(session, LOSER_USE_COUNTS_KEY)
    await session.commit()
    log.info("admin.loser_reason_use_counts_cleared", removed=n, by=user.id)
    return ReasonUseCountsCleared(cleared=n)


@router.get(
    "/admin/chukhan-reasons/use-counts", response_model=ReasonUseCountsOut
)
async def admin_get_chukhan_reason_use_counts(
    session: SessionDep, user: CurrentUser
) -> ReasonUseCountsOut:
    _ensure_admin(user)
    reasons = await _get_chukhan_reasons(session)
    counts = await get_use_counts(session, CHUKHAN_USE_COUNTS_KEY)
    return ReasonUseCountsOut(counts=await _merge_counts_by_phrase(reasons, counts))


@router.delete(
    "/admin/chukhan-reasons/use-counts", response_model=ReasonUseCountsCleared
)
async def admin_clear_chukhan_reason_use_counts(
    session: SessionDep, user: CurrentUser
) -> ReasonUseCountsCleared:
    _ensure_admin(user)
    n = await clear_use_counts(session, CHUKHAN_USE_COUNTS_KEY)
    await session.commit()
    log.info("admin.chukhan_reason_use_counts_cleared", removed=n, by=user.id)
    return ReasonUseCountsCleared(cleared=n)


# --- GHG6 AD4/AD7/AD8: scheduled settings (агрегат master-toggles) ---


class ScheduledRemindersIO(BaseModel):
    enabled: bool
    tick_minutes: int = Field(..., ge=1, le=120)


class ScheduledLoserIO(BaseModel):
    enabled: bool
    per_day: int = Field(..., ge=1, le=12)
    window_start_hour: int = Field(..., ge=0, le=23)
    window_end_hour: int = Field(..., ge=0, le=23)
    interval_hours: int = Field(..., ge=0, le=72)


class ScheduledPhrasesIO(BaseModel):
    enabled: bool
    window_start: str
    window_end: str


class ScheduledAvatarsIO(BaseModel):
    enabled: bool
    per_day: float = Field(..., ge=0.14, le=24.0)


class ScheduledBirthdaysIO(BaseModel):
    alerts_enabled: bool


class ScheduledChukhanIO(BaseModel):
    weekday: int = Field(..., ge=0, le=6)
    window_start: str
    window_end: str


class ScheduledSettingsIO(BaseModel):
    reminders: ScheduledRemindersIO
    loser: ScheduledLoserIO
    phrases: ScheduledPhrasesIO
    avatars: ScheduledAvatarsIO
    birthdays: ScheduledBirthdaysIO
    chukhan: ScheduledChukhanIO


@router.get("/admin/scheduled", response_model=ScheduledSettingsIO)
async def admin_get_scheduled(
    session: SessionDep, user: CurrentUser
) -> ScheduledSettingsIO:
    _ensure_admin(user)
    return ScheduledSettingsIO(**(await _get_sched(session)))


@router.put("/admin/scheduled", response_model=ScheduledSettingsIO)
async def admin_set_scheduled(
    body: ScheduledSettingsIO, session: SessionDep, user: CurrentUser
) -> ScheduledSettingsIO:
    _ensure_admin(user)
    await _set_sched(session, body.model_dump())
    log.info("admin.scheduled_updated", by=user.id)
    # После записи — пересоберём динамические job'ы.
    from app.bot.dispatcher import get_bot

    try:
        await reload_dynamic_jobs(get_bot())
    except Exception:  # noqa: BLE001
        log.exception("admin.scheduled_reload_failed")
    return ScheduledSettingsIO(**(await _get_sched(session)))


# --- GHG6 AD5: quick action «крутануть лоха» через admin API ---


class LoserRollNowOut(BaseModel):
    ok: bool
    loser_user_id: int | None = None
    reason_text: str | None = None
    error: str | None = None


@router.post("/admin/loser/roll-now", response_model=LoserRollNowOut)
async def admin_loser_roll_now(
    session: SessionDep, user: CurrentUser
) -> LoserRollNowOut:
    """Прокручивает лоха немедленно (как quick-action в шапке AdminScreen).

    Использует тот же `roll_loser`, что и обычный пользовательский флоу.
    Анонс в групповой чат идёт через on_announce — best-effort, ошибки TG не
    блокируют ответ API (детальная сетевая обработка — на стороне основного
    LoserSheet).
    """
    _ensure_admin(user)
    from app.bot.dispatcher import get_bot
    from app.config import get_settings as _gs
    from app.services.loser import compose_loser_message, roll_loser

    settings = _gs()
    bot = get_bot()

    async def _announce(roll, loser, extras=None):
        if not settings.group_chat_id:
            return
        try:
            await bot.send_message(
                chat_id=settings.group_chat_id,
                text=compose_loser_message(
                    loser_name=loser.display_name,
                    reason_text=roll.reason_text or "",
                    roller_name=user.display_name,
                    extras=extras,
                    header_emoji="🤡",
                    header_label="Лох дня",
                ),
                parse_mode="HTML",
            )
        except Exception:  # noqa: BLE001
            log.warning("admin.loser_roll_announce_failed")

    try:
        # GHG6 H1: admin force-reroll — source='manual' (он же — ручная
        # рулетка, просто игнорирующая cooldown), bypass_cooldown=True
        # сохраняет старое поведение «крутить, когда захочется».
        roll = await roll_loser(
            session,
            rolled_by=user,
            on_announce=_announce,
            source="manual",
            bypass_cooldown=True,
        )
        return LoserRollNowOut(
            ok=True,
            loser_user_id=roll.loser_user_id,
            reason_text=roll.reason_text,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("admin.loser_roll_failed", error=str(exc))
        return LoserRollNowOut(ok=False, error=str(exc))


# --- A2: Reminders tick ---

class RemindersSettingsOut(BaseModel):
    tick_minutes: int


class RemindersSettingsUpdate(BaseModel):
    tick_minutes: int = Field(..., ge=1, le=120)


@router.get("/admin/reminders", response_model=RemindersSettingsOut)
async def get_reminders(session: SessionDep, user: CurrentUser) -> RemindersSettingsOut:
    _ensure_admin(user)
    return RemindersSettingsOut(tick_minutes=await get_reminders_tick_minutes(session))


@router.put("/admin/reminders", response_model=RemindersSettingsOut)
async def update_reminders(
    body: RemindersSettingsUpdate, session: SessionDep, user: CurrentUser
) -> RemindersSettingsOut:
    _ensure_admin(user)
    await set_reminders_tick_minutes(session, body.tick_minutes)
    from app.bot.dispatcher import get_bot
    await reload_dynamic_jobs(get_bot())
    log.info("admin.reminders_tick_updated", minutes=body.tick_minutes, by=user.id)
    return RemindersSettingsOut(tick_minutes=body.tick_minutes)


# --- A3 + A4: Random phrases (schedule + generator) ---

class RandomPhrasesScheduleOut(BaseModel):
    mode: str
    param: dict


class RandomPhrasesScheduleUpdate(BaseModel):
    mode: str = Field(..., pattern="^(daily_n|weekly_n|fixed_times|random_interval)$")
    param: dict = Field(default_factory=dict)


@router.get("/admin/random-phrases/schedule", response_model=RandomPhrasesScheduleOut)
async def get_rp_schedule(session: SessionDep, user: CurrentUser) -> RandomPhrasesScheduleOut:
    _ensure_admin(user)
    mode, param = await get_random_phrases_schedule(session)
    return RandomPhrasesScheduleOut(mode=mode, param=param)


@router.put("/admin/random-phrases/schedule", response_model=RandomPhrasesScheduleOut)
async def update_rp_schedule(
    body: RandomPhrasesScheduleUpdate, session: SessionDep, user: CurrentUser
) -> RandomPhrasesScheduleOut:
    _ensure_admin(user)
    await set_random_phrases_schedule(session, body.mode, body.param)
    from app.bot.dispatcher import get_bot
    await reload_dynamic_jobs(get_bot())
    log.info("admin.rp_schedule_updated", mode=body.mode, param=body.param, by=user.id)
    return RandomPhrasesScheduleOut(mode=body.mode, param=body.param)


class GeneratorSettingsOut(BaseModel):
    count_min: int
    count_max: int
    lookback_days: int
    collective_chance: float
    user_chance: float
    # GHG6 L: режим сбора фраз — отдельные слова / целые фразы / смесь.
    mode: str = Field("mix", pattern="^(words|phrases|mix)$")


class GeneratorSettingsUpdate(BaseModel):
    count_min: int = Field(..., ge=2, le=6)
    count_max: int = Field(..., ge=2, le=6)
    lookback_days: int = Field(..., ge=1, le=365)
    collective_chance: float = Field(..., ge=0.0, le=1.0)
    user_chance: float = Field(..., ge=0.0, le=1.0)
    # GHG6 L: дефолт 'mix' — старые клиенты не присылают mode.
    mode: str = Field("mix", pattern="^(words|phrases|mix)$")


@router.get("/admin/random-phrases/generator", response_model=GeneratorSettingsOut)
async def get_rp_generator(session: SessionDep, user: CurrentUser) -> GeneratorSettingsOut:
    _ensure_admin(user)
    cmin, cmax = await get_random_phrases_count_range(session)
    return GeneratorSettingsOut(
        count_min=cmin,
        count_max=cmax,
        lookback_days=await get_random_phrases_lookback_days(session),
        collective_chance=await get_random_phrases_collective_chance(session),
        user_chance=await get_random_phrases_user_chance(session),
        mode=await get_random_phrases_mode(session),
    )


@router.put("/admin/random-phrases/generator", response_model=GeneratorSettingsOut)
async def update_rp_generator(
    body: GeneratorSettingsUpdate, session: SessionDep, user: CurrentUser
) -> GeneratorSettingsOut:
    _ensure_admin(user)
    await set_random_phrases_count_range(session, body.count_min, body.count_max)
    await set_random_phrases_lookback_days(session, body.lookback_days)
    await set_random_phrases_collective_chance(session, body.collective_chance)
    await set_random_phrases_user_chance(session, body.user_chance)
    await set_random_phrases_mode(session, body.mode)
    log.info("admin.rp_generator_updated", body=body.model_dump(), by=user.id)
    return body


# --- A6: Auto-loser ---

class AutoLoserSettingsOut(BaseModel):
    enabled: bool
    window_start_hour: int
    window_end_hour: int
    interval_hours: int


class AutoLoserSettingsUpdate(BaseModel):
    enabled: bool
    window_start_hour: int = Field(..., ge=0, le=23)
    window_end_hour: int = Field(..., ge=0, le=23)
    interval_hours: int = Field(..., ge=0, le=72)


@router.get("/admin/autoloser", response_model=AutoLoserSettingsOut)
async def get_autoloser(session: SessionDep, user: CurrentUser) -> AutoLoserSettingsOut:
    _ensure_admin(user)
    return AutoLoserSettingsOut(**(await get_autoloser_settings(session)))


@router.put("/admin/autoloser", response_model=AutoLoserSettingsOut)
async def update_autoloser(
    body: AutoLoserSettingsUpdate, session: SessionDep, user: CurrentUser
) -> AutoLoserSettingsOut:
    _ensure_admin(user)
    await set_autoloser_settings(
        session,
        enabled=body.enabled,
        window_start_hour=body.window_start_hour,
        window_end_hour=body.window_end_hour,
        interval_hours=body.interval_hours,
    )
    from app.bot.dispatcher import get_bot
    await reload_dynamic_jobs(get_bot())
    log.info("admin.autoloser_updated", body=body.model_dump(), by=user.id)
    return body


# --- E8: «Червь-пидор» ---


class WormSettingsOut(BaseModel):
    enabled: bool
    chance: float  # 0..1


class WormSettingsUpdate(BaseModel):
    enabled: bool | None = None
    chance: float | None = None


@router.get("/admin/worm", response_model=WormSettingsOut)
async def get_worm(session: SessionDep, user: CurrentUser) -> WormSettingsOut:
    _ensure_admin(user)
    from app.services.admin_config import get_worm_chance, is_worm_enabled

    return WormSettingsOut(
        enabled=await is_worm_enabled(session),
        chance=await get_worm_chance(session),
    )


@router.put("/admin/worm", response_model=WormSettingsOut)
async def update_worm(
    body: WormSettingsUpdate, session: SessionDep, user: CurrentUser
) -> WormSettingsOut:
    _ensure_admin(user)
    from app.services.admin_config import (
        get_worm_chance,
        is_worm_enabled,
        set_worm_chance,
        set_worm_enabled,
    )

    if body.enabled is not None:
        await set_worm_enabled(session, body.enabled)
    if body.chance is not None:
        await set_worm_chance(session, body.chance)
    log.info("admin.worm_updated", body=body.model_dump(exclude_unset=True), by=user.id)
    return WormSettingsOut(
        enabled=await is_worm_enabled(session),
        chance=await get_worm_chance(session),
    )


# --- A7: Loser history ---

class LoserHistoryRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rolled_at: datetime
    loser_user_id: int
    rolled_by: int
    reason_text: str | None


@router.get("/admin/loser/history", response_model=list[LoserHistoryRow])
async def loser_history(session: SessionDep, user: CurrentUser) -> list[LoserRoll]:
    _ensure_admin(user)
    rows = await session.scalars(
        select(LoserRoll).order_by(desc(LoserRoll.rolled_at)).limit(30)
    )
    return list(rows.all())


# --- BD2: Birthdays ---

class BirthdayRow(BaseModel):
    user_id: int
    display_name: str
    bday: date | None
    year_known: bool
    remind_month: bool
    remind_week: bool
    remind_day: bool
    remind_on_day: bool
    remind_hint_week: bool


class BirthdayUpdate(BaseModel):
    user_id: int
    bday: date | None = None
    year_known: bool = True
    remind_month: bool = True
    remind_week: bool = True
    remind_day: bool = True
    remind_on_day: bool = True
    remind_hint_week: bool = True


class BirthdaysPut(BaseModel):
    items: list[BirthdayUpdate]


@router.get("/admin/birthdays", response_model=list[BirthdayRow])
async def list_birthdays(session: SessionDep, user: CurrentUser) -> list[BirthdayRow]:
    _ensure_admin(user)
    users = (
        await session.scalars(select(User).order_by(User.id))
    ).all()
    existing = {
        b.user_id: b
        for b in (await session.scalars(select(Birthday))).all()
    }
    out: list[BirthdayRow] = []
    for u in users:
        b = existing.get(u.id)
        if b is None:
            out.append(BirthdayRow(
                user_id=u.id,
                display_name=u.display_name,
                bday=None,
                year_known=True,
                remind_month=True,
                remind_week=True,
                remind_day=True,
                remind_on_day=True,
                remind_hint_week=True,
            ))
        else:
            out.append(BirthdayRow(
                user_id=u.id,
                display_name=u.display_name,
                bday=b.bday,
                year_known=b.year_known,
                remind_month=b.remind_month,
                remind_week=b.remind_week,
                remind_day=b.remind_day,
                remind_on_day=b.remind_on_day,
                remind_hint_week=b.remind_hint_week,
            ))
    return out


@router.put("/admin/birthdays", response_model=list[BirthdayRow])
async def update_birthdays(
    body: BirthdaysPut, session: SessionDep, user: CurrentUser
) -> list[BirthdayRow]:
    _ensure_admin(user)
    valid_ids = {
        row[0] for row in (await session.execute(select(User.id))).all()
    }
    for item in body.items:
        if item.user_id not in valid_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown user_id={item.user_id}")
        stmt = pg_insert(Birthday).values(
            user_id=item.user_id,
            bday=item.bday,
            year_known=item.year_known,
            remind_month=item.remind_month,
            remind_week=item.remind_week,
            remind_day=item.remind_day,
            remind_on_day=item.remind_on_day,
            remind_hint_week=item.remind_hint_week,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Birthday.user_id],
            set_={
                "bday": stmt.excluded.bday,
                "year_known": stmt.excluded.year_known,
                "remind_month": stmt.excluded.remind_month,
                "remind_week": stmt.excluded.remind_week,
                "remind_day": stmt.excluded.remind_day,
                "remind_on_day": stmt.excluded.remind_on_day,
                "remind_hint_week": stmt.excluded.remind_hint_week,
            },
        )
        await session.execute(stmt)
    await session.commit()
    log.info("admin.birthdays_updated", count=len(body.items), by=user.id)
    return await list_birthdays(session, user)

# --- GHG5 POLL-HOURS1: Time presets for polls/auto-pick ---

class PollPresetItem(BaseModel):
    start: str  # HH:MM
    end: str    # HH:MM
    label: str | None = None


class PollPresetsOut(BaseModel):
    presets: list[PollPresetItem]


class PollPresetsUpdate(BaseModel):
    presets: list[PollPresetItem]


@router.get("/admin/poll-presets", response_model=PollPresetsOut)
async def admin_get_poll_presets(session: SessionDep, user: CurrentUser) -> PollPresetsOut:
    _ensure_admin(user)
    raw = await get_poll_time_presets(session)
    return PollPresetsOut(presets=[PollPresetItem(**p) for p in raw])


@router.put("/admin/poll-presets", response_model=PollPresetsOut)
async def admin_update_poll_presets(
    body: PollPresetsUpdate, session: SessionDep, user: CurrentUser
) -> PollPresetsOut:
    _ensure_admin(user)
    await set_poll_time_presets(session, [p.model_dump() for p in body.presets])
    saved = await get_poll_time_presets(session)
    log.info("admin.poll_presets_updated", count=len(saved), by=user.id)
    return PollPresetsOut(presets=[PollPresetItem(**p) for p in saved])


# --- GHG5 P2: Smart Proxy management ---

from app.services.proxies import (
    ProxyMode,
    bootstrap_fetch as _bootstrap_fetch,
    clear_add_errors as _clear_add_errors,
    delete_proxy as _delete_proxy,
    get_add_errors as _get_add_errors,
    get_proxy_mode,
    list_proxies,
    set_proxy_mode,
    update_proxy as _update_proxy,
    upsert_proxy_with_ping,
)


class ProxyOut(BaseModel):
    id: int
    server: str
    port: int
    type: str
    secret: str | None
    enabled: bool
    fail_count: int
    last_ok_at: datetime | None
    last_fail_at: datetime | None
    dead_until: datetime | None


class ProxyCreateIn(BaseModel):
    server: str = Field(..., min_length=1, max_length=255)
    port: int = Field(..., ge=1, le=65535)
    type: str = Field("mtproto", pattern="^(mtproto|socks5|http)$")
    secret: str | None = Field(None, max_length=255)
    enabled: bool = True


class ProxyUpdateIn(BaseModel):
    enabled: bool


class ProxyModeOut(BaseModel):
    mode: str


class ProxyModeIn(BaseModel):
    mode: str = Field(..., pattern="^(always_on|always_off|auto_fallback)$")


def _proxy_to_out(p) -> ProxyOut:
    return ProxyOut(
        id=p.id,
        server=p.server,
        port=p.port,
        type=p.type,
        secret=p.secret,
        enabled=p.enabled,
        fail_count=p.fail_count,
        last_ok_at=p.last_ok_at,
        last_fail_at=p.last_fail_at,
        dead_until=p.dead_until,
    )


@router.get("/admin/proxy/mode", response_model=ProxyModeOut)
async def admin_get_proxy_mode(session: SessionDep, user: CurrentUser) -> ProxyModeOut:
    _ensure_admin(user)
    mode = await get_proxy_mode(session)
    return ProxyModeOut(mode=mode.value)


@router.put("/admin/proxy/mode", response_model=ProxyModeOut)
async def admin_set_proxy_mode(
    body: ProxyModeIn, session: SessionDep, user: CurrentUser
) -> ProxyModeOut:
    _ensure_admin(user)
    await set_proxy_mode(session, ProxyMode(body.mode))
    log.info("admin.proxy_mode_set", mode=body.mode, by=user.id)
    return ProxyModeOut(mode=body.mode)


@router.get("/admin/proxy", response_model=list[ProxyOut])
async def admin_list_proxies(session: SessionDep, user: CurrentUser) -> list[ProxyOut]:
    _ensure_admin(user)
    rows = await list_proxies(session)
    return [_proxy_to_out(r) for r in rows]


class ProxyPingOut(BaseModel):
    proxy_id: int
    ok: bool
    latency_ms: int | None
    error: str | None


class ProxyAddOut(BaseModel):
    """Ответ на POST /admin/proxy (GHG6 E1.2).

    `ping_result=None` означает «не пинговали» (например, прокси создан как
    `enabled=false`). При `type=mtproto` ping_result будет с
    `error="ping_not_supported_for_type:mtproto"` — фронт показывает это
    отдельным состоянием (не «мёртв», а «нельзя проверить по HTTP»).
    """

    proxy: ProxyOut
    created: bool
    ping_result: ProxyPingOut | None


@router.post("/admin/proxy", response_model=ProxyAddOut)
async def admin_create_proxy(
    body: ProxyCreateIn, session: SessionDep, user: CurrentUser
) -> ProxyAddOut:
    _ensure_admin(user)
    try:
        row, created, ping = await upsert_proxy_with_ping(
            session,
            server=body.server,
            port=body.port,
            type_=body.type,
            secret=body.secret,
            enabled=body.enabled,
        )
    except ValueError as exc:
        # ring-buffer для proxy_pool_full и db_error пишется в upsert_proxy.
        # Любую другую ValueError (валидация на бизнес-уровне) тоже фиксируем.
        msg = str(exc)
        if not msg.startswith("proxy_pool_full"):
            from app.services.proxies import record_add_error as _record_add_error
            await _record_add_error(
                session,
                reason="validation_error",
                detail=msg[:300],
                draft={"server": body.server, "port": body.port, "type": body.type},
            )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, msg)
    log.info(
        "admin.proxy_upserted",
        server=body.server,
        port=body.port,
        created=created,
        ping_ok=ping.ok if ping else None,
        by=user.id,
    )
    ping_out = None
    if ping is not None:
        ping_out = ProxyPingOut(
            proxy_id=ping.proxy_id,
            ok=ping.ok,
            latency_ms=ping.latency_ms,
            error=ping.error,
        )
    return ProxyAddOut(proxy=_proxy_to_out(row), created=created, ping_result=ping_out)


@router.put("/admin/proxy/{proxy_id}", response_model=ProxyOut)
async def admin_update_proxy_endpoint(
    proxy_id: int, body: ProxyUpdateIn, session: SessionDep, user: CurrentUser
) -> ProxyOut:
    _ensure_admin(user)
    row = await _update_proxy(session, proxy_id, enabled=body.enabled)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proxy_not_found")
    log.info("admin.proxy_updated", id=proxy_id, enabled=body.enabled, by=user.id)
    return _proxy_to_out(row)


class ProxyEditIn(BaseModel):
    server: str | None = Field(None, min_length=1, max_length=255)
    port: int | None = Field(None, ge=1, le=65535)
    type: str | None = Field(None, pattern="^(mtproto|socks5|http)$")
    secret: str | None = Field(None, max_length=255)
    clear_secret: bool = False
    enabled: bool | None = None


@router.patch("/admin/proxy/{proxy_id}", response_model=ProxyOut)
async def admin_edit_proxy_endpoint(
    proxy_id: int, body: ProxyEditIn, session: SessionDep, user: CurrentUser
) -> ProxyOut:
    _ensure_admin(user)
    row = await _update_proxy(
        session,
        proxy_id,
        enabled=body.enabled,
        server=body.server,
        port=body.port,
        type_=body.type,
        secret=body.secret,
        clear_secret=body.clear_secret,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proxy_not_found")
    log.info("admin.proxy_edited", id=proxy_id, by=user.id)
    return _proxy_to_out(row)


@router.delete("/admin/proxy/{proxy_id}")
async def admin_delete_proxy_endpoint(
    proxy_id: int, session: SessionDep, user: CurrentUser
) -> dict:
    _ensure_admin(user)
    ok = await _delete_proxy(session, proxy_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proxy_not_found")
    log.info("admin.proxy_deleted", id=proxy_id, by=user.id)
    return {"deleted": True}


# --- GHG6 P0: indicators / parser / ping / alerts ---

from app.services.proxies import (
    clear_last_error,
    delete_dead as _delete_dead_proxies,
    get_alerts_enabled,
    get_last_alert_at,
    get_last_error,
    parse_mtproto_blob,
    ping_all as _ping_all_proxies,
    ping_proxy as _ping_proxy,
    selftest_send as _selftest_send,
    set_alerts_enabled,
)


class ProxySelftestOut(BaseModel):
    ok: bool
    mode_used: str
    proxy_id: int | None
    latency_ms: int | None
    error: str | None
    bot_active: bool


class ProxyStatusOut(BaseModel):
    bot_active: bool
    mode: str
    pool_size: int
    alive_count: int
    last_selftest: ProxySelftestOut | None
    last_error: dict | None


class ProxyParseIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)


class ProxyParseOut(BaseModel):
    parsed: list[dict]


class ProxyAlertsIn(BaseModel):
    enabled: bool


class ProxyAlertsOut(BaseModel):
    enabled: bool
    last_alert_at: datetime | None


@router.post("/admin/proxy/selftest", response_model=ProxySelftestOut)
async def admin_proxy_selftest(session: SessionDep, user: CurrentUser) -> ProxySelftestOut:
    _ensure_admin(user)
    from app.bot.dispatcher import get_bot

    bot = get_bot()
    res = await _selftest_send(bot, session=session)
    log.info(
        "admin.proxy_selftest",
        ok=res.ok,
        latency_ms=res.latency_ms,
        mode=res.mode_used,
        by=user.id,
    )
    return ProxySelftestOut(**res.to_dict())


@router.post("/admin/proxy/{proxy_id}/ping", response_model=ProxyPingOut)
async def admin_proxy_ping_one(
    proxy_id: int, session: SessionDep, user: CurrentUser
) -> ProxyPingOut:
    _ensure_admin(user)
    res = await _ping_proxy(session, proxy_id)
    return ProxyPingOut(**res.to_dict())


@router.post("/admin/proxy/ping-all", response_model=list[ProxyPingOut])
async def admin_proxy_ping_all(
    session: SessionDep, user: CurrentUser
) -> list[ProxyPingOut]:
    _ensure_admin(user)
    rows = await _ping_all_proxies(session)
    return [ProxyPingOut(**r.to_dict()) for r in rows]


@router.post("/admin/proxy/delete-dead")
async def admin_proxy_delete_dead(
    session: SessionDep, user: CurrentUser
) -> dict:
    _ensure_admin(user)
    n = await _delete_dead_proxies(session)
    log.info("admin.proxy_delete_dead", count=n, by=user.id)
    return {"deleted": n}


@router.post("/admin/proxy/parse", response_model=ProxyParseOut)
async def admin_proxy_parse(
    body: ProxyParseIn, user: CurrentUser
) -> ProxyParseOut:
    _ensure_admin(user)
    drafts = parse_mtproto_blob(body.text)
    return ProxyParseOut(parsed=[d.to_dict() for d in drafts])


# --- GHG6 E1.1: ring-buffer ошибок добавления прокси ---

class ProxyAddErrorItem(BaseModel):
    at: str
    reason: str
    detail: str
    draft: dict


class ProxyAddErrorsOut(BaseModel):
    errors: list[ProxyAddErrorItem]


@router.get("/admin/proxy/add-errors", response_model=ProxyAddErrorsOut)
async def admin_proxy_get_add_errors(
    session: SessionDep, user: CurrentUser
) -> ProxyAddErrorsOut:
    _ensure_admin(user)
    raw = await _get_add_errors(session)
    items: list[ProxyAddErrorItem] = []
    for r in raw:
        try:
            items.append(
                ProxyAddErrorItem(
                    at=str(r.get("at", "")),
                    reason=str(r.get("reason", "")),
                    detail=str(r.get("detail", "")),
                    draft=r.get("draft") if isinstance(r.get("draft"), dict) else {},
                )
            )
        except Exception:  # noqa: BLE001 — диагностический эндпоинт, не падаем на корявой записи.
            continue
    return ProxyAddErrorsOut(errors=items)


@router.delete("/admin/proxy/add-errors")
async def admin_proxy_clear_add_errors(
    session: SessionDep, user: CurrentUser
) -> dict:
    _ensure_admin(user)
    await _clear_add_errors(session)
    log.info("admin.proxy_add_errors_cleared", by=user.id)
    return {"cleared": True}


# --- GHG6 E1.4: bootstrap-fetch публичного списка прокси ---

class ProxyBootstrapIn(BaseModel):
    # Опциональный override: если задан, env PROXY_BOOTSTRAP_URL игнорируется.
    url_override: str | None = Field(None, min_length=1, max_length=2048)


class ProxyBootstrapOut(BaseModel):
    source_url: str
    fetched: int
    pinged_alive: int
    added: int
    skipped_duplicate: int
    skipped_dead: int
    skipped_pool_full: int
    errors: list[str]


@router.post("/admin/proxy/bootstrap-fetch", response_model=ProxyBootstrapOut)
async def admin_proxy_bootstrap_fetch(
    body: ProxyBootstrapIn | None,
    session: SessionDep,
    user: CurrentUser,
) -> ProxyBootstrapOut:
    """Скачать публичный список прокси, проверить живые, добавить до 10 в пул.

    503 `bootstrap_not_configured` — если ни `url_override`, ни env
    `PROXY_BOOTSTRAP_URL`, ни встроенный список `BUNDLED_BOOTSTRAP_URLS` не дают
    рабочих URL. По умолчанию BUNDLED — пуст (см. proxies.py:510 TODO), так что
    без явного override/env эндпоинт сразу отвечает 503.
    """
    _ensure_admin(user)
    override = body.url_override if body is not None else None
    res = await _bootstrap_fetch(session, url_override=override)
    if "bootstrap_not_configured" in res.errors:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="bootstrap_not_configured",
        )
    log.info("admin.proxy_bootstrap_fetch", by=user.id, **res.to_dict())
    return ProxyBootstrapOut(**res.to_dict())


@router.get("/admin/proxy/status", response_model=ProxyStatusOut)
async def admin_proxy_status(session: SessionDep, user: CurrentUser) -> ProxyStatusOut:
    _ensure_admin(user)
    from app.bot.dispatcher import get_bot
    from app.services.proxies import (
        ensure_loaded as _ensure_loaded,
        get_state_snapshot as _get_state_snapshot,
    )

    await _ensure_loaded(session)
    snap = _get_state_snapshot()
    # Лёгкий пинг через getMe (с тайм-аутом) — чтобы понять «бот вообще жив?».
    bot = get_bot()
    res = await _selftest_send(bot, session=session)
    last_err = await get_last_error(session)
    return ProxyStatusOut(
        bot_active=res.bot_active,
        mode=snap["mode"],
        pool_size=snap["pool_size"],
        alive_count=snap["alive"],
        last_selftest=ProxySelftestOut(**res.to_dict()),
        last_error=last_err,
    )


@router.delete("/admin/proxy/status/last-error")
async def admin_proxy_clear_last_error(
    session: SessionDep, user: CurrentUser
) -> dict:
    _ensure_admin(user)
    await clear_last_error(session)
    return {"cleared": True}


@router.get("/admin/proxy/alerts", response_model=ProxyAlertsOut)
async def admin_proxy_get_alerts(
    session: SessionDep, user: CurrentUser
) -> ProxyAlertsOut:
    _ensure_admin(user)
    return ProxyAlertsOut(
        enabled=await get_alerts_enabled(session),
        last_alert_at=await get_last_alert_at(session),
    )


@router.put("/admin/proxy/alerts", response_model=ProxyAlertsOut)
async def admin_proxy_set_alerts(
    body: ProxyAlertsIn, session: SessionDep, user: CurrentUser
) -> ProxyAlertsOut:
    _ensure_admin(user)
    await set_alerts_enabled(session, body.enabled)
    log.info("admin.proxy_alerts_set", enabled=body.enabled, by=user.id)
    return ProxyAlertsOut(
        enabled=body.enabled,
        last_alert_at=await get_last_alert_at(session),
    )


# =============================================================================
# GHG6 CL0: master-toggle нового таймлайн-вида календаря.
# GET — whitelist-only (читает любой залогиненный, в т.ч. фронт-CalendarView).
# PUT — admin-only.
# =============================================================================


class CalendarTimelineOut(BaseModel):
    enabled: bool


class CalendarTimelineIn(BaseModel):
    enabled: bool


@router.get("/admin/calendar/timeline", response_model=CalendarTimelineOut)
async def admin_calendar_timeline_get(
    session: SessionDep, _: CurrentUser
) -> CalendarTimelineOut:
    # Намеренно без _ensure_admin: флаг видит весь фронт, чтобы
    # CalendarView выбрал legacy/new ветку рендера.
    from app.services.admin_config import get_calendar_timeline_enabled
    return CalendarTimelineOut(enabled=await get_calendar_timeline_enabled(session))


@router.put("/admin/calendar/timeline", response_model=CalendarTimelineOut)
async def admin_calendar_timeline_put(
    body: CalendarTimelineIn, session: SessionDep, user: CurrentUser
) -> CalendarTimelineOut:
    _ensure_admin(user)
    from app.services.admin_config import set_calendar_timeline_enabled
    await set_calendar_timeline_enabled(session, body.enabled)
    log.info("admin.calendar_timeline_set", enabled=body.enabled, by=user.id)
    return CalendarTimelineOut(enabled=body.enabled)


# --- GHG6 E11: bot pause + zaebal settings ---


class BotPauseStartIn(BaseModel):
    duration_days: int | None = None
    reason: str | None = None


class BotPauseOut(BaseModel):
    active: bool
    id: int | None = None
    started_at: datetime | None = None
    ends_at: datetime | None = None
    reason: str | None = None


class ZaebalSettingsIO(BaseModel):
    threshold: int = Field(..., ge=1, le=10)
    duration_days: int = Field(..., ge=1, le=30)
    poll_hours: int = Field(..., ge=1, le=72)
    vote_duration_days: int = Field(..., ge=1, le=30)
    auto_enabled: bool
    auto_max_per_month: int = Field(..., ge=0, le=10)


def _pause_to_out(p) -> BotPauseOut:
    if p is None:
        return BotPauseOut(active=False)
    return BotPauseOut(
        active=p.ended_at is None,
        id=p.id,
        started_at=p.started_at,
        ends_at=p.ends_at,
        reason=p.reason,
    )


@router.get("/admin/bot-pause/current", response_model=BotPauseOut)
async def admin_pause_current(
    session: SessionDep, user: CurrentUser
) -> BotPauseOut:
    _ensure_admin(user)
    from app.services.bot_pause import get_active_pause

    return _pause_to_out(await get_active_pause(session))


@router.post("/admin/bot-pause/start", response_model=BotPauseOut)
async def admin_pause_start(
    body: BotPauseStartIn, session: SessionDep, user: CurrentUser
) -> BotPauseOut:
    _ensure_admin(user)
    from app.services.bot_pause import start_pause

    reason = body.reason or "manual_admin"
    try:
        pause = await start_pause(
            session,
            duration_days=body.duration_days,
            reason=reason,
            started_by_tg_id=user.telegram_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return _pause_to_out(pause)


@router.post("/admin/bot-pause/stop", response_model=BotPauseOut)
async def admin_pause_stop(
    session: SessionDep, user: CurrentUser
) -> BotPauseOut:
    _ensure_admin(user)
    from app.services.bot_pause import stop_pause

    pause = await stop_pause(session)
    return _pause_to_out(pause)


@router.get("/admin/zaebal-settings", response_model=ZaebalSettingsIO)
async def admin_zaebal_get(
    session: SessionDep, user: CurrentUser
) -> ZaebalSettingsIO:
    _ensure_admin(user)
    from app.services.bot_pause import get_zaebal_settings

    return ZaebalSettingsIO(**(await get_zaebal_settings(session)))


@router.put("/admin/zaebal-settings", response_model=ZaebalSettingsIO)
async def admin_zaebal_put(
    body: ZaebalSettingsIO, session: SessionDep, user: CurrentUser
) -> ZaebalSettingsIO:
    _ensure_admin(user)
    from app.bot.dispatcher import get_bot
    from app.services.bot_pause import set_zaebal_settings

    await set_zaebal_settings(session, body.model_dump())
    await reload_dynamic_jobs(get_bot())
    log.info("admin.zaebal_settings_updated", by=user.id)
    return body


# --- GHG6 E9: реакции бота на @-mention и reply ---


class BotReactionsIO(BaseModel):
    mention_enabled: bool
    reply_all_enabled: bool
    reply_except_phrases_enabled: bool


@router.get("/admin/bot-reactions", response_model=BotReactionsIO)
async def admin_get_bot_reactions(
    session: SessionDep, user: CurrentUser
) -> BotReactionsIO:
    _ensure_admin(user)
    from app.services.admin_config import get_bot_reactions_settings

    cfg = await get_bot_reactions_settings(session)
    return BotReactionsIO(**cfg)


@router.put("/admin/bot-reactions", response_model=BotReactionsIO)
async def admin_put_bot_reactions(
    body: BotReactionsIO, session: SessionDep, user: CurrentUser
) -> BotReactionsIO:
    _ensure_admin(user)
    from app.services.admin_config import set_bot_reactions_settings

    await set_bot_reactions_settings(
        session,
        mention_enabled=body.mention_enabled,
        reply_all_enabled=body.reply_all_enabled,
        reply_except_phrases_enabled=body.reply_except_phrases_enabled,
    )
    log.info("admin.bot_reactions_updated", by=user.id, **body.model_dump())
    return body


# --- GHG6 E10: avatars — разовый sync + одноразовое расписание ---
# Рекуррентный JOB_AVATAR_SYNC упразднён (default avatars.sync_enabled=false).
# Вместо него — две ручные операции: запустить прямо сейчас или запланировать
# на конкретное datetime один раз.

JOB_AVATAR_SYNC_ONE_SHOT = "avatar_sync_one_shot"


class AvatarsSyncNowOut(BaseModel):
    synced: int  # количество пользователей, чьи аватары были запрошены


class AvatarsScheduleOnceIn(BaseModel):
    # ISO 8601 datetime. Принимаем как str, чтобы не зависеть от tz pydantic-парсера —
    # парсим вручную и проверяем «в будущем».
    run_at: str


class AvatarsScheduleOnceOut(BaseModel):
    scheduled: bool
    run_at: datetime | None = None


@router.post("/admin/avatars/sync-now", response_model=AvatarsSyncNowOut)
async def admin_avatars_sync_now(
    session: SessionDep, user: CurrentUser
) -> AvatarsSyncNowOut:
    _ensure_admin(user)
    from app.bot.dispatcher import get_bot
    from app.services.avatars import sync_all_avatars

    count = await sync_all_avatars(session, get_bot())
    log.info("admin.avatars_sync_now", count=count, by=user.id)
    return AvatarsSyncNowOut(synced=count)


def _parse_iso_future(run_at: str) -> datetime:
    try:
        dt = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid_datetime: {e}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "run_at_must_be_future")
    return dt


@router.get("/admin/avatars/schedule-once", response_model=AvatarsScheduleOnceOut)
async def admin_avatars_schedule_once_get(
    user: CurrentUser,
) -> AvatarsScheduleOnceOut:
    _ensure_admin(user)
    sched = get_scheduler()
    job = sched.get_job(JOB_AVATAR_SYNC_ONE_SHOT)
    if job is None or job.next_run_time is None:
        return AvatarsScheduleOnceOut(scheduled=False)
    return AvatarsScheduleOnceOut(scheduled=True, run_at=job.next_run_time)


@router.post("/admin/avatars/schedule-once", response_model=AvatarsScheduleOnceOut)
async def admin_avatars_schedule_once_post(
    body: AvatarsScheduleOnceIn, user: CurrentUser
) -> AvatarsScheduleOnceOut:
    _ensure_admin(user)
    from apscheduler.triggers.date import DateTrigger
    from app.bot.dispatcher import get_bot
    from app.db.base import get_sessionmaker
    from app.services.avatars import sync_all_avatars

    run_dt = _parse_iso_future(body.run_at)

    async def _one_shot() -> None:
        sm = get_sessionmaker()
        async with sm() as session:
            try:
                await sync_all_avatars(session, get_bot())
            except Exception as exc:  # noqa: BLE001
                log.warning("avatars.one_shot_failed", error=str(exc))

    sched = get_scheduler()
    sched.add_job(
        _one_shot,
        DateTrigger(run_date=run_dt),
        id=JOB_AVATAR_SYNC_ONE_SHOT,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("admin.avatars_schedule_once", run_at=run_dt.isoformat(), by=user.id)
    return AvatarsScheduleOnceOut(scheduled=True, run_at=run_dt)


@router.delete("/admin/avatars/schedule-once", response_model=AvatarsScheduleOnceOut)
async def admin_avatars_schedule_once_delete(
    user: CurrentUser,
) -> AvatarsScheduleOnceOut:
    _ensure_admin(user)
    sched = get_scheduler()
    job = sched.get_job(JOB_AVATAR_SYNC_ONE_SHOT)
    if job is not None:
        sched.remove_job(JOB_AVATAR_SYNC_ONE_SHOT)
        log.info("admin.avatars_schedule_once_cancelled", by=user.id)
    return AvatarsScheduleOnceOut(scheduled=False)


# --- GHG6 E6: номинированные игры + голосование ---

class GameNominationOut(BaseModel):
    id: int
    name: str
    added_by_tg_id: int
    added_at: datetime


class GameNominationIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class GameNominationsListOut(BaseModel):
    items: list[GameNominationOut]
    max_active: int


@router.get("/admin/games", response_model=GameNominationsListOut)
async def admin_games_list(
    session: SessionDep, user: CurrentUser
) -> GameNominationsListOut:
    _ensure_admin(user)
    from app.services.games import (
        MAX_ACTIVE_NOMINATIONS,
        list_active_nominations,
    )

    rows = await list_active_nominations(session)
    return GameNominationsListOut(
        items=[
            GameNominationOut(
                id=r.id,
                name=r.name,
                added_by_tg_id=r.added_by_tg_id,
                added_at=r.added_at,
            )
            for r in rows
        ],
        max_active=MAX_ACTIVE_NOMINATIONS,
    )


@router.post(
    "/admin/games", response_model=GameNominationOut, status_code=status.HTTP_201_CREATED
)
async def admin_games_create(
    body: GameNominationIn, session: SessionDep, user: CurrentUser
) -> GameNominationOut:
    _ensure_admin(user)
    from app.services.games import (
        NominationEmpty,
        NominationLimitExceeded,
        add_nomination,
    )

    try:
        row = await add_nomination(
            session, name=body.name, added_by_tg_id=user.telegram_id
        )
    except NominationEmpty as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except NominationLimitExceeded as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    return GameNominationOut(
        id=row.id,
        name=row.name,
        added_by_tg_id=row.added_by_tg_id,
        added_at=row.added_at,
    )


@router.delete("/admin/games/{nomination_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_games_remove(
    nomination_id: int, session: SessionDep, user: CurrentUser
) -> Response:
    _ensure_admin(user)
    from app.services.games import remove_nomination

    removed = await remove_nomination(session, nomination_id=nomination_id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "nomination_not_found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class GamesPollCreateIn(BaseModel):
    """Запуск голосования «Во что сыграем».

    `timeout_hours` — open_period в часах (12..24 по спеке E6.3).
    `nomination_ids` — если пусто, берём все активные номинации.
    `follow_up_when` — если true, после закрытия `game_choice` создаём
    follow-up `game_when` с datetime-вариантами.
    """

    timeout_hours: int = Field(default=24, ge=1, le=72)
    nomination_ids: list[int] | None = None
    follow_up_when: bool = False
    # G2: None → берём дефолт из admin_config (polls.pin_default).
    pin: bool | None = None


class GamesPollCreateOut(BaseModel):
    poll_id: int
    tg_message_id: int | None
    options_count: int
    closes_at: datetime | None
    follow_up_when: bool


@router.post("/admin/games/poll-create", response_model=GamesPollCreateOut)
async def admin_games_poll_create(
    body: GamesPollCreateIn, session: SessionDep, user: CurrentUser
) -> GamesPollCreateOut:
    _ensure_admin(user)
    settings = get_settings()
    if not settings.group_chat_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "group_chat_id_not_configured"
        )
    from app.bot.dispatcher import get_bot
    from app.services.games_poll import GamesPollSendFailed, create_game_choice_poll

    # G2: дефолт pin берём из admin_config, если в теле не указали.
    if body.pin is None:
        from app.services.admin_config import get_polls_pin_default
        pin = await get_polls_pin_default(session)
    else:
        pin = body.pin

    try:
        poll = await create_game_choice_poll(
            session,
            get_bot(),
            chat_id=settings.group_chat_id,
            created_by=user,
            timeout_hours=body.timeout_hours,
            nomination_ids=body.nomination_ids,
            follow_up_when=body.follow_up_when,
            pin=pin,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except GamesPollSendFailed as exc:
        # GHG6 hotfix: прокси/network failed на send_poll — не валим ASGI,
        # отвечаем понятным 503. Фронт показывает alert, пользователь идёт
        # чинить прокси в админке.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"telegram_send_failed:{exc.reason}",
        ) from None

    return GamesPollCreateOut(
        poll_id=poll.id,
        tg_message_id=poll.tg_message_id,
        options_count=len(body.nomination_ids or []),
        closes_at=poll.closes_at,
        follow_up_when=body.follow_up_when,
    )
