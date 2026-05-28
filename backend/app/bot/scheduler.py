"""Один общий APScheduler на процесс. Запускается в lifespan FastAPI и
шарит event loop с aiogram."""
from __future__ import annotations

import asyncio
import functools
import random
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.services.admin_config import (
    get_autoloser_settings,
    get_random_phrases_schedule,
    get_reminders_tick_minutes,
    get_scheduled_settings,
)
from app.services.birthdays import run_birthdays_job
from app.services.chukhan import run_chukhan_job
from app.services.random_phrases import run_random_phrases_job
from app.services.reminders import run_due_reminders

log = structlog.get_logger()


def _logged_job(
    job_id: str,
    func: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[None]]:
    """Wrap an async job so any exception is logged with traceback, и пишет
    `job_fired`/`job_done` для трассировки реальных запусков.

    Без exception-обёртки APScheduler-executor молча проглатывает traceback и
    в логе остаётся `Job raised an exception` без причины (сеть/БД/TG API).
    Без `job_fired`/`job_done` невозможно отличить «job не сработал» от
    «сработал и упал» — пользователь GHG6 п.16 как раз жаловался, что бот
    «забивает на job в назначенное время». Логи дают возможность увидеть,
    был ли вообще вход в функцию.
    """

    @functools.wraps(func)
    async def _wrapped(*args: Any, **kwargs: Any) -> None:
        log.info("scheduler.job_fired", job_id=job_id)
        try:
            await func(*args, **kwargs)
        except Exception:
            log.exception("scheduler.job_failed", job_id=job_id)
            raise
        else:
            log.info("scheduler.job_done", job_id=job_id)

    return _wrapped

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=get_settings().scheduler_tz)
    return _scheduler


# --- IDs динамических job'ов, которыми управляют admin-настройки ---
JOB_REMINDERS_TICK = "meeting_reminders_tick"
JOB_RANDOM_PHRASES = "random_phrases"
JOB_AUTOLOSER = "autoloser"
JOB_PROXY_HEALTH = "proxy_health"
JOB_CHUKHAN_WEEKLY = "chukhan_weekly"
JOB_AVATAR_SYNC = "avatar_sync_daily"
JOB_BIRTHDAYS = "birthdays_daily"
JOB_BOT_PAUSE_AUTO_RESTORE = "bot_pause_auto_restore"  # GHG6 E11
JOB_AUTO_ZAEBAL = "auto_zaebal"  # GHG6 E11.3
JOB_MEETING_FEEDBACK = "meeting_feedback_daily"  # GHG6 N2.3


def _env_int(name: str, default: int) -> int:
    import os
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


PROXY_HEALTH_INTERVAL_SEC = _env_int("PROXY_HEALTH_INTERVAL_SEC", 600)  # GHG6 PX6

# GHG7 P0.2.b: 8 секунд достаточно — прокси с медленнее реальной доставкой
# всё равно «не успеет» в чат к юзеру; ретрай-job переотправит через 5 мин.
_AUTOLOSER_SEND_TIMEOUT = 8.0
# Шаг между попытками retry — ровно 5 минут (12 попыток × 5 мин = ~1ч лимит).
_AUTOLOSER_RETRY_DELAY = timedelta(minutes=5)
# Сколько раз пытаемся вообще (включая первую попытку). После — status='expired'.
_AUTOLOSER_MAX_ATTEMPTS = 12


