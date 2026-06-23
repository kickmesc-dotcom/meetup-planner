from __future__ import annotations
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any
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
    get_phrase_generator_version,
    get_poll_time_presets,
    get_random_phrases_collective_chance,
    get_random_phrases_count,
    get_random_phrases_count_range,
    get_random_phrases_enabled,
    get_random_phrases_lookback_days,
    get_random_phrases_mode,
    get_random_phrases_recency_quarantine_hours,
    get_random_phrases_recency_quarantine_weight,
    get_random_phrases_schedule,
    get_random_phrases_user_chance,
    get_reminders_tick_minutes,
    reset_chukhan_weight,
    set_autoloser_settings,
    set_chukhan_weight,
    set_loser_reasons,
    set_phrase_generator_version,
    set_poll_time_presets,
    set_random_phrases_collective_chance,
    set_random_phrases_count,
    set_random_phrases_count_range,
    set_random_phrases_enabled,
    set_random_phrases_lookback_days,
    set_random_phrases_mode,
    set_random_phrases_recency_quarantine_hours,
    set_random_phrases_recency_quarantine_weight,
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
    reason_text: str | None = None  # GHG8 T1.2

class ChukhanLeaderRow(BaseModel):
    user_id: int
    count: int

class ScheduledJobOut(BaseModel):
    id: str
    kind: str
    label: str
    next_run_at: datetime | None
    detail: str | None = None
    # GHG6 M: тип триггера (для фронта — определять, что писать в reschedule)
    # и редактируемость. Системные job'ы вроде proxy_health не редактируются.
    trigger_kind: str = "interval"  # interval | cron | date | reminder
    editable: bool = True


# GHG6 M: пропускаемые scheduler-job-id (нельзя двигать/отменять руками).
# Это инфраструктурный health-check — он должен идти строго по таймеру.
_NON_EDITABLE_JOB_IDS: frozenset[str] = frozenset({"proxy_health"})


def _classify_trigger(trigger: object) -> str:
    """GHG6 M: текстовое имя для типа APScheduler-триггера.

    Не используем `isinstance` напрямую, чтобы не тащить лишних импортов
    в этот файл — анализируем имя класса.
    """
    name = type(trigger).__name__.lower()
    if "cron" in name:
        return "cron"
    if "interval" in name:
        return "interval"
    if "date" in name:
        return "date"
    return "unknown"

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
    "meeting_feedback_daily": "🌟 5★ опрос по встречам (N2)",
    "space_restart_tick": "🔄 Рестарт Space (тик расписания)",
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
        tkind = _classify_trigger(job.trigger)
        out.append(
            ScheduledJobOut(
                id=job.id,
                kind=tkind,
                label=label,
                next_run_at=job.next_run_time,
                detail=str(job.trigger),
                trigger_kind=tkind,
                editable=job.id not in _NON_EDITABLE_JOB_IDS,
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
                trigger_kind="reminder",
                editable=True,
            )
        )
    return out

# GHG6 M: ручное управление scheduler-jobs (reschedule + skip-next).
#
# Решения по семантике (по п.17):
# - reschedule на конкретное время — только для editable APScheduler-jobs
#   и reminder:<id>. Системные job'ы из _NON_EDITABLE_JOB_IDS отказывают 400.
# - cancel = «пропустить ближайший запуск», НЕ удаление job'а:
#   * Для recurring (interval/cron) → next_run_time = trigger.get_next_fire_time
#     после now + epsilon (1 сек), что даёт следующий цикл и пропускает текущий.
#   * Для one-shot (date) → действительно удаляем job из планировщика.
#   * Для reminder → выставляем sent_at=now (старая семантика).
# - reload_dynamic_jobs НЕ зовём — это сбросило бы все ручные правки и
#   собрало бы расписание заново.


class JobRescheduleIn(BaseModel):
    """GHG6 M: тело для POST /admin/jobs/{id}/reschedule.

    `run_at` всегда в UTC ISO; фронт переводит из локального времени.
    """

    run_at: datetime


@router.post("/admin/jobs/{job_id:path}/reschedule", response_model=ScheduledJobOut)
async def reschedule_job(
    job_id: str,
    body: JobRescheduleIn,
    session: SessionDep,
    user: CurrentUser,
) -> ScheduledJobOut:
    """GHG6 M2: подвинуть `next_run_time` job'а на указанный момент."""
    _ensure_admin(user)
    run_at = body.run_at
    if run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=timezone.utc)

    if job_id.startswith("reminder:"):
        try:
            rem_id = int(job_id.split(":", 1)[1])
        except (ValueError, IndexError) as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad_job_id") from e
        rem = await session.get(MeetingReminder, rem_id)
        if rem is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "reminder_not_found")
        if rem.sent_at is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "reminder_already_sent")
        rem.due_at = run_at
        await session.commit()
        meeting = await session.get(Meeting, rem.meeting_id)
        meeting_title = meeting.title if meeting else "?"
        log.info(
            "admin.reminder_rescheduled",
            reminder_id=rem_id,
            run_at=run_at.isoformat(),
            by=user.id,
        )
        return ScheduledJobOut(
            id=job_id,
            kind="reminder",
            label=f"📅 «{meeting_title}» (-{rem.offset_minutes} мин)",
            next_run_at=rem.due_at,
            detail=f"meeting_id={rem.meeting_id}",
            trigger_kind="reminder",
            editable=True,
        )

    if job_id in _NON_EDITABLE_JOB_IDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "system_job_not_editable")

    sched = get_scheduler()
    job = sched.get_job(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job_not_found")
    try:
        sched.modify_job(job_id, next_run_time=run_at)
    except Exception as e:  # noqa: BLE001 — APScheduler не специфичен
        log.warning("admin.job_reschedule_failed", job_id=job_id, error=str(e))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "modify_failed") from e
    log.info("admin.job_rescheduled", job_id=job_id, run_at=run_at.isoformat(), by=user.id)
    job = sched.get_job(job_id)
    tkind = _classify_trigger(job.trigger) if job else "unknown"
    label = (
        f"💬 Автопост фраз (доп. {job_id.rsplit(':', 1)[-1]})"
        if job_id.startswith("random_phrases:extra:")
        else _JOB_LABELS.get(job_id, job_id)
    )
    return ScheduledJobOut(
        id=job_id,
        kind=tkind,
        label=label,
        next_run_at=job.next_run_time if job else None,
        detail=str(job.trigger) if job else None,
        trigger_kind=tkind,
        editable=True,
    )


