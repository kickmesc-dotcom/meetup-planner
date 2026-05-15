"""Один общий APScheduler на процесс. Запускается в lifespan FastAPI и
шарит event loop с aiogram."""
from __future__ import annotations

import functools
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
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
)
from app.services.avatars import sync_all_avatars
from app.services.birthdays import run_birthdays_job
from app.services.chukhan import run_chukhan_job
from app.services.random_phrases import run_random_phrases_job
from app.services.reminders import run_due_reminders

log = structlog.get_logger()


def _logged_job(
    job_id: str,
    func: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[None]]:
    """Wrap an async job so any exception is logged with traceback.

    Without this, APScheduler's executor swallows the exception, logs a bare
    'Executed successfully' / 'Job raised an exception' line without context,
    and the actual reason (network, DB, TG API) never reaches stdout.
    """

    @functools.wraps(func)
    async def _wrapped(*args: Any, **kwargs: Any) -> None:
        try:
            await func(*args, **kwargs)
        except Exception:
            log.exception("scheduler.job_failed", job_id=job_id)
            raise

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
    from app.services.loser import roll_loser

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

        async def _announce(roll, loser):
            text = f"🤡 <b>Автолох сегодня:</b> {loser.display_name}\n<i>{roll.reason_text}</i>"
            await bot.send_message(
                chat_id=settings.group_chat_id,
                text=text,
                parse_mode="HTML",
            )

        try:
            await roll_loser(session, rolled_by=rolled_by, on_announce=_announce)
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
    """Пересобрать reminders/random_phrases/autoloser-job'ы под новые
    admin-настройки. Идемпотентно: вызывается из start_scheduler и из API при
    смене конфига."""
    settings = get_settings()
    sched = get_scheduler()
    sm = get_sessionmaker()
    async with sm() as session:
        tick_minutes = await get_reminders_tick_minutes(session)
        rp_mode, rp_param = await get_random_phrases_schedule(session)
        autoloser_cfg = await get_autoloser_settings(session)

    sched.add_job(
        _logged_job(JOB_REMINDERS_TICK, run_due_reminders),
        IntervalTrigger(minutes=tick_minutes),
        kwargs={"bot": bot},
        id=JOB_REMINDERS_TICK,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info("scheduler.reminders_tick_reloaded", minutes=tick_minutes)

    # Random phrases: один основной job; для fixed_times с несколькими временами
    # добавляем дополнительные job'ы с суффиксом.
    rp_trigger = _build_random_phrases_trigger(rp_mode, rp_param, settings.scheduler_tz)
    sched.add_job(
        _logged_job(JOB_RANDOM_PHRASES, run_random_phrases_job),
        rp_trigger,
        kwargs={"bot": bot},
        id=JOB_RANDOM_PHRASES,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # Лишние fixed_times — отдельные job'ы. Чистим прошлые «extra», добавляем заново.
    for j in list(sched.get_jobs()):
        if j.id.startswith(f"{JOB_RANDOM_PHRASES}:extra:"):
            sched.remove_job(j.id)
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
            )
    log.info("scheduler.random_phrases_reloaded", mode=rp_mode, param=rp_param)

    if autoloser_cfg["enabled"]:
        sched.add_job(
            _logged_job(JOB_AUTOLOSER, _autoloser_job),
            _build_autoloser_trigger(autoloser_cfg, settings.scheduler_tz),
            kwargs={"bot": bot},
            id=JOB_AUTOLOSER,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        log.info("scheduler.autoloser_enabled", cfg=autoloser_cfg)
    else:
        if sched.get_job(JOB_AUTOLOSER) is not None:
            sched.remove_job(JOB_AUTOLOSER)
        log.info("scheduler.autoloser_disabled")


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    settings = get_settings()
    sched = get_scheduler()
    if sched.running:
        return sched

    sched.add_job(
        _logged_job("chukhan_weekly", run_chukhan_job),
        CronTrigger.from_crontab(settings.chukhan_cron, timezone=settings.scheduler_tz),
        kwargs={"bot": bot},
        id="chukhan_weekly",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )

    async def _sync_avatars_job() -> None:
        sm = get_sessionmaker()
        async with sm() as session:
            await sync_all_avatars(session, bot)

    sched.add_job(
        _logged_job("avatar_sync_daily", _sync_avatars_job),
        CronTrigger.from_crontab("17 4 * * *", timezone=settings.scheduler_tz),
        id="avatar_sync_daily",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    sched.add_job(
        _logged_job("birthdays_daily", run_birthdays_job),
        CronTrigger(hour=9, minute=7, timezone=settings.scheduler_tz),
        kwargs={"bot": bot},
        id="birthdays_daily",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
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