async def _autoloser_job(bot: Bot) -> None:
    """A6: автоматический roll лоха через services.loser.

    Запуск идёт по интервалу/cron; внутри проверяем enabled и окно времени,
    делаем атомарный roll с публикацией в group chat. После запуска триггер
    переустанавливается в `reload_dynamic_jobs` (для random-режима — на новое
    случайное время следующих суток).
    """
    from app.bot.dispatcher import get_bot  # noqa: F401  — keep cycle-safe pattern
    from app.config import get_settings as _gs
    from app.db.base import get_sessionmaker as _gsm
    from app.db.models import LoserOutbox
    from app.services.loser import compose_loser_message, roll_loser

    settings = _gs()
    if not settings.group_chat_id:
        log.warning("autoloser.no_group_chat_id")
        return

    sm = _gsm()
    async with sm() as session:
        cfg = await get_autoloser_settings(session)
        if not cfg["enabled"]:
            log.info("autoloser.disabled_in_settings")
            return
        # Окно — мягкая защита: cron уже стартует только внутри окна,
        # но кейс interval=0 (random) может попасть точно на границу.
        now = datetime.now()
        if not (cfg["window_start_hour"] <= now.hour < cfg["window_end_hour"]):
            log.info("autoloser.outside_window", hour=now.hour, cfg=cfg)
            return

        # rolled_by — синтетический "system" пользователь не нужен:
        # берём любого админа из БД для записи rolled_by.
        from sqlalchemy import select as _select

        from app.db.models import User as _User

        rolled_by = await session.scalar(
            _select(_User).where(_User.telegram_id.in_(settings.admin_tg_id_set)).limit(1)
        )
        if rolled_by is None:
            rolled_by = await session.scalar(_select(_User).limit(1))
        if rolled_by is None:
            log.warning("autoloser.no_users")
            return

        async def _announce(roll, loser, extras=None):
            """GHG7 P0.2.b.3: outbox-паттерн вместо raise-on-fail.

            Создаём `LoserOutbox` сразу в той же транзакции что и `roll`, после
            чего пробуем send_message. Любой результат — ОБНОВЛЯЕМ outbox и
            НЕ raise: иначе `roll_loser` откатит транзакцию и мы потеряем как
            roll, так и outbox-запись, что лишает retry-job шанса повторить.

            Calendar marks фильтрует source='auto' loser-метки по
            `outbox.status='sent'`, поэтому пока поста в чате нет — короны на
            календаре тоже нет (никаких фантомных «лохов без объявления»).
            """
            text = compose_loser_message(
                loser_name=loser.display_name,
                reason_text=roll.reason_text or "",
                extras=extras,
                header_emoji="🤡",
                header_label="Автолох сегодня",
            )
            now = datetime.now(timezone.utc)
            outbox = LoserOutbox(
                loser_roll_id=roll.id,
                status="pending",
                attempts=0,
                next_retry_at=now,
            )
            session.add(outbox)
            await session.flush()  # фиксируем outbox.id до send'а

            # P0.2.d: transport-логирование для диагностики «висящего прокси».
            transport = (
                "proxy"
                if getattr(bot.session, "_active_proxy_id", None) is not None
                else "direct"
            )
            proxy_id = getattr(bot.session, "_active_proxy_id", None)
            send_started = time.monotonic()
            try:
                msg = await asyncio.wait_for(
                    bot.send_message(
                        chat_id=settings.group_chat_id,
                        text=text,
                        parse_mode="HTML",
                    ),
                    timeout=_AUTOLOSER_SEND_TIMEOUT,
                )
                elapsed_ms = round((time.monotonic() - send_started) * 1000, 1)
                outbox.status = "sent"
                outbox.attempts = 1
                outbox.sent_at = datetime.now(timezone.utc)
                outbox.tg_message_id = getattr(msg, "message_id", None)
                log.info(
                    "autoloser.outbox_sent",
                    transport=transport,
                    proxy_id=proxy_id,
                    elapsed_ms=elapsed_ms,
                    tg_message_id=outbox.tg_message_id,
                )
            except Exception as exc:  # noqa: BLE001 — ловим всё, чтобы НЕ raise (откат транзакции уничтожил бы outbox-запись вместе с роллом)
                elapsed_ms = round((time.monotonic() - send_started) * 1000, 1)
                outbox.attempts = 1
                outbox.last_error = f"{type(exc).__name__}: {exc}"[:500]
                outbox.next_retry_at = (
                    datetime.now(timezone.utc) + _AUTOLOSER_RETRY_DELAY
                )
                log.warning(
                    "autoloser.outbox_pending",
                    transport=transport,
                    proxy_id=proxy_id,
                    elapsed_ms=elapsed_ms,
                    error=outbox.last_error,
                )

        try:
            # GHG6 H1: source='auto' и bypass_cooldown=True — авто-лох не
            # делит кулдаун с ручной рулеткой, и сам не блокируется им.
            await roll_loser(
                session,
                rolled_by=rolled_by,
                on_announce=_announce,
                source="auto",
                bypass_cooldown=True,
            )
            log.info("autoloser.posted")
        except Exception:
            log.exception("autoloser.failed")