@router.delete(
    "/admin/jobs/{job_id:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def cancel_job(
    job_id: str,
    session: SessionDep,
    user: CurrentUser,
):
    """GHG6 M3: пропустить ближайший запуск (для recurring) / удалить (one-shot).

    Семантика см. шапку секции — НЕ совпадает с «delete job» в классическом
    APScheduler, потому что recurring-job нам нужно сохранить (он автоматически
    пересоберётся через reload_dynamic_jobs при следующей правке настроек).
    """
    _ensure_admin(user)
    if job_id.startswith("reminder:"):
        try:
            rem_id = int(job_id.split(":", 1)[1])
        except (ValueError, IndexError) as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad_job_id") from e
        rem = await session.get(MeetingReminder, rem_id)
        if rem is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "reminder_not_found")
        if rem.sent_at is not None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        rem.sent_at = datetime.now(timezone.utc)
        await session.commit()
        log.info("admin.reminder_cancelled", reminder_id=rem_id, by=user.id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if job_id in _NON_EDITABLE_JOB_IDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "system_job_not_cancellable")

    sched = get_scheduler()
    job = sched.get_job(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job_not_found")
    tkind = _classify_trigger(job.trigger)
    if tkind == "date":
        # One-shot — действительно удаляем (DateTrigger всё равно выстрелит один раз).
        sched.remove_job(job_id)
        log.info("admin.job_removed_oneshot", job_id=job_id, by=user.id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # Recurring (cron/interval) — пропускаем ближайший запуск.
    # `get_next_fire_time(prev, now)` у APScheduler-триггеров возвращает
    # следующее время после `now`. Берём now+1сек, чтобы текущий запуск
    # (если он на now) был пропущен.
    from datetime import timedelta as _td
    now = datetime.now(timezone.utc)
    try:
        next_fire = job.trigger.get_next_fire_time(None, now + _td(seconds=1))
    except Exception as e:  # noqa: BLE001
        log.warning("admin.job_skip_next_failed", job_id=job_id, error=str(e))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "skip_next_failed") from e
    if next_fire is None:
        # Триггер исчерпан — просто удалим job.
        sched.remove_job(job_id)
        log.info("admin.job_removed_exhausted", job_id=job_id, by=user.id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    sched.modify_job(job_id, next_run_time=next_fire)
    log.info(
        "admin.job_next_skipped",
        job_id=job_id,
        new_next_run_at=next_fire.isoformat(),
        by=user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

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


# --- GHG7 P0.3: debug-снимок копилки (ВСЕ записи, без cutoff) ---
#
# Жалоба GHG7 стр.4: счётчики фраз в админ-UI обнулились/упали (140+ → 63),
# у активного юзера висит 0. Эндпоинт ниже отдаёт сырьё для разбора:
# total_messages по юзеру без cutoff (т.е. что физически лежит в БД),
# last_sent_at (старая запись = чистка отъела), messages_within_lookback
# (то, что попадает в /pool). Расхождение total vs within_lookback
# показывает, режет ли TTL-чистка слишком много; large total + 0 в
# within_lookback при «вчера активный» = баг TZ/cutoff; малый total
# при «много писал» = не записывается на входе (whitelist/тип сообщения).
#
# Безопасный read-only эндпоинт под админ-токеном.


class RandomPhrasesPoolRawRow(BaseModel):
    user_id: int
    telegram_id: int
    display_name: str
    total_messages: int
    last_sent_at: datetime | None
    messages_within_lookback: int


class RandomPhrasesPoolRawOut(BaseModel):
    server_now_utc: datetime
    lookback_days: int
    cutoff_used_utc: datetime
    total_messages_in_db: int
    total_within_lookback: int
    rows: list[RandomPhrasesPoolRawRow]


@router.get(
    "/admin/random-phrases/pool/raw",
    response_model=RandomPhrasesPoolRawOut,
)
async def get_rp_pool_raw(
    session: SessionDep, user: CurrentUser
) -> RandomPhrasesPoolRawOut:
    _ensure_admin(user)
    from app.db.models import ChatMessage as _CM

    lookback_days = await get_random_phrases_lookback_days(session)
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=lookback_days)

    # Агрегаты по юзеру без cutoff'a — что физически лежит в БД.
    total_rows = list((await session.execute(
        select(
            _CM.user_id,
            func.count().label("total"),
            func.max(_CM.sent_at).label("last_sent_at"),
        ).group_by(_CM.user_id)
    )).all())
    totals_by_uid: dict[int, tuple[int, datetime | None]] = {}
    grand_total = 0
    for uid, cnt, last in total_rows:
        if uid is None:
            continue
        totals_by_uid[int(uid)] = (int(cnt), last)
        grand_total += int(cnt)

    # Агрегаты внутри окна.
    win_rows = list((await session.execute(
        select(_CM.user_id, func.count())
        .where(_CM.sent_at >= cutoff)
        .group_by(_CM.user_id)
    )).all())
    win_by_uid: dict[int, int] = {
        int(uid): int(cnt) for uid, cnt in win_rows if uid is not None
    }
    win_total = sum(win_by_uid.values())

    users = (await session.scalars(select(User).order_by(User.id))).all()
    out_rows = []
    for u in users:
        total_cnt, last_at = totals_by_uid.get(u.id, (0, None))
        out_rows.append(
            RandomPhrasesPoolRawRow(
                user_id=u.id,
                telegram_id=u.telegram_id,
                display_name=u.display_name,
                total_messages=total_cnt,
                last_sent_at=last_at,
                messages_within_lookback=win_by_uid.get(u.id, 0),
            )
        )
    # Сортировка по «вкладу в БД» убывая, потом по имени.
    out_rows.sort(key=lambda r: (-r.total_messages, r.display_name))

    return RandomPhrasesPoolRawOut(
        server_now_utc=now_utc,
        lookback_days=lookback_days,
        cutoff_used_utc=cutoff,
        total_messages_in_db=grand_total,
        total_within_lookback=win_total,
        rows=out_rows,
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


# --- N2: master-toggle и история feedback-опросов ---


class MeetingFeedbackSettingsIO(BaseModel):
    """GHG6 N2: настройки feedback-опроса по встречам.

    `enabled` — master-toggle scheduler-job'а. Поднимается → перерегистрируется
    job (см. PUT-handler с reload_dynamic_jobs).
    `notify_absence` — публиковать ли тост «@user пропустил встречу +0.5».
    `absence_weight_delta` — насколько поднимать вес. Default +0.5 как в п.18.
    """

    enabled: bool
    notify_absence: bool
    absence_weight_delta: float = Field(..., ge=0.0, le=5.0)


@router.get("/admin/meeting-feedback", response_model=MeetingFeedbackSettingsIO)
async def get_meeting_feedback_settings(
    session: SessionDep,
    user: CurrentUser,
) -> MeetingFeedbackSettingsIO:
    _ensure_admin(user)
    from app.services.admin_config import (
        get_meeting_feedback_absence_weight,
        get_meeting_feedback_enabled,
        get_meeting_feedback_notify_absence,
    )

    return MeetingFeedbackSettingsIO(
        enabled=await get_meeting_feedback_enabled(session),
        notify_absence=await get_meeting_feedback_notify_absence(session),
        absence_weight_delta=await get_meeting_feedback_absence_weight(session),
    )


@router.put("/admin/meeting-feedback", response_model=MeetingFeedbackSettingsIO)
async def put_meeting_feedback_settings(
    body: MeetingFeedbackSettingsIO,
    session: SessionDep,
    user: CurrentUser,
) -> MeetingFeedbackSettingsIO:
    _ensure_admin(user)
    from app.services.admin_config import (
        set_meeting_feedback_absence_weight,
        set_meeting_feedback_enabled,
        set_meeting_feedback_notify_absence,
    )

    await set_meeting_feedback_enabled(session, body.enabled)
    await set_meeting_feedback_notify_absence(session, body.notify_absence)
    await set_meeting_feedback_absence_weight(session, body.absence_weight_delta)
    # Перерегистрируем scheduler-job при изменении enabled.
    from app.bot.dispatcher import get_bot

    await reload_dynamic_jobs(get_bot())
    log.info("admin.meeting_feedback_updated", **body.model_dump(), by=user.id)
    return body


class MeetingFeedbackRow(BaseModel):
    """История 5★-оценок встречи. Группируется по meeting_id на фронте."""

    meeting_id: int
    meeting_title: str
    meeting_starts_at: datetime
    user_id: int
    display_name: str | None
    rating: int | None
    was_absent: bool
    reason_text: str | None
    created_at: datetime


@router.get("/admin/meeting-feedback/history", response_model=list[MeetingFeedbackRow])
async def get_meeting_feedback_history(
    session: SessionDep,
    user: CurrentUser,
    limit: int = 50,
) -> list[MeetingFeedbackRow]:
    """N2.5: история оценок последних N встреч. Лимит ограничен 200 сверху."""
    _ensure_admin(user)
    from app.db.models import MeetingFeedback

    cap = max(1, min(limit, 200))
    rows = list(
        (
            await session.execute(
                select(
                    MeetingFeedback,
                    Meeting.title,
                    Meeting.starts_at,
                    User.display_name,
                )
                .join(Meeting, Meeting.id == MeetingFeedback.meeting_id)
                .join(User, User.id == MeetingFeedback.user_id)
                .order_by(desc(MeetingFeedback.created_at))
                .limit(cap)
            )
        ).all()
    )
    out: list[MeetingFeedbackRow] = []
    for fb, m_title, m_starts, u_name in rows:
        out.append(
            MeetingFeedbackRow(
                meeting_id=fb.meeting_id,
                meeting_title=m_title,
                meeting_starts_at=m_starts,
                user_id=fb.user_id,
                display_name=u_name,
                rating=fb.rating,
                was_absent=fb.was_absent,
                reason_text=fb.reason_text,
                created_at=fb.created_at,
            )
        )
    return out


# --- N1: история опросов / игр (исходник п.18) ---
#
# Чисто чтение. Возвращаем последние N опросов с раскрытыми опциями и голосами.
# Без новых таблиц — данные из polls / poll_options / poll_votes.


class PollHistoryVote(BaseModel):
    user_id: int
    display_name: str | None = None
    voted_at: datetime


class PollHistoryOption(BaseModel):
    id: int
    label: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    votes: list[PollHistoryVote]


class PollHistoryRow(BaseModel):
    poll_id: int
    kind: str | None
    question: str
    created_by: int
    created_at: datetime
    closes_at: datetime | None
    closed: bool
    tg_message_id: int | None
    # Для game_when poll — id связанной номинации (чтобы фронт мог показать
    # «Какая игра была»). Для остальных типов — None.
    game_nomination_id: int | None = None
    options: list[PollHistoryOption]


async def _build_poll_history(
    session, *, kinds: list[str] | None = None, limit: int = 30
) -> list[PollHistoryRow]:
    """Чистая функция: достать последние N опросов с join'ами по опциям и голосам.

    Не делаем отдельных подзапросов на каждый poll — один SELECT для опций
    и один для голосов, потом группируем в Python. Это держит endpoint
    дёшевым даже на большой истории.
    """
    poll_stmt = select(Poll).order_by(desc(Poll.created_at)).limit(limit)
    if kinds:
        poll_stmt = poll_stmt.where(Poll.kind.in_(kinds))
    polls: list[Poll] = list((await session.scalars(poll_stmt)).all())
    if not polls:
        return []
    poll_ids = [p.id for p in polls]

    from app.db.models import PollOption, PollVote

    option_rows: list[PollOption] = list(
        (
            await session.scalars(
                select(PollOption).where(PollOption.poll_id.in_(poll_ids))
            )
        ).all()
    )
    by_poll: dict[int, list[PollOption]] = {}
    for opt in option_rows:
        by_poll.setdefault(opt.poll_id, []).append(opt)

    option_ids = [opt.id for opt in option_rows]
    votes_by_opt: dict[int, list[tuple[int, datetime]]] = {}
    voter_ids: set[int] = set()
    if option_ids:
        vote_rows = list(
            (
                await session.execute(
                    select(PollVote.poll_option_id, PollVote.user_id, PollVote.voted_at).where(
                        PollVote.poll_option_id.in_(option_ids)
                    )
                )
            ).all()
        )
        for opt_id, uid, voted_at in vote_rows:
            votes_by_opt.setdefault(opt_id, []).append((uid, voted_at))
            voter_ids.add(uid)

    name_by_uid: dict[int, str] = {}
    if voter_ids:
        user_rows = list(
            (
                await session.execute(
                    select(User.id, User.display_name).where(User.id.in_(voter_ids))
                )
            ).all()
        )
        name_by_uid = {uid: name for uid, name in user_rows}

    out: list[PollHistoryRow] = []
    for p in polls:
        options_out: list[PollHistoryOption] = []
        for opt in by_poll.get(p.id, []):
            options_out.append(
                PollHistoryOption(
                    id=opt.id,
                    label=opt.label,
                    starts_at=opt.starts_at,
                    ends_at=opt.ends_at,
                    votes=[
                        PollHistoryVote(
                            user_id=uid,
                            display_name=name_by_uid.get(uid),
                            voted_at=voted_at,
                        )
                        for uid, voted_at in votes_by_opt.get(opt.id, [])
                    ],
                )
            )
        out.append(
            PollHistoryRow(
                poll_id=p.id,
                kind=p.kind,
                question=p.question,
                created_by=p.created_by,
                created_at=p.created_at,
                closes_at=p.closes_at,
                closed=bool(p.is_closed),
                tg_message_id=p.tg_message_id,
                game_nomination_id=p.game_nomination_id,
                options=options_out,
            )
        )
    return out


@router.get("/admin/polls/history", response_model=list[PollHistoryRow])
async def admin_polls_history(
    session: SessionDep,
    user: CurrentUser,
    limit: int = 30,
) -> list[PollHistoryRow]:
    """N1.1: последние N опросов любого типа с раскрытыми опциями/голосами.

    Не фильтруем по kind — это полная история. Лимит ограничен сверху 200,
    чтобы не отдавать всю таблицу.
    """
    _ensure_admin(user)
    return await _build_poll_history(session, limit=max(1, min(limit, 200)))


@router.get("/admin/games/history", response_model=list[PollHistoryRow])
async def admin_games_history(
    session: SessionDep,
    user: CurrentUser,
    limit: int = 30,
) -> list[PollHistoryRow]:
    """N1.2: история игровых опросов (`kind in ('game_choice','game_when')`).

    Возвращает тот же `PollHistoryRow`, что и /admin/polls/history. Поле
    `game_nomination_id` имеет смысл только для `game_when` — фронт по нему
    может подтянуть имя игры через /admin/games (если номинация ещё жива).
    """
    _ensure_admin(user)
    return await _build_poll_history(
        session, kinds=["game_choice", "game_when"], limit=max(1, min(limit, 200))
    )


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
from app.services.admin_config import (
    CHUKHAN_REASONS_KEY as _CHUKHAN_REASONS_KEY,
    _DEFAULT_CHUKHAN_REASONS,
    _get_value as _admin_get_value,
)


class ChukhanReasonsOut(BaseModel):
    reasons: list[str]


class ChukhanReasonsUpdate(BaseModel):
    reasons: list[str] = Field(..., max_length=500)


class ChukhanReasonsRaw(BaseModel):
    """GHG8 Q5: диагностика расхождения «правлю Neon, а в приложении 6 фраз».

    Показывает что РЕАЛЬНО лежит в admin_config под ключом chukhan_reasons.list
    и как это парсится. Если `key_present=false` — правка пользователя легла не
    под этот ключ. Если `parsed_count` падает к 6 при непустом `raw_value` —
    значит JSON невалиден и сработал тихий фолбэк на дефолт (см. логи
    chukhan_reasons.fallback_default)."""

    key: str
    key_present: bool
    raw_value: str | None
    raw_len: int
    parse_ok: bool
    parsed_count: int
    using_default: bool
    default_count: int


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


@router.get("/admin/chukhan-reasons/raw", response_model=ChukhanReasonsRaw)
async def admin_get_chukhan_reasons_raw(
    session: SessionDep, user: CurrentUser
) -> ChukhanReasonsRaw:
    """GHG8 Q5: диагностика «почему в приложении 6 старых причин чухана».

    Read-only. Возвращает сырое значение ключа из admin_config + результат
    парсинга, чтобы отличить «ключ не тот» от «невалидный JSON → фолбэк»."""
    _ensure_admin(user)
    raw = await _admin_get_value(session, _CHUKHAN_REASONS_KEY)
    parse_ok = False
    parsed_count = 0
    if raw is not None:
        try:
            data = json.loads(raw)
            if isinstance(data, list) and all(isinstance(x, str) for x in data):
                parse_ok = True
                parsed_count = len(data)
        except (ValueError, TypeError):
            parse_ok = False
    effective = await _get_chukhan_reasons(session)
    using_default = list(effective) == list(_DEFAULT_CHUKHAN_REASONS)
    return ChukhanReasonsRaw(
        key=_CHUKHAN_REASONS_KEY,
        key_present=raw is not None,
        raw_value=raw,
        raw_len=len(raw) if raw is not None else 0,
        parse_ok=parse_ok,
        parsed_count=parsed_count,
        using_default=using_default,
        default_count=len(_DEFAULT_CHUKHAN_REASONS),
    )


@router.post("/admin/chukhan-reasons/reset", response_model=ChukhanReasonsOut)
async def admin_reset_chukhan_reasons(
    session: SessionDep, user: CurrentUser
) -> ChukhanReasonsOut:
    """GHG8 Q5: перезаписать причины чухана дефолтами из кода.

    Чинит кейс «в Neon лежит кривой/пустой ключ → тихий фолбэк на 6 старых
    фраз, правки не применяются». Кнопка в админ-UI пишет валидный JSON через
    `set_chukhan_reasons`, гарантированно вытесняя битое значение."""
    _ensure_admin(user)
    await _set_chukhan_reasons(session, list(_DEFAULT_CHUKHAN_REASONS))
    saved = await _get_chukhan_reasons(session)
    log.info("admin.chukhan_reasons_reset", count=len(saved), by=user.id)
    return ChukhanReasonsOut(reasons=saved)


# --- T3.4: advice («магический шар») ---

from app.services.admin_config import (
    get_advice_enabled as _get_advice_enabled,
    set_advice_enabled as _set_advice_enabled,
    get_advice_phrases as _get_advice_phrases,
    set_advice_phrases as _set_advice_phrases,
)


class AdviceOut(BaseModel):
    enabled: bool
    phrases: list[str]


class AdvicePhrasesUpdate(BaseModel):
    phrases: list[str] = Field(..., max_length=500)


class AdviceEnabledUpdate(BaseModel):
    enabled: bool


@router.get("/admin/advice", response_model=AdviceOut)
async def admin_get_advice(session: SessionDep, user: CurrentUser) -> AdviceOut:
    _ensure_admin(user)
    return AdviceOut(
        enabled=await _get_advice_enabled(session),
        phrases=await _get_advice_phrases(session),
    )


@router.put("/admin/advice/phrases", response_model=AdviceOut)
async def admin_update_advice_phrases(
    body: AdvicePhrasesUpdate, session: SessionDep, user: CurrentUser
) -> AdviceOut:
    _ensure_admin(user)
    await _set_advice_phrases(session, body.phrases)
    saved = await _get_advice_phrases(session)
    log.info("admin.advice_phrases_updated", count=len(saved), by=user.id)
    return AdviceOut(enabled=await _get_advice_enabled(session), phrases=saved)


@router.put("/admin/advice/enabled", response_model=AdviceOut)
async def admin_update_advice_enabled(
    body: AdviceEnabledUpdate, session: SessionDep, user: CurrentUser
) -> AdviceOut:
    _ensure_admin(user)
    await _set_advice_enabled(session, body.enabled)
    log.info("admin.advice_enabled_updated", enabled=body.enabled, by=user.id)
    return AdviceOut(
        enabled=await _get_advice_enabled(session),
        phrases=await _get_advice_phrases(session),
    )


# --- T3.1: снапшот/экспорт базы причин-реакций ---

from app.services.phrase_snapshot import (
    apply_snapshot as _apply_snapshot,
    build_snapshot as _build_snapshot,
    validate_snapshot as _validate_snapshot,
)


class PhraseSnapshotImport(BaseModel):
    snapshot: dict[str, Any]
    mode: str = Field("replace", pattern="^(replace|merge)$")


@router.get("/admin/phrases/snapshot")
async def admin_get_phrases_snapshot(
    session: SessionDep, user: CurrentUser
) -> dict[str, Any]:
    """T3.1: полный снапшот всех редактируемых пулов фраз + use_counts +
    персонажей. Фронт даёт скопировать/скачать как страховку от потери."""
    _ensure_admin(user)
    snap = await _build_snapshot(session)
    log.info(
        "admin.phrases_snapshot_built",
        pools={k: len(v) for k, v in snap["pools"].items()},
        personas=len(snap["personas"]),
        by=user.id,
    )
    return snap


@router.post("/admin/phrases/snapshot/import")
async def admin_import_phrases_snapshot(
    body: PhraseSnapshotImport, session: SessionDep, user: CurrentUser
) -> dict[str, Any]:
    """T3.1: залить снапшот обратно. mode=replace перезаписывает пулы, merge —
    дописывает без дублей. Возвращает summary по каждому пулу/персонажам."""
    _ensure_admin(user)
    ok, err = _validate_snapshot(body.snapshot)
    if not ok:
        raise HTTPException(status_code=422, detail=f"невалидный снапшот: {err}")
    summary = await _apply_snapshot(session, body.snapshot, mode=body.mode)
    log.info("admin.phrases_snapshot_imported", summary=summary, by=user.id)
    return summary


# --- T3.3: алёрты «лох/чухан не запостился» ---

from app.services.posting_alerts import get_posting_alerts as _get_posting_alerts


@router.get("/admin/posting-alerts")
async def admin_posting_alerts(
    session: SessionDep, user: CurrentUser
) -> dict[str, Any]:
    """T3.3: read-only сводка терминально-незапостившихся лох/чухан.

    ⚠️ Только SELECT (loser_outbox/weekly_chukhan), никаких записей. outbox лоха
    не трогаем — лишь показываем expired-строки. Обычно total=0."""
    _ensure_admin(user)
    return await _get_posting_alerts(session)


@router.post("/admin/posting-alerts/chukhan-retry")
async def admin_posting_alerts_chukhan_retry(
    session: SessionDep, user: CurrentUser
) -> dict[str, Any]:
    """T3.3: дослать недоставленного чухана текущей недели. Зовёт СУЩЕСТВУЮЩУЮ
    `retry_undelivered_chukhan` (тот же штатный путь, что job каждые 30 мин;
    без «алерта в чат что вручную»). Перепрогона лоха здесь НЕТ — его outbox
    работает сам и его мы не трогаем."""
    _ensure_admin(user)
    from app.bot.dispatcher import get_bot
    from app.services.chukhan import retry_undelivered_chukhan

    delivered = await retry_undelivered_chukhan(get_bot())
    log.info("admin.posting_alerts_chukhan_retry", delivered=delivered, by=user.id)
    return {"delivered": delivered}


# --- GHG7 P5: реакции бота на медиа (пулы фраз single/collection + эмодзи) ---

from app.services.media_reactions import (
    get_single_phrases as _get_single_phrases,
    set_single_phrases as _set_single_phrases,
    get_collection_phrases as _get_collection_phrases,
    set_collection_phrases as _set_collection_phrases,
    get_emoji_whitelist as _get_emoji_whitelist,
    set_emoji_whitelist as _set_emoji_whitelist,
)
from app.services.admin_config import (
    get_media_reactions_settings as _get_media_settings,
    set_media_reactions_settings as _set_media_settings,
)


class MediaPhrasesOut(BaseModel):
    phrases: list[str]


class MediaPhrasesUpdate(BaseModel):
    phrases: list[str] = Field(..., max_length=500)


class MediaEmojiWhitelistOut(BaseModel):
    """Ответ сохранения emoji-whitelist: что реально записано + что отброшено
    как неподдерживаемая TG-реакция (п.15: показать админу, а не глотать молча)."""
    phrases: list[str]
    rejected: list[str] = []


@router.get("/admin/media-reactions/single-phrases", response_model=MediaPhrasesOut)
async def admin_get_media_single_phrases(
    session: SessionDep, user: CurrentUser
) -> MediaPhrasesOut:
    _ensure_admin(user)
    return MediaPhrasesOut(phrases=await _get_single_phrases(session))


@router.put("/admin/media-reactions/single-phrases", response_model=MediaPhrasesOut)
async def admin_update_media_single_phrases(
    body: MediaPhrasesUpdate, session: SessionDep, user: CurrentUser
) -> MediaPhrasesOut:
    _ensure_admin(user)
    await _set_single_phrases(session, body.phrases)
    saved = await _get_single_phrases(session)
    log.info("admin.media_single_phrases_updated", count=len(saved), by=user.id)
    return MediaPhrasesOut(phrases=saved)


@router.get("/admin/media-reactions/collection-phrases", response_model=MediaPhrasesOut)
async def admin_get_media_collection_phrases(
    session: SessionDep, user: CurrentUser
) -> MediaPhrasesOut:
    _ensure_admin(user)
    return MediaPhrasesOut(phrases=await _get_collection_phrases(session))


@router.put("/admin/media-reactions/collection-phrases", response_model=MediaPhrasesOut)
async def admin_update_media_collection_phrases(
    body: MediaPhrasesUpdate, session: SessionDep, user: CurrentUser
) -> MediaPhrasesOut:
    _ensure_admin(user)
    await _set_collection_phrases(session, body.phrases)
    saved = await _get_collection_phrases(session)
    log.info("admin.media_collection_phrases_updated", count=len(saved), by=user.id)
    return MediaPhrasesOut(phrases=saved)


@router.get("/admin/media-reactions/emoji-whitelist", response_model=MediaPhrasesOut)
async def admin_get_media_emoji_whitelist(
    session: SessionDep, user: CurrentUser
) -> MediaPhrasesOut:
    _ensure_admin(user)
    return MediaPhrasesOut(phrases=await _get_emoji_whitelist(session))


@router.put(
    "/admin/media-reactions/emoji-whitelist", response_model=MediaEmojiWhitelistOut
)
async def admin_update_media_emoji_whitelist(
    body: MediaPhrasesUpdate, session: SessionDep, user: CurrentUser
) -> MediaEmojiWhitelistOut:
    _ensure_admin(user)
    rejected = await _set_emoji_whitelist(session, body.phrases)
    saved = await _get_emoji_whitelist(session)
    log.info(
        "admin.media_emoji_whitelist_updated",
        count=len(saved),
        rejected=len(rejected),
        by=user.id,
    )
    return MediaEmojiWhitelistOut(phrases=saved, rejected=rejected)


class MediaReactionsSettingsIO(BaseModel):
    enabled: bool
    single_enabled: bool
    collection_enabled: bool
    mode: str  # always|chance|wait_then_chance|never
    chance_pct: int = Field(..., ge=0, le=100)  # один честный ролл на мем
    wait_window_min: int = Field(..., ge=1, le=360)  # грейс-окно wait_then_chance
    single_response_mode: str  # emoji|phrase|both|random_one


@router.get("/admin/media-reactions/settings", response_model=MediaReactionsSettingsIO)
async def admin_get_media_settings(
    session: SessionDep, user: CurrentUser
) -> MediaReactionsSettingsIO:
    _ensure_admin(user)
    return MediaReactionsSettingsIO(**await _get_media_settings(session))


@router.put("/admin/media-reactions/settings", response_model=MediaReactionsSettingsIO)
async def admin_update_media_settings(
    body: MediaReactionsSettingsIO, session: SessionDep, user: CurrentUser
) -> MediaReactionsSettingsIO:
    _ensure_admin(user)
    await _set_media_settings(
        session,
        enabled=body.enabled,
        single_enabled=body.single_enabled,
        collection_enabled=body.collection_enabled,
        mode=body.mode,
        chance_pct=body.chance_pct,
        wait_window_min=body.wait_window_min,
        single_response_mode=body.single_response_mode,
    )
    saved = await _get_media_settings(session)
    log.info("admin.media_settings_updated", by=user.id)
    return MediaReactionsSettingsIO(**saved)


class MediaForceOut(BaseModel):
    ok: bool
    message_id: int


@router.post("/admin/media-reactions/force/{kind}", response_model=MediaForceOut)
async def admin_media_force_react(
    kind: str, session: SessionDep, user: CurrentUser
) -> MediaForceOut:
    """P5.5: принудительно отреагировать на последний мем/подборку в группе.

    Берёт последнее сохранённое медиа нужного типа: сперва in-memory store
    handler'а, при промахе — persist из admin_config (GHG8 Q7.b: in-memory
    обнуляется при рестарте Space, БД-копия переживает). Если нет нигде —
    404 `no_recent_media` (Q7.c: фронт показывает человечный текст). Реагирует
    немедленно, без серии/проверки шанса. Импорт handler'а ленивый — не тащим
    aiogram в роуты на импорте модуля."""
    _ensure_admin(user)
    if kind not in {"single", "collection"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad_kind")
    group_chat_id = get_settings().group_chat_id
    if not group_chat_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no_group_chat_id")

    from app.bot.handlers.media_reactions import get_recent, react_now
    from app.services.media_reactions import get_recent_media_persisted

    recent = get_recent(group_chat_id, kind)  # type: ignore[arg-type]
    if recent is None:
        # Q7.b: фолбэк на персистнутую запись (рестарт Space стёр in-memory).
        recent = await get_recent_media_persisted(session, group_chat_id, kind)  # type: ignore[arg-type]
    if recent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no_recent_media")
    message_id, author_name = recent
    await react_now(kind, group_chat_id, message_id, author_name)  # type: ignore[arg-type]
    log.info("admin.media_force_react", kind=kind, message_id=message_id, by=user.id)
    return MediaForceOut(ok=True, message_id=message_id)


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
    set_one_use_count,
)


class ReasonUseCountsOut(BaseModel):
    """Словарь `{phrase: count}` для всех актуальных фраз. Фразы без записи
    в счётчиках попадают со значением 0 — фронту не надо угадывать.
    """
    counts: dict[str, int]


class ReasonUseCountsCleared(BaseModel):
    cleared: int


class ReasonUseCountSet(BaseModel):
    """Точечная правка счётчика одной фразы из админки. `count=0` — сброс."""
    phrase: str
    count: int = Field(..., ge=0)


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


@router.put(
    "/admin/loser-reasons/use-counts", response_model=ReasonUseCountsOut
)
async def admin_set_loser_reason_use_count(
    payload: ReasonUseCountSet, session: SessionDep, user: CurrentUser
) -> ReasonUseCountsOut:
    _ensure_admin(user)
    await set_one_use_count(
        session, LOSER_USE_COUNTS_KEY, payload.phrase, payload.count
    )
    await session.commit()
    log.info(
        "admin.loser_reason_use_count_set", count=payload.count, by=user.id
    )
    reasons = await get_loser_reasons(session)
    counts = await get_use_counts(session, LOSER_USE_COUNTS_KEY)
    return ReasonUseCountsOut(counts=await _merge_counts_by_phrase(reasons, counts))


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


@router.put(
    "/admin/chukhan-reasons/use-counts", response_model=ReasonUseCountsOut
)
async def admin_set_chukhan_reason_use_count(
    payload: ReasonUseCountSet, session: SessionDep, user: CurrentUser
) -> ReasonUseCountsOut:
    _ensure_admin(user)
    await set_one_use_count(
        session, CHUKHAN_USE_COUNTS_KEY, payload.phrase, payload.count
    )
    await session.commit()
    log.info(
        "admin.chukhan_reason_use_count_set", count=payload.count, by=user.id
    )
    reasons = await _get_chukhan_reasons(session)
    counts = await get_use_counts(session, CHUKHAN_USE_COUNTS_KEY)
    return ReasonUseCountsOut(counts=await _merge_counts_by_phrase(reasons, counts))


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
    # GHG8 P3: режим иммунитета именинника. Дефолт — чтобы старые клиенты
    # (не присылающие поле) не сбрасывали настройку.
    immunity_mode: Literal["announce", "silent"] = "announce"


class ScheduledChukhanIO(BaseModel):
    weekday: int = Field(..., ge=0, le=6)
    window_start: str
    window_end: str


class ScheduledDeadChatIO(BaseModel):
    # GHG8 P7: «мёртвый чат» — пост при долгой тишине (пороги 24ч…год).
    enabled: bool = True


class ScheduledSettingsIO(BaseModel):
    reminders: ScheduledRemindersIO
    loser: ScheduledLoserIO
    phrases: ScheduledPhrasesIO
    avatars: ScheduledAvatarsIO
    birthdays: ScheduledBirthdaysIO
    chukhan: ScheduledChukhanIO
    # GHG8 P7: дефолт — чтобы старые клиенты (не присылающие блок) не падали
    # на валидации и не сбрасывали настройку (set_* пишет только присланное —
    # но default_factory даёт {"enabled": True}; см. примечание в admin_config).
    dead_chat: ScheduledDeadChatIO = Field(default_factory=ScheduledDeadChatIO)


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
        # GHG8 P3: оглашение «черновых» именинников (announce-режим).
        if extras is not None and getattr(extras, "immunity_skipped", None):
            from app.services.birthday_immunity import announce_immunity_skips

            await announce_immunity_skips(
                bot, settings.group_chat_id, extras.immunity_skipped
            )
        try:
            await bot.send_message(
                chat_id=settings.group_chat_id,
                text=compose_loser_message(
                    loser_name=loser.display_name,
                    reason_text=roll.reason_text or "",
                    roller_name=user.display_name,
                    extras=extras,
                    # GHG7 P9.1.c: admin force-reroll = тихий прокрут «лоха дня»
                    # (👑), source остаётся "manual" → идёт в статистику/титулы.
                    header_emoji="👑",
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
    # P13: карантин свежести — сообщения младше N часов почти не цитируются.
    recency_quarantine_hours: float = Field(18.0, ge=0.0, le=168.0)
    recency_quarantine_weight: float = Field(0.05, ge=0.0, le=1.0)
    # GHG8 P6.3: версия генератора — legacy (нарезка v1) | personas (типажи v2).
    generator_version: str = Field("legacy", pattern="^(legacy|personas)$")


class GeneratorSettingsUpdate(BaseModel):
    count_min: int = Field(..., ge=2, le=6)
    count_max: int = Field(..., ge=2, le=6)
    lookback_days: int = Field(..., ge=1, le=365)
    collective_chance: float = Field(..., ge=0.0, le=1.0)
    user_chance: float = Field(..., ge=0.0, le=1.0)
    # GHG6 L: дефолт 'mix' — старые клиенты не присылают mode.
    mode: str = Field("mix", pattern="^(words|phrases|mix)$")
    # P13: дефолты — старые клиенты не присылают эти поля.
    recency_quarantine_hours: float = Field(18.0, ge=0.0, le=168.0)
    recency_quarantine_weight: float = Field(0.05, ge=0.0, le=1.0)
    # GHG8 P6.3: дефолт legacy — старые клиенты не присылают поле.
    generator_version: str = Field("legacy", pattern="^(legacy|personas)$")


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
        recency_quarantine_hours=await get_random_phrases_recency_quarantine_hours(session),
        recency_quarantine_weight=await get_random_phrases_recency_quarantine_weight(session),
        generator_version=await get_phrase_generator_version(session),
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
    await set_random_phrases_recency_quarantine_hours(
        session, body.recency_quarantine_hours
    )
    await set_random_phrases_recency_quarantine_weight(
        session, body.recency_quarantine_weight
    )
    await set_phrase_generator_version(session, body.generator_version)
    log.info("admin.rp_generator_updated", body=body.model_dump(), by=user.id)
    return body


# --- GHG8 P6.1: персоналии участников (генератор фраз v2) ---
# Тексты живут только в Neon (открытый git) — сидинг руками через эти
# эндпоинты (P6.1.b), не коммитом. Формат persona_text — [шаблоны]/[слоты],
# парсер в services/personas.py.

class PersonaRow(BaseModel):
    user_id: int
    display_name: str
    # Текст None = персоналия не заведена (юзер виден в списке всё равно —
    # админ понимает, кого ещё не просидировал).
    persona_text: str | None = None
    templates_count: int = 0
    broken_templates_count: int = 0  # шаблоны с плейсхолдером без слота


class PersonaUpdate(BaseModel):
    persona_text: str = Field(..., max_length=20_000)


class PersonaPreviewOut(BaseModel):
    phrase: str | None  # None = ни одного пригодного шаблона


def _persona_counts(text: str | None) -> tuple[int, int]:
    """(всего шаблонов, из них битых). Чистая обёртка для списка."""
    from app.services.personas import _PLACEHOLDER_RE, parse_persona

    p = parse_persona(text)
    broken = sum(
        1
        for t in p.templates
        if not all(
            p.slots.get(name.strip().lower())
            for name in _PLACEHOLDER_RE.findall(t)
        )
    )
    return len(p.templates), broken


@router.get("/admin/personas", response_model=list[PersonaRow])
async def list_personas(session: SessionDep, user: CurrentUser) -> list[PersonaRow]:
    _ensure_admin(user)
    from app.db.models import ParticipantPersona

    users = list((await session.scalars(select(User).order_by(User.id))).all())
    personas = {
        p.user_id: p.persona_text
        for p in (await session.scalars(select(ParticipantPersona))).all()
    }
    out: list[PersonaRow] = []
    for u in users:
        text = personas.get(u.id)
        total, broken = _persona_counts(text)
        out.append(
            PersonaRow(
                user_id=u.id,
                display_name=u.display_name,
                persona_text=text,
                templates_count=total,
                broken_templates_count=broken,
            )
        )
    return out


@router.put("/admin/personas/{user_id}", response_model=PersonaRow)
async def upsert_persona(
    user_id: int, body: PersonaUpdate, session: SessionDep, user: CurrentUser
) -> PersonaRow:
    _ensure_admin(user)
    from app.db.models import ParticipantPersona

    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    row = await session.get(ParticipantPersona, user_id)
    text = body.persona_text.strip()
    if not text:
        # Пустой текст = удаление персоналии (юзер вернётся на legacy-пул).
        if row is not None:
            await session.delete(row)
        await session.commit()
        log.info("admin.persona_deleted", user_id=user_id, by=user.id)
        return PersonaRow(user_id=user_id, display_name=target.display_name)
    if row is None:
        session.add(ParticipantPersona(user_id=user_id, persona_text=text))
    else:
        row.persona_text = text
    await session.commit()
    total, broken = _persona_counts(text)
    log.info(
        "admin.persona_upserted",
        user_id=user_id,
        templates=total,
        broken=broken,
        chars=len(text),
        by=user.id,
    )
    return PersonaRow(
        user_id=user_id,
        display_name=target.display_name,
        persona_text=text,
        templates_count=total,
        broken_templates_count=broken,
    )


@router.post("/admin/personas/{user_id}/preview", response_model=PersonaPreviewOut)
async def preview_persona(
    user_id: int, body: PersonaUpdate, session: SessionDep, user: CurrentUser
) -> PersonaPreviewOut:
    """Превью БЕЗ сохранения — админ проверяет текст до коммита в Neon."""
    _ensure_admin(user)
    from app.services.personas import parse_persona, render_phrase

    return PersonaPreviewOut(phrase=render_phrase(parse_persona(body.persona_text)))


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
    # GHG8 G: proxy_health-tick регистрируется только в ALWAYS_ON. Смена режима
    # → перевзвод (job появляется при включении ALWAYS_ON, снимается при выходе).
    from app.bot.dispatcher import get_bot
    from app.bot.scheduler import reschedule_proxy_health

    await reschedule_proxy_health(get_bot())
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
    # GHG7 P0.4: двухступенчатая проверка selftest. `retried=True`
    # значит первая попытка getMe моргнула, вторая прошла (если ok=True)
    # или обе упали (если ok=False). `first_error` — причина первой
    # ошибки; полезно для UI «онлайн (после ретрая)» и для разбора
    # дважды-подряд кейсов. Старые клиенты, не знающие про эти поля,
    # их просто игнорируют.
    retried: bool = False
    first_error: str | None = None


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


# --- GHG8 (18.06 #2): ручная подстановка аватарки на участника ---
# Пользователь: «можно вручную подставить ссылкой для каждого участника
# отдельно особую смешную аватарку» (кейс Серж/Митян — приватность TG не даёт
# тянуть фото). avatar_manual_url ПЕРЕКРЫВАЕТ TG для ОТОБРАЖЕНИЯ в мини-аппе
# (см. _avatar_display_url), но принудительный sync всё равно тянет TG-фото и
# пишет file_id — ручная остаётся как фолбэк, если TG-фото недоступно.


class AvatarRow(BaseModel):
    user_id: int
    display_name: str
    # Что реально показывается в мини-аппе (manual → прокси → None).
    display_url: str | None = None
    has_tg_photo: bool  # есть ли стабильный file_id (синканное TG-фото)
    manual_url: str | None = None
    synced_at: datetime | None = None


class AvatarManualIn(BaseModel):
    # Пусто/None → сброс ручной ссылки (вернуться к TG-аватарке).
    manual_url: str | None = Field(None, max_length=2048)


@router.get("/admin/avatars/list", response_model=list[AvatarRow])
async def admin_avatars_list(
    session: SessionDep, user: CurrentUser
) -> list[AvatarRow]:
    _ensure_admin(user)
    from app.api.routes_users import _avatar_display_url

    result = await session.scalars(select(User).order_by(User.display_name))
    rows: list[AvatarRow] = []
    for u in result.all():
        rows.append(
            AvatarRow(
                user_id=u.id,
                display_name=u.display_name,
                display_url=_avatar_display_url(u),
                has_tg_photo=bool(u.avatar_file_id),
                manual_url=u.avatar_manual_url,
                synced_at=u.avatar_synced_at,
            )
        )
    return rows


@router.put("/admin/avatars/{user_id}/manual", response_model=AvatarRow)
async def admin_avatars_set_manual(
    user_id: int,
    body: AvatarManualIn,
    session: SessionDep,
    user: CurrentUser,
) -> AvatarRow:
    _ensure_admin(user)
    from app.api.routes_users import _avatar_display_url

    u = await session.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")

    raw = (body.manual_url or "").strip()
    if raw and not (raw.startswith("http://") or raw.startswith("https://")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "manual_url_must_be_http")
    u.avatar_manual_url = raw or None
    await session.commit()
    log.info(
        "admin.avatar_manual_set",
        target=user_id,
        cleared=not bool(raw),
        by=user.id,
    )
    return AvatarRow(
        user_id=u.id,
        display_name=u.display_name,
        display_url=_avatar_display_url(u),
        has_tg_photo=bool(u.avatar_file_id),
        manual_url=u.avatar_manual_url,
        synced_at=u.avatar_synced_at,
    )


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


# --- GHG8 P14: рестарт HF Space (кнопка + расписание) ---

class SpaceRestartScheduleIO(BaseModel):
    """`space_restart.schedule`: off | once (at, ISO) | interval (every_hours)."""

    mode: str = Field(..., pattern="^(off|once|interval)$")
    at: str | None = None
    every_hours: int | None = Field(None, ge=1, le=720)


class SpaceRestartStatusOut(BaseModel):
    available: bool  # env HF_TOKEN задан — рестарт вообще возможен
    schedule: SpaceRestartScheduleIO
    last_restart_at: datetime | None
    next_restart_at: datetime | None


async def _space_restart_status(session) -> SpaceRestartStatusOut:
    from app.services.space_restart import (
        compute_next_restart,
        get_last_restart_at,
        get_schedule,
        hf_token_configured,
    )

    schedule = await get_schedule(session)
    last = await get_last_restart_at(session)
    nxt = compute_next_restart(schedule, last, datetime.now(timezone.utc))
    return SpaceRestartStatusOut(
        available=hf_token_configured(),
        schedule=SpaceRestartScheduleIO(**schedule),
        last_restart_at=last,
        next_restart_at=nxt,
    )


@router.get("/admin/space/restart-settings", response_model=SpaceRestartStatusOut)
async def admin_space_restart_get(
    session: SessionDep, user: CurrentUser
) -> SpaceRestartStatusOut:
    _ensure_admin(user)
    return await _space_restart_status(session)


@router.put("/admin/space/restart-settings", response_model=SpaceRestartStatusOut)
async def admin_space_restart_put(
    body: SpaceRestartScheduleIO, session: SessionDep, user: CurrentUser
) -> SpaceRestartStatusOut:
    _ensure_admin(user)
    from app.services.space_restart import set_schedule

    # once в прошлом — отклоняем сразу: иначе job рестартанул бы «мгновенно»,
    # что админ вряд ли имел в виду (для мгновенного есть кнопка).
    if body.mode == "once":
        if body.at is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "at_required_for_once")
        _parse_iso_future(body.at)
    if body.mode == "interval" and body.every_hours is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "every_hours_required_for_interval"
        )

    normalized = await set_schedule(session, body.model_dump())
    # GHG8 G: расписание сменилось → перевзводим событийный one-shot (DateTrigger
    # на новое время / снимаем job при off). Без этого новое расписание
    # подхватилось бы только при следующем рестарте процесса.
    from app.bot.scheduler import reschedule_space_restart

    await reschedule_space_restart()
    log.info("space_restart.schedule_updated", schedule=normalized, by=user.id)
    return await _space_restart_status(session)


@router.post(
    "/admin/space/restart", status_code=status.HTTP_202_ACCEPTED
)
async def admin_space_restart_now(
    session: SessionDep, user: CurrentUser
) -> dict[str, str]:
    """Ручной рестарт Space. 202 уходит клиенту ДО фактического вызова HF API:
    хоть P14-INV и показал даунтайм HTTP ≈ 0, страховаться от обрыва ответа
    дешевле, чем объяснять фронту «request failed» при успешном рестарте.

    Анти-луп 30 мин на ручной рестарт НЕ распространяется: это аварийный
    инструмент «расклинить», и админ уже подтвердил действие в UI. Но
    last_restart_at пишем — чтобы scheduled-тик не добавил второй рестарт
    следом за ручным.
    """
    _ensure_admin(user)
    from app.services.space_restart import (
        hf_token_configured,
        set_last_restart_at,
        trigger_hf_restart,
    )

    if not hf_token_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "hf_token_not_configured"
        )

    await set_last_restart_at(session, datetime.now(timezone.utc))
    log.info("space_restart.requested", source="manual", by=user.id)

    async def _fire() -> None:
        # Даём ASGI-ответу секунду на доставку до пересоздания контейнера.
        import asyncio as _aio

        await _aio.sleep(1.0)
        await trigger_hf_restart(source="manual")

    import asyncio as _asyncio

    _asyncio.create_task(_fire())
    return {"status": "restarting"}
