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

# --- H2 (30.09): классификация «транзиентных» сбоев БД ---------------------
# Прод-инцидент: один прогон `run_memes_job` упал на `socket.gaierror:
# Temporary failure in name resolution` — контейнер Amvera на секунду не смог
# разрешить DNS до Neon. Это НЕ баг кода: следующий прогон той же job'ы
# отработал штатно. Но APScheduler трактует любое исключение как провал
# запуска, а `_logged_job` до этого просто пробрасывал его наверх — то есть
# секундный сетевой блип убивал весь прогон целиком (а, например, у
# `run_memes_job` внутри две фазы, и вторая тоже не выполнялась).
#
# Лечение: распознаём транзиентные сбои подключения (DNS, сокет, обрыв
# соединения, таймаут, «база недоступна») и повторяем прогон с экспоненциальной
# задержкой. Логика БД (constraint violation, UndefinedColumn, неверный SQL) —
# НЕ транзиентна: её ретраить бессмысленно и опасно (можно замаскировать
# настоящую ошибку), поэтому такие исключения по-прежнему валят прогон сразу.
_TRANSIENT_DB_EXC_NAMES = frozenset(
    {
        # sqlalchemy.exc — ошибки уровня соединения/движка
        "OperationalError",
        "InterfaceError",
        "DisconnectionError",
        "DBAPIError",
        # asyncpg — соединение/postgres-сервер недоступен
        "ConnectionDoesNotExistError",
        "PostgresConnectionError",
        "CannotConnectNowError",
        "TooManyConnectionsError",
        "ConnectionResetError",
        "ConnectionRefusedError",
        "ConnectionAbortedError",
        "IncompleteReadError",
        "TimeoutError",
    }
)