def _build_random_phrases_trigger(mode: str, param: dict, tz: str):
    """Собрать APScheduler-trigger из admin_config-настроек A3.

    daily_n         param={"n": 3} → N равномерно распределённых cron-времён в сутках
    weekly_n        param={"n": 2} → N раз в неделю (по дням недели)
    fixed_times     param={"times": ["12:00", "18:00"]}
    random_interval param={"min_minutes": 120} → IntervalTrigger с jitter
    """
    if mode == "fixed_times":
        times = param.get("times") or ["19:37"]
        # Соберём несколько cron-триггеров: APScheduler не умеет «либо/либо» одним
        # триггером, но через OrTrigger можно. Чтобы не тащить кастомщину —
        # берём первое валидное время. Остальные времена даст A3 через несколько
        # job'ов (см. add_job ниже).
        hh, mm = _parse_hhmm(times[0])
        return CronTrigger(hour=hh, minute=mm, timezone=tz)
    if mode == "weekly_n":
        n = max(1, min(7, int(param.get("n", 2))))
        # n дней в неделю, в 19:37; равномерно распределяем по 7 дням.
        days = sorted({(i * 7) // n for i in range(n)})
        return CronTrigger(day_of_week=",".join(str(d) for d in days), hour=19, minute=37, timezone=tz)
    if mode == "random_interval":
        minutes = max(15, min(1440, int(param.get("min_minutes", 120))))
        return IntervalTrigger(minutes=minutes, jitter=minutes // 2)
    # daily_n (default): n раз в сутки в равномерно разнесённые часы
    n = max(1, min(24, int(param.get("n", 1))))
    if n == 1:
        return CronTrigger(hour=19, minute=37, timezone=tz)
    step = 24 // n
    hours = ",".join(str((6 + i * step) % 24) for i in range(n))
    return CronTrigger(hour=hours, minute=37, timezone=tz)


def _parse_hhmm(s: str) -> tuple[int, int]:
    try:
        hh, mm = s.strip().split(":")
        return max(0, min(23, int(hh))), max(0, min(59, int(mm)))
    except Exception:  # noqa: BLE001
        return 19, 37


def _build_autoloser_trigger(cfg: dict, tz: str):
    """A6: либо фиксированный интервал в часах, либо random раз в сутки в окне.

    Для random берём одно случайное HH:MM в окне на сегодня/завтра и ставим
    DateTrigger; после выстрела `reload_dynamic_jobs` ставит следующий день.
    """
    if cfg["interval_hours"] > 0:
        # Фиксированный интервал — IntervalTrigger; окно проверяем внутри job.
        return IntervalTrigger(hours=cfg["interval_hours"], jitter=300)
    # random раз в сутки: следующий запуск — случайная минута в окне.
    start_h = cfg["window_start_hour"]
    end_h = cfg["window_end_hour"]
    if end_h <= start_h:
        end_h = (start_h + 1) % 24
    now = datetime.now()
    candidate = now.replace(
        hour=random.randint(start_h, max(start_h, end_h - 1)),
        minute=random.randint(0, 59),
        second=0,
        microsecond=0,
    )
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return DateTrigger(run_date=candidate)


async def reload_dynamic_jobs(bot: Bot) -> None:
    """Пересобрать все управляемые админкой job'ы под текущие admin-настройки.

    Идемпотентно: вызывается из start_scheduler и из API при смене конфига
    (`/admin/scheduled` PUT). Респектит master-toggle'ы GHG6 AD6: если
    `enabled=false` — соответствующий job удаляется, не пере-создаётся.
    """
    settings = get_settings()
    sched = get_scheduler()
    sm = get_sessionmaker()
    async with sm() as session:
        sched_cfg = await get_scheduled_settings(session)
        tick_minutes = sched_cfg["reminders"]["tick_minutes"]
        rp_mode, rp_param = await get_random_phrases_schedule(session)

    # --- Reminders ---
    if sched_cfg["reminders"]["enabled"]:
        sched.add_job(
            _logged_job(JOB_REMINDERS_TICK, run_due_reminders),
            IntervalTrigger(minutes=tick_minutes),
            kwargs={"bot": bot},
            id=JOB_REMINDERS_TICK,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            # GHG6 H4: дефолтный misfire_grace_time=1с молча роняет
            # запуск если воркер был занят. Час grace покрывает любой
            # реалистичный лаг (повисший прокси/сеть/GC).
            misfire_grace_time=3600,
        )
        log.info("scheduler.reminders_tick_reloaded", minutes=tick_minutes)
    else:
        _remove_job_if_exists(sched, JOB_REMINDERS_TICK)
        log.info("scheduler.reminders_disabled")

    # --- Random phrases ---
    # Лишние fixed_times — отдельные job'ы. Чистим прошлые «extra» в любом случае.
    for j in list(sched.get_jobs()):
        if j.id.startswith(f"{JOB_RANDOM_PHRASES}:extra:"):
            sched.remove_job(j.id)
    if sched_cfg["phrases"]["enabled"]:
        rp_trigger = _build_random_phrases_trigger(rp_mode, rp_param, settings.scheduler_tz)
        sched.add_job(
            _logged_job(JOB_RANDOM_PHRASES, run_random_phrases_job),
            rp_trigger,
            kwargs={"bot": bot},
            id=JOB_RANDOM_PHRASES,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,  # GHG6 H4
        )
        if rp_mode == "fixed_times":
            times = rp_param.get("times") or []
            for i, t in enumerate(times[1:], start=1):
                hh, mm = _parse_hhmm(t)
                sched.add_job(
                    _logged_job(f"{JOB_RANDOM_PHRASES}:extra:{i}", run_random_phrases_job),
                    CronTrigger(hour=hh, minute=mm, timezone=settings.scheduler_tz),
                    kwargs={"bot": bot},
                    id=f"{JOB_RANDOM_PHRASES}:extra:{i}",
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=3600,  # GHG6 H4
                )
        log.info("scheduler.random_phrases_reloaded", mode=rp_mode, param=rp_param)
    else:
        _remove_job_if_exists(sched, JOB_RANDOM_PHRASES)
        log.info("scheduler.random_phrases_disabled")

    # --- Autoloser ---
    autoloser_cfg = {
        "enabled": sched_cfg["loser"]["enabled"],
        "window_start_hour": sched_cfg["loser"]["window_start_hour"],
        "window_end_hour": sched_cfg["loser"]["window_end_hour"],
        "interval_hours": sched_cfg["loser"]["interval_hours"],
    }
    if autoloser_cfg["enabled"]:
        sched.add_job(
            _logged_job(JOB_AUTOLOSER, _autoloser_job),
            _build_autoloser_trigger(autoloser_cfg, settings.scheduler_tz),
            kwargs={"bot": bot},
            id=JOB_AUTOLOSER,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,  # GHG6 H4
        )
        log.info("scheduler.autoloser_enabled", cfg=autoloser_cfg)
    else:
        _remove_job_if_exists(sched, JOB_AUTOLOSER)
        log.info("scheduler.autoloser_disabled")

    # --- Avatars sync (GHG6 AD6) ---
    if sched_cfg["avatars"]["enabled"]:
        per_day = sched_cfg["avatars"]["per_day"]
        # per_day → interval_hours: 1.0 → 24ч, 2.0 → 12ч, 0.5 → 48ч.
        interval_hours = max(1, int(round(24.0 / max(0.14, per_day))))
        async def _sync_avatars_job() -> None:
            sm2 = get_sessionmaker()
            async with sm2() as session:
                from app.services.avatars import sync_all_avatars
                await sync_all_avatars(session, bot)
        sched.add_job(
            _logged_job(JOB_AVATAR_SYNC, _sync_avatars_job),
            IntervalTrigger(hours=interval_hours, jitter=300),
            id=JOB_AVATAR_SYNC,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,  # GHG6 H4
        )
        log.info("scheduler.avatars_reloaded", per_day=per_day, interval_hours=interval_hours)
    else:
        _remove_job_if_exists(sched, JOB_AVATAR_SYNC)
        log.info("scheduler.avatars_disabled")

    # --- Chukhan weekly (GHG6 AD6) — день недели + рандомная минута в окне ---
    chukhan_cfg = sched_cfg["chukhan"]
    ws_h, ws_m = _parse_hhmm(chukhan_cfg["window_start"])
    we_h, we_m = _parse_hhmm(chukhan_cfg["window_end"])
    # Случайный час в окне (включая ws_h, исключая we_h), затем минута в окне для крайних случаев.
    if we_h <= ws_h:
        we_h = (ws_h + 1) % 24
    import random as _rnd
    chukhan_hour = _rnd.randint(ws_h, max(ws_h, we_h - 1))
    chukhan_min = _rnd.randint(0, 59)
    chukhan_dow = chukhan_cfg["weekday"]  # 0=Mon в нашей UI ↔ APScheduler dow=0=Mon
    sched.add_job(
        _logged_job(JOB_CHUKHAN_WEEKLY, run_chukhan_job),
        CronTrigger(
            day_of_week=str(chukhan_dow),
            hour=chukhan_hour,
            minute=chukhan_min,
            timezone=settings.scheduler_tz,
        ),
        kwargs={"bot": bot},
        id=JOB_CHUKHAN_WEEKLY,
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    log.info(
        "scheduler.chukhan_reloaded",
        dow=chukhan_dow,
        hour=chukhan_hour,
        minute=chukhan_min,
    )

    # --- E11.3: авто-zaebal раз в месяц (15-18 числа, default-off) ---
    async with sm() as session:
        from app.services.bot_pause import get_zaebal_settings
        zaebal_cfg = await get_zaebal_settings(session)
    if zaebal_cfg["auto_enabled"]:
        async def _auto_zaebal() -> None:
            from app.services.zaebal import run_auto_zaebal

            sm2 = get_sessionmaker()
            async with sm2() as session:
                await run_auto_zaebal(session, bot)

        sched.add_job(
            _logged_job(JOB_AUTO_ZAEBAL, _auto_zaebal),
            CronTrigger(
                day="15-18",
                hour=18,
                minute=37,
                timezone=settings.scheduler_tz,
            ),
            id=JOB_AUTO_ZAEBAL,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,  # GHG6 H4
        )
        log.info("scheduler.auto_zaebal_enabled")
    else:
        _remove_job_if_exists(sched, JOB_AUTO_ZAEBAL)
        log.info("scheduler.auto_zaebal_disabled")

    # --- Birthdays — глобальный switch (точное время — внутри run_birthdays_job) ---
    if sched_cfg["birthdays"]["alerts_enabled"]:
        sched.add_job(
            _logged_job(JOB_BIRTHDAYS, run_birthdays_job),
            CronTrigger(hour=9, minute=7, timezone=settings.scheduler_tz),
            kwargs={"bot": bot},
            id=JOB_BIRTHDAYS,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        log.info("scheduler.birthdays_enabled")
    else:
        _remove_job_if_exists(sched, JOB_BIRTHDAYS)
        log.info("scheduler.birthdays_disabled")

    # --- Meeting feedback (GHG6 N2.3): пост-фактум 5★-опрос ---
    # Дневной проход в 12:07 — встречи прошедшего дня (cutoff = now - 1d)
    # получают свой feedback-полл. Master-toggle берётся из admin_config внутри
    # самой job-функции (`run_meeting_feedback_job`), но чтобы не палить
    # лишнюю job когда фича выключена — пропускаем регистрацию совсем.
    from app.services.admin_config import get_meeting_feedback_enabled
    from app.services.meeting_feedback import run_meeting_feedback_job

    if await get_meeting_feedback_enabled(session):
        sched.add_job(
            _logged_job(JOB_MEETING_FEEDBACK, run_meeting_feedback_job),
            CronTrigger(hour=12, minute=7, timezone=settings.scheduler_tz),
            kwargs={"bot": bot},
            id=JOB_MEETING_FEEDBACK,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        log.info("scheduler.meeting_feedback_enabled")
    else:
        _remove_job_if_exists(sched, JOB_MEETING_FEEDBACK)
        log.info("scheduler.meeting_feedback_disabled")


def _remove_job_if_exists(sched: AsyncIOScheduler, job_id: str) -> None:
    if sched.get_job(job_id) is not None:
        sched.remove_job(job_id)


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    settings = get_settings()
    sched = get_scheduler()
    if sched.running:
        return sched

    # GHG6 AD6: chukhan/avatars/birthdays теперь регистрирует
    # `reload_dynamic_jobs` — респектят master-toggles из admin_config.
    # Прокси-health-tick — независимая инфра, регистрируем здесь.
    from app.services.proxies import proxy_health_tick

    sched.add_job(
        _logged_job(JOB_PROXY_HEALTH, proxy_health_tick),
        IntervalTrigger(seconds=PROXY_HEALTH_INTERVAL_SEC, jitter=30),
        kwargs={"bot": bot},
        id=JOB_PROXY_HEALTH,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=PROXY_HEALTH_INTERVAL_SEC,  # GHG6 H4
    )

    # GHG6 E11: фоновая проверка истечения паузы. Раз в 5 минут — пауза
    # не требует точности до секунды. Этот job не отключается reload_dynamic_jobs
    # и всегда крутится: иначе из автопаузы не выйти.
    async def _auto_restore_tick() -> None:
        from app.services.bot_pause import maybe_auto_restore

        sm2 = get_sessionmaker()
        async with sm2() as session:
            await maybe_auto_restore(session)

    sched.add_job(
        _logged_job(JOB_BOT_PAUSE_AUTO_RESTORE, _auto_restore_tick),
        IntervalTrigger(minutes=5, jitter=30),
        id=JOB_BOT_PAUSE_AUTO_RESTORE,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,  # GHG6 H4: 10мин — пауза не требует секундной точности
    )

    sched.start()
    log.info("scheduler.started", chukhan_cron=settings.chukhan_cron, tz=settings.scheduler_tz)

    # Динамические job'ы — после start, чтобы reload_dynamic_jobs мог
    # пересоздавать их через сам же sched (он уже running).
    import asyncio as _asyncio

    _asyncio.create_task(reload_dynamic_jobs(bot))

    return sched


async def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")
    _scheduler = None