def _is_transient_db_error(exc: BaseException | None) -> bool:
    """True, если исключение (или его причина) — транзиентный сбой доступа к БД.

    Проходим цепочку `__cause__`/`__context__`: SQLAlchemy заворачивает
    низкоуровневые `asyncpg`/`socket`-ошибки, поэтому тип верхнего исключения
    малоинформативен. Смотрим и по имени класса (sqlalchemy/asyncpg тянуть в
    импорт ради isinstance здесь не хочется — это опциональные зависимости в
    тестах), и по `isinstance(OSError/TimeoutError)` — `socket.gaierror` из
    прод-инцидента наследуется именно от `OSError`.
    """
    seen: set[int] = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, OSError | TimeoutError):
            return True
        if type(cur).__name__ in _TRANSIENT_DB_EXC_NAMES:
            return True
        cur = cur.__cause__ or cur.__context__
    return False


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

    H2 (30.09): транзиентный сбой БД (DNS/сокет/таймаут) не роняет прогон —
    повторяем до `_SCHEDULER_DB_RETRY_ATTEMPTS` раз с экспоненциальной паузой
    (base × 2^n). Каждая повторная попытка пишет `scheduler.job_retry`, а
    итоговая неудача после исчерпания попыток — `scheduler.job_failed` с
    флагом `transient=True`. Нетранзиентные ошибки ретраить не пытаемся.
    """

    @functools.wraps(func)
    async def _wrapped(*args: Any, **kwargs: Any) -> None:
        log.info("scheduler.job_fired", job_id=job_id)
        attempt = 0
        while True:
            attempt += 1
            try:
                await func(*args, **kwargs)
            except Exception as exc:
                transient = _is_transient_db_error(exc)
                if transient and attempt < _SCHEDULER_DB_RETRY_ATTEMPTS:
                    delay = _SCHEDULER_DB_RETRY_BASE_DELAY_SEC * (2 ** (attempt - 1))
                    log.warning(
                        "scheduler.job_retry",
                        job_id=job_id,
                        attempt=attempt,
                        max_attempts=_SCHEDULER_DB_RETRY_ATTEMPTS,
                        delay_sec=delay,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    await asyncio.sleep(delay)
                    continue
                log.exception(
                    "scheduler.job_failed",
                    job_id=job_id,
                    attempt=attempt,
                    transient=transient,
                )
                raise
            else:
                log.info("scheduler.job_done", job_id=job_id, attempts=attempt)
                return

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
JOB_LOSER_OUTBOX_RETRY = "loser_outbox_retry"  # GHG7 P0.2.b.4
JOB_CHUKHAN_RETRY = "chukhan_retry"  # GHG7 P11 (инцидент 03.06 #1)
JOB_DEAD_CHAT = "dead_chat_hourly"  # GHG8 P7
JOB_SPACE_RESTART = "space_restart_tick"  # GHG8 P14
JOB_GAME_HOLIDAYS = "game_holidays_daily"  # GHG10 Э10
JOB_GAME_WEEK_ACTIVITY = "game_week_activity_weekly"  # GHG10 Э6
JOB_GAME_MEMES = "game_memes_sweep"  # GHG10 Э7
JOB_GAME_MEMORIAL = "game_memorial_daily"  # GHG10 Э13
JOB_GAME_EVENTS = "game_events_hourly"  # GHG10 Э13
JOB_GAME_DIGEST = "game_digest_flush"  # GHG10 Э13
JOB_GAME_VOICE = "game_voice_tick"  # GHG10 Э14
JOB_GAME_MUSIC = "game_music_weekly"  # GHG10 Э15
JOB_GAME_MUSIC_GAME = "game_music_game_weekly"  # GHG10 Э16


def _env_int(name: str, default: int) -> int:
    import os
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    import os
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# H2 (30.09): сколько раз повторять прогон при транзиентном сбое БД и базовая
# пауза (экспоненциально растёт: base, base×2, base×4…). Всего попыток, включая
# первую. Дефолт: 3 попытки с паузами 2с/4с — суммарно ~6с ожидания, этого
# хватает на типичный DNS-блип, но не растягивает тик до неприличия (у части
# job'ов misfire_grace_time всего 10 минут, а в одной БД-сессии интервал 10 мин).
_SCHEDULER_DB_RETRY_ATTEMPTS = max(1, _env_int("SCHEDULER_DB_RETRY_ATTEMPTS", 3))
_SCHEDULER_DB_RETRY_BASE_DELAY_SEC = max(
    0.0, _env_float("SCHEDULER_DB_RETRY_BASE_DELAY_SEC", 2.0)
)


# GHG6 PX6 / GHG7 P8.4: онлайн-статус раз в час (было 10 мин). Каждый тик —
# исходящий bot.get_me() к api.telegram.org; 600с давали 144 «пустых» запроса/
# сутки, что при throttling канала отъедало бюджет у реальных сообщений. 3600с
# → 24/сутки. Свежесть индикатора падает до 1 часа — осознанный компромисс.
PROXY_HEALTH_INTERVAL_SEC = _env_int("PROXY_HEALTH_INTERVAL_SEC", 3600)

# GHG7 P8.1: таймаут отправки лоха настраивается через env LOSER_SEND_TIMEOUT
# (дефолт 25с). Прежние 8с резали доставку при throttling канала (РКН): TG
# отвечает за 8–30с, а сессия бота держит 30с (_IPv4AiohttpSession). «Случайная
# фраза» шлёт БЕЗ wait_for и доходит — лох же оборачивался в wait_for(8s) и падал
# в TimeoutError (прод 30.05: rolls 35/36 → outbox expired). 25с < 30с сессии:
# даём send успеть, но не виснем дольше самой сессии. Ретрай-job догонит, если
# и 25с не хватило.
_AUTOLOSER_SEND_TIMEOUT = float(_env_int("LOSER_SEND_TIMEOUT", 25))
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
            # GHG8 P3: оглашение «черновых» именинников (announce-режим
            # иммунитета). Best-effort: фейл не трогает outbox/roll.
            if extras is not None and getattr(extras, "immunity_skipped", None):
                from app.services.birthday_immunity import announce_immunity_skips

                await announce_immunity_skips(
                    bot,
                    settings.group_chat_id,
                    extras.immunity_skipped,
                    send_timeout=_AUTOLOSER_SEND_TIMEOUT,
                )
            # GHG7 P9.1.d: автолох-по-расписанию = «Лох дня» (👑), source="auto"
            # идёт в статистику/титулы. 🤡 «Автолох» — это ручная дуэль (duel).
            text = compose_loser_message(
                loser_name=loser.display_name,
                reason_text=roll.reason_text or "",
                extras=extras,
                header_emoji="👑",
                header_label="Лох дня",
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


async def _loser_outbox_retry_job(bot: Bot) -> None:
    """GHG7 P0.2.b.4: ретраит pending-записи `loser_outbox`.

    Каждую минуту берёт до 10 записей `status='pending' AND attempts<MAX AND
    next_retry_at<=now()` под `FOR UPDATE SKIP LOCKED` — две машины (или job
    и админский «принудительный ретрай», если когда-нибудь появится) не
    подерутся за одну строку. Для каждой пересобираем текст из
    `LoserRoll+User` (без worm-блока — если корона уже передавалась в БД
    при первом roll, текст «передача звания» уже бессмыслен через час).

    Лимиты: 12 попыток × 5 мин = ~1 час суммарного окна доставки. После —
    `status='expired'`. Корона на календаре до `status='sent'` не показана
    (фильтр в `routes_calendar.py`, см. b.5), поэтому expired-роллы
    тихо остаются в БД для аналитики, без визуального шума.
    """
    from sqlalchemy import select as _select

    from app.config import get_settings as _gs
    from app.db.base import get_sessionmaker as _gsm
    from app.db.models import LoserOutbox, LoserRoll, User
    from app.services.loser import compose_loser_message

    settings = _gs()
    if not settings.group_chat_id:
        return  # без чата ретраить некуда — outbox останется pending

    sm = _gsm()
    async with sm() as session:
        # FOR UPDATE SKIP LOCKED — postgres-only, в SQLite-тестах sa упадёт.
        # Тесты на retry-job будут использовать postgres-fixture либо моковать
        # эту функцию целиком. LIMIT 10 защищает от «бури» если пул-доставщик
        # вдруг встал на час и накопил тысячу записей.
        stmt = (
            _select(LoserOutbox)
            .where(
                LoserOutbox.status == "pending",
                LoserOutbox.attempts < _AUTOLOSER_MAX_ATTEMPTS,
                LoserOutbox.next_retry_at <= datetime.now(timezone.utc),
            )
            .order_by(LoserOutbox.next_retry_at.asc())
            .limit(10)
            .with_for_update(skip_locked=True)
        )
        rows = list((await session.scalars(stmt)).all())
        if not rows:
            return

        for outbox in rows:
            roll = await session.get(LoserRoll, outbox.loser_roll_id)
            if roll is None:
                # Roll удалён вручную (например `delete_last_loser`) — outbox
                # обессмыслен. Помечаем expired, чтобы не крутить впустую.
                outbox.status = "expired"
                outbox.last_error = "loser_roll missing"
                continue

            loser_user = await session.get(User, roll.loser_user_id)
            loser_name = (
                loser_user.display_name if loser_user is not None else "?"
            )
            # GHG7 P9.1.d: ретрай автолоха-по-расписанию — тоже «Лох дня» (👑),
            # как и первичная отправка (_announce выше).
            text = compose_loser_message(
                loser_name=loser_name,
                reason_text=roll.reason_text or "",
                extras=None,  # worm-стилизация при ретрае не повторяется
                header_emoji="👑",
                header_label="Лох дня",
            )

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
                outbox.attempts = outbox.attempts + 1
                outbox.sent_at = datetime.now(timezone.utc)
                outbox.tg_message_id = getattr(msg, "message_id", None)
                outbox.last_error = None
                log.info(
                    "loser_outbox_retry.sent",
                    outbox_id=outbox.id,
                    attempts=outbox.attempts,
                    transport=transport,
                    proxy_id=proxy_id,
                    elapsed_ms=elapsed_ms,
                    tg_message_id=outbox.tg_message_id,
                )
            except Exception as exc:  # noqa: BLE001 — лимит/ретрай решается ниже
                elapsed_ms = round((time.monotonic() - send_started) * 1000, 1)
                outbox.attempts = outbox.attempts + 1
                outbox.last_error = f"{type(exc).__name__}: {exc}"[:500]
                if outbox.attempts >= _AUTOLOSER_MAX_ATTEMPTS:
                    outbox.status = "expired"
                    log.warning(
                        "loser_outbox_retry.expired",
                        outbox_id=outbox.id,
                        attempts=outbox.attempts,
                        last_error=outbox.last_error,
                    )
                else:
                    outbox.next_retry_at = (
                        datetime.now(timezone.utc) + _AUTOLOSER_RETRY_DELAY
                    )
                    log.warning(
                        "loser_outbox_retry.pending",
                        outbox_id=outbox.id,
                        attempts=outbox.attempts,
                        transport=transport,
                        proxy_id=proxy_id,
                        elapsed_ms=elapsed_ms,
                        error=outbox.last_error,
                    )

        await session.commit()


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

    # --- GHG10 (Э10): праздники — ежедневный обход.
    # Регистрируем ТОЛЬКО при включённом рубильнике: когда игра выключена, в
    # простое не должно быть ни одного лишнего тика (требование Э12.2).
    from app.services.game.flags import is_game_enabled

    # Один запрос на обе игровые job'ы: reload и так редкий, но два одинаковых
    # `SELECT` подряд — бессмысленные round-trip'ы (см. заметку про кэш флага).
    game_on = await is_game_enabled(session)

    if game_on:
        from app.services.game.holidays import run_holidays_job

        sched.add_job(
            _logged_job(JOB_GAME_HOLIDAYS, run_holidays_job),
            CronTrigger(hour=9, minute=17, timezone=settings.scheduler_tz),
            kwargs={"bot": bot},
            id=JOB_GAME_HOLIDAYS,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        log.info("scheduler.game_holidays_enabled")
    else:
        _remove_job_if_exists(sched, JOB_GAME_HOLIDAYS)
        log.info("scheduler.game_holidays_disabled")

    # --- GHG10 (Э6): недельный итог активности — «Рупор поколения» / «Read only».
    # Понедельник 09:27 — после конца ISO-недели, рядом с утренними ДР/праздниками.
    # Как и праздники, регистрируем ТОЛЬКО при включённом рубильнике.
    if game_on:
        from app.services.game.weekly import run_week_activity_job

        sched.add_job(
            _logged_job(JOB_GAME_WEEK_ACTIVITY, run_week_activity_job),
            CronTrigger(
                day_of_week="mon", hour=9, minute=27, timezone=settings.scheduler_tz
            ),
            kwargs={"bot": bot},
            id=JOB_GAME_WEEK_ACTIVITY,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        log.info("scheduler.game_week_activity_enabled")
    else:
        _remove_job_if_exists(sched, JOB_GAME_WEEK_ACTIVITY)
        log.info("scheduler.game_week_activity_disabled")

    # --- GHG10 (Э7): разбор мем-постов.
    # Каждые 10 минут закрываем окно реакции и выносим 12-часовой вердикт. Две
    # фазы в одном прогоне (см. `memes.resolve_due`), поэтому частота — компромисс:
    # чаще = быстрее ачивка, реже = дешевле (в простое это один SELECT).
    if game_on:
        from app.services.game.memes import run_memes_job

        sched.add_job(
            _logged_job(JOB_GAME_MEMES, run_memes_job),
            IntervalTrigger(minutes=10),
            id=JOB_GAME_MEMES,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=600,
        )
        log.info("scheduler.game_memes_enabled")
    else:
        _remove_job_if_exists(sched, JOB_GAME_MEMES)
        log.info("scheduler.game_memes_disabled")

    # --- GHG10 (Э13): «поминальные» — раз в сутки.
    # 10:05 — после утренних ДР/праздников, чтобы поминовение не толкалось с
    # ними в одном сообщении. Само решение «кого поминать» принимает job
    # (порог и интервал повтора читаются из конфига и меняются без деплоя).
    if game_on:
        from app.services.game.memorial import run_memorial_job

        sched.add_job(
            _logged_job(JOB_GAME_MEMORIAL, run_memorial_job),
            CronTrigger(hour=10, minute=5, timezone=settings.scheduler_tz),
            id=JOB_GAME_MEMORIAL,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        log.info("scheduler.game_memorial_enabled")
    else:
        _remove_job_if_exists(sched, JOB_GAME_MEMORIAL)
        log.info("scheduler.game_memorial_disabled")

    # --- GHG10 (Э13): случайные события.
    # Тик — часовой, а «выпадать/не выпадать» решает сам job: пауза между
    # событиями (`min_gap_hours`), суточный потолок и вероятность. Поэтому
    # правка настроек в админке работает без пересоздания job'а.
    if game_on:
        from app.services.game.events import run_events_job

        sched.add_job(
            _logged_job(JOB_GAME_EVENTS, run_events_job),
            IntervalTrigger(hours=1),
            id=JOB_GAME_EVENTS,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )
        log.info("scheduler.game_events_enabled")
    else:
        _remove_job_if_exists(sched, JOB_GAME_EVENTS)
        log.info("scheduler.game_events_disabled")

    # --- GHG10 (Э13): отправка сводки.
    # Режим сводки ВЫКЛЮЧЕН по умолчанию (см. `game.digest.enabled`), но job
    # регистрируем всегда при включённой игре: включение режима не должно
    # требовать рестарта контейнера. Пустой журнал = ноль работы.
    if game_on:
        from app.services.game.journal import run_digest_job

        sched.add_job(
            _logged_job(JOB_GAME_DIGEST, run_digest_job),
            IntervalTrigger(minutes=30),
            id=JOB_GAME_DIGEST,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=900,
        )
        log.info("scheduler.game_digest_enabled")
    else:
        _remove_job_if_exists(sched, JOB_GAME_DIGEST)
        log.info("scheduler.game_digest_disabled")

    # --- GHG10 (Э14): голосовые задания. ---
    # Job тикает часто, а решение «ставить ли задание» принимает сам: дневное
    # окно, пауза ``game.voice.min_gap_hours`` и «нет открытого задания». Поэтому
    # правка настроек в админке работает без пересоздания job'а.
    if game_on:
        from app.services.game.voice import run_voice_job

        sched.add_job(
            _logged_job(JOB_GAME_VOICE, run_voice_job),
            IntervalTrigger(minutes=30),
            kwargs={"bot": bot},
            id=JOB_GAME_VOICE,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=900,
        )
        log.info("scheduler.game_voice_enabled")
    else:
        _remove_job_if_exists(sched, JOB_GAME_VOICE)
        log.info("scheduler.game_voice_disabled")

    # --- GHG10 (Э15): музыкальная предложка. ---
    # Job тикает часто, а «пора ли публиковать» решает сам по расписанию из
    # админки и последней попытке (в т.ч. повтор при недоборе через 3–6 ч).
    if game_on:
        from app.services.game.music import run_music_job

        sched.add_job(
            _logged_job(JOB_GAME_MUSIC, run_music_job),
            IntervalTrigger(minutes=30),
            kwargs={"bot": bot},
            id=JOB_GAME_MUSIC,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=900,
        )
        log.info("scheduler.game_music_enabled")
    else:
        _remove_job_if_exists(sched, JOB_GAME_MUSIC)
        log.info("scheduler.game_music_disabled")

    # --- GHG10 (Э16): мьюзик-гейм «угадай, кто предложил трек». ---
    # Авто-вызов — опция (по умолчанию выкл). Job тикает часто, а «пора ли» решает
    # сам: расписание из админки, отсутствие открытого раунда и память о прошлых.
    # Зависшие раунды (опрос не долетел) он же и закрывает.
    if game_on:
        from app.services.game.music_game import run_music_game_job

        sched.add_job(
            _logged_job(JOB_GAME_MUSIC_GAME, run_music_game_job),
            IntervalTrigger(minutes=30),
            kwargs={"bot": bot},
            id=JOB_GAME_MUSIC_GAME,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=900,
        )
        log.info("scheduler.game_music_game_enabled")
    else:
        _remove_job_if_exists(sched, JOB_GAME_MUSIC_GAME)
        log.info("scheduler.game_music_game_disabled")


def _remove_job_if_exists(sched: AsyncIOScheduler, job_id: str) -> None:
    if sched.get_job(job_id) is not None:
        sched.remove_job(job_id)


async def _space_restart_job() -> None:
    """GHG8 G (антиспам): one-shot job рестарта Space. Делает решение+вызов HF
    (`run_space_restart_tick`), затем перевзводит следующий one-shot
    (`reschedule_space_restart`): interval → следующий DateTrigger от
    last_restart_at; once → расписание стало off → job снимается."""
    from app.services.space_restart import run_space_restart_tick

    await run_space_restart_tick()
    await reschedule_space_restart()


async def reschedule_proxy_health(bot: Bot) -> None:
    """GHG8 G (антиспам): регистрируем proxy_health-tick ТОЛЬКО в режиме
    ALWAYS_ON.

    Тик шлёт selftest (getMe к api.telegram.org) и алёртит админов про мёртвые
    прокси — но алёрт срабатывает лишь когда `mode is ALWAYS_ON` (см.
    `proxy_health_tick`). В AUTO_FALLBACK/ALWAYS_OFF (прод обычно тут — прокси
    в проде не работали) тик = 24 холостых исходящих getMe/сутки без пользы:
    fallback управляется per-request в dispatcher, не этим тиком. Поэтому вне
    ALWAYS_ON job не регистрируем (0 запросов). Переключение режима из админки
    дёргает этот reschedule → job появляется/исчезает на лету.
    """
    from app.services.proxies import ProxyMode, get_proxy_mode, proxy_health_tick

    sched = get_scheduler()
    sm = get_sessionmaker()
    async with sm() as session:
        mode = await get_proxy_mode(session)
    if mode is not ProxyMode.ALWAYS_ON:
        _remove_job_if_exists(sched, JOB_PROXY_HEALTH)
        log.info("scheduler.proxy_health_disarmed", mode=mode.value)
        return
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
    log.info("scheduler.proxy_health_armed", interval_sec=PROXY_HEALTH_INTERVAL_SEC)


async def reschedule_space_restart() -> None:
    """GHG8 G: событийное планирование рестарта Space вместо 5-мин поллинга.

    Ставит ОДИН `DateTrigger` ровно на `compute_next_fire` (учитывает 30-мин
    анти-луп). off → job не регистрируется (0 запросов в простое — это 99%
    времени, режим обычно off/раз-в-неделю). Вызывается на старте и из
    admin PUT при смене расписания. После каждого выстрела job сам себя
    перевзводит через `_space_restart_job`.
    """
    from app.services.space_restart import (
        compute_next_fire,
        get_last_restart_at,
        get_schedule,
    )

    sched = get_scheduler()
    sm = get_sessionmaker()
    async with sm() as session:
        schedule = await get_schedule(session)
        last = await get_last_restart_at(session)
    now = datetime.now(timezone.utc)
    nxt = compute_next_fire(schedule, last, now)
    if nxt is None:
        _remove_job_if_exists(sched, JOB_SPACE_RESTART)
        log.info("scheduler.space_restart_disarmed")
        return
    # Просроченный once (контейнер лежал) → стреляем немедленно: anti-loop пол
    # внутри compute_next_fire уже не даст частить. APScheduler примет run_date
    # в прошлом в пределах misfire_grace, но max(nxt, now) надёжнее.
    run_date = nxt if nxt > now else now
    sched.add_job(
        _logged_job(JOB_SPACE_RESTART, _space_restart_job),
        DateTrigger(run_date=run_date),
        id=JOB_SPACE_RESTART,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,  # рестарт не требует секундной точности
    )
    log.info(
        "scheduler.space_restart_armed",
        next_fire=run_date.isoformat(),
        mode=schedule["mode"],
    )


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    settings = get_settings()
    sched = get_scheduler()
    if sched.running:
        return sched

    # GHG6 AD6: chukhan/avatars/birthdays теперь регистрирует
    # `reload_dynamic_jobs` — респектят master-toggles из admin_config.
    # GHG8 G: proxy_health-tick теперь регистрируется условно — только в режиме
    # ALWAYS_ON (см. reschedule_proxy_health). Перевзвод после start (нужен
    # running sched + чтение режима из БД), рядом с reload_dynamic_jobs.

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
        # HOTFIX 2026-06-12: 5мин→12ч. Neon free-tier суспендится после 5мин
        # простоя; тик каждые 5мин = БД никогда не спит = выжигание compute.
        # Цена: выход из автопаузы теперь проверяется 2×/сутки (терпимо).
        IntervalTrigger(hours=12, jitter=300),
        id=JOB_BOT_PAUSE_AUTO_RESTORE,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,  # GHG6 H4: 10мин — пауза не требует секундной точности
    )

    # GHG7 P0.2.b.4: ретрай недоставленных автолох-постов. Тянем pending-записи
    # из loser_outbox и пробуем отправить заново. Не зависит от admin-config —
    # это infra-job, как proxy_health.
    # GHG7 P8.5: интервал 1мин → 5мин. Шаг ретрая (_AUTOLOSER_RETRY_DELAY) и так
    # 5 минут, поэтому ежеминутный тик 4 раза из 5 находил только записи с
    # next_retry_at в будущем и слал «пустой» SELECT в Neon (минус бюджет
    # compute) — а реальную попытку send делал всё равно раз в 5 мин. Согласуем
    # интервал с шагом ретрая: один осмысленный тик на окно.
    sched.add_job(
        _logged_job(JOB_LOSER_OUTBOX_RETRY, _loser_outbox_retry_job),
        # HOTFIX 2026-06-12: 5мин→12ч (тот же мотив, что у auto_restore выше —
        # не будить Neon). Цена: ретрай недоставленных лох-постов раз в 12ч.
        IntervalTrigger(hours=12, jitter=300),
        kwargs={"bot": bot},
        id=JOB_LOSER_OUTBOX_RETRY,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,  # GHG6 H4: 5 мин — таков же шаг ретрая
    )

    # GHG7 P11 (инцидент 03.06 #1): дотягиваем недоставленного чухана текущей
    # недели. Cron-ролл понедельника мог упасть в окно недоступности канала/Neon
    # (см. incidentlog.txt: connection reset, webhook.set_failed timeouts) —
    # раньше пик при этом откатывался (rollback) и не повторялся до след. недели.
    # Теперь announce_chukhan при фейле оставляет строку WeeklyChukhan с
    # posted_at IS NULL, а этот job находит её и добивает доставку тем же юзером
    # (идемпотентность pick_chukhan_for_week по week_start). Интервал 30 мин —
    # компромисс с бюджетом Neon: в обычном случае один дешёвый SELECT, который
    # ничего не находит (48/сутки vs 288 у loser_outbox). misfire_grace 30 мин —
    # скип-окно не требует секундной точности.
    async def _chukhan_retry_tick(*, bot: Bot) -> None:
        from app.services.chukhan import retry_undelivered_chukhan

        await retry_undelivered_chukhan(bot)

    sched.add_job(
        _logged_job(JOB_CHUKHAN_RETRY, _chukhan_retry_tick),
        # GHG8 G (03.07): 30мин→2ч. Ретрай нужен лишь в окно после недельного
        # ролла чухана (пн), 99% времени SELECT холостой (48→12/сутки в Neon).
        # Недоставленного чухана добьём в пределах 2ч — некритично.
        IntervalTrigger(hours=2, jitter=300),
        kwargs={"bot": bot},
        id=JOB_CHUKHAN_RETRY,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=7200,  # 2ч — скип чухана не критичен к секундам
    )

    # GHG8 P7: «мёртвый чат» — часовой тик проверки тишины. Master-toggle
    # (`dead_chat.enabled`) и пауза бота проверяются ВНУТРИ job'а, поэтому он
    # не участвует в reload_dynamic_jobs (как bot_pause_auto_restore). Дёшево
    # для Neon: 3–4 point-SELECT по admin_config в час; пост — редкое событие
    # (пороги от 24ч).
    async def _dead_chat_tick(*, bot: Bot) -> None:
        from app.services.dead_chat import run_dead_chat_job

        await run_dead_chat_job(bot)

    sched.add_job(
        _logged_job(JOB_DEAD_CHAT, _dead_chat_tick),
        # GHG8 G (03.07): 1ч→6ч. Порог тишины ≥24ч, поэтому часовой опрос
        # избыточен (24→4 тика/сутки в Neon); тишину суток ловим с запасом.
        IntervalTrigger(hours=6, jitter=600),
        kwargs={"bot": bot},
        id=JOB_DEAD_CHAT,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,  # тишина суток не требует точности
    )

    # GHG8 G (антиспам, заменил P14-поллинг): рестарт Space теперь событийный —
    # ОДИН DateTrigger на точное время следующего рестарта (`compute_next_fire`),
    # а не 5-мин поллинг (288 холостых SELECT/сутки → 0 в простое). Режим обычно
    # off/раз-в-неделю, поэтому job чаще всего не зарегистрирован вовсе.
    # Перевзвод — после start (sched должен быть running), рядом с
    # reload_dynamic_jobs.

    sched.start()
    log.info("scheduler.started", chukhan_cron=settings.chukhan_cron, tz=settings.scheduler_tz)

    # Динамические job'ы — после start, чтобы reload_dynamic_jobs мог
    # пересоздавать их через сам же sched (он уже running).
    import asyncio as _asyncio

    _asyncio.create_task(reload_dynamic_jobs(bot))
    # GHG8 G: событийный перевзвод one-shot рестарта Space (см.
    # reschedule_space_restart). Отдельная таска — не блокирует старт.
    _asyncio.create_task(reschedule_space_restart())
    # GHG8 G: условная регистрация proxy_health (только ALWAYS_ON).
    _asyncio.create_task(reschedule_proxy_health(bot))

    return sched


async def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")
    _scheduler = None
