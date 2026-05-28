from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    MenuButtonWebApp,
    WebAppInfo,
)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_admin,
    routes_availability,
    routes_birthdays,
    routes_calendar,
    routes_meetings,
    routes_polls,
    routes_users,
)
from app.bot import webhook as bot_webhook
from app.bot.dispatcher import get_bot
from app.bot.scheduler import shutdown_scheduler, start_scheduler
from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.seed import seed_users
# Импорт sync_all_avatars остается, но вызов ниже закомментирован
from app.services.avatars import sync_all_avatars

def _configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper())
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )

async def _register_bot_metadata() -> None:
    settings = get_settings()
    bot = get_bot()
    # GHG6 K2-bis: список команд берём из единого каталога commands_catalog.py.
    # Описания в Telegram-menu и в /help теперь не расходятся.
    from app.bot.commands_catalog import bot_commands_for_scope

    private_cmds = [
        BotCommand(command=c.cmd, description=c.desc_ru)
        for c in bot_commands_for_scope("private")
    ]
    group_cmds = [
        BotCommand(command=c.cmd, description=c.desc_ru)
        for c in bot_commands_for_scope("group")
    ]
    try:
        # Устанавливаем команды с коротким таймаутом
        await bot.set_my_commands(private_cmds, scope=BotCommandScopeAllPrivateChats(), request_timeout=10)
        await bot.set_my_commands(group_cmds, scope=BotCommandScopeAllGroupChats(), request_timeout=10)
        # GHG7 P1.3: чтобы в нашем основном чате Telegram не дописывал
        # `@gunghogunsbot` к каждой команде в autocomplete, ставим
        # команды дополнительно прицельно на `group_chat_id` через
        # BotCommandScopeChat. У TG приоритет scope'ов: специфический
        # (Chat) перекрывает общий (AllGroupChats), и в этом конкретном
        # чате TG считает команды «однозначно нашими» — не клеит суффикс.
        # Для других group chat'ов (если бот когда-нибудь окажется в
        # ещё одной группе) остаётся AllGroupChats-fallback.
        if settings.group_chat_id:
            await bot.set_my_commands(
                group_cmds,
                scope=BotCommandScopeChat(chat_id=settings.group_chat_id),
                request_timeout=10,
            )
    except Exception as exc:  # noqa: BLE001
        structlog.get_logger().warning("bot.set_commands_failed", error=str(exc))

    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="📅 Планер",
                web_app=WebAppInfo(url=settings.mini_app_url),
            ),
            request_timeout=10
        )
    except Exception as exc:  # noqa: BLE001
        structlog.get_logger().warning("bot.set_menu_button_failed", error=str(exc))

async def _set_webhook() -> None:
    settings = get_settings()
    if not settings.public_base_url:
        structlog.get_logger().warning("webhook.skip_no_public_base_url")
        return
    url = f"{settings.public_base_url.rstrip('/')}/tg/webhook"
    bot = get_bot()
    await bot.set_webhook(
        url=url,
        secret_token=settings.tg_webhook_secret,
        allowed_updates=["message", "callback_query", "poll_answer"],
        drop_pending_updates=False,
        request_timeout=20,
    )
    structlog.get_logger().info("webhook.set", url=url)


async def _register_telegram_metadata_with_retry() -> None:
    """Background task: set webhook + commands + menu button, retrying on
    transient network failures so a flaky HF egress doesn't permanently
    leave the bot unconfigured. Each attempt is wrapped in its own
    try/except so a single failure never bubbles up.
    """
    log = structlog.get_logger()
    backoff = 5
    for attempt in range(1, 7):  # ~5+10+20+40+80+160s ≈ 5min total
        webhook_ok = False
        try:
            await _set_webhook()
            webhook_ok = True
        except Exception as exc:  # noqa: BLE001
            log.warning("webhook.set_failed", attempt=attempt, error=str(exc))

        try:
            await _register_bot_metadata()
        except Exception as exc:  # noqa: BLE001
            log.warning("bot.metadata_failed", attempt=attempt, error=str(exc))

        if webhook_ok:
            return
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 160)
    log.error("tg.registration_gave_up")

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(settings.log_level)
    
    # 1. Сидинг пользователей (Локальная операция с БД)
    sm = get_sessionmaker()
    async with sm() as session:
        await seed_users(session)
        # P2: bootstrap proxy pool из env (PROXIES_BOOTSTRAP_JSON), если задан.
        try:
            from app.services.proxies import bootstrap_from_env
            await bootstrap_from_env(session)
        except Exception as exc:  # noqa: BLE001
            structlog.get_logger().warning("proxy.bootstrap_failed", error=str(exc))
        
        # РЕЗЕРВНЫЙ ШАГ: Синхронизация аватарок отключена для ускорения запуска
        # try:
        #     await sync_all_avatars(session, get_bot())
        # except Exception as exc:
        #     structlog.get_logger().warning("avatars.startup_sync_failed", error=str(exc))

    # 2. Сетевые операции (Telegram) уходят в фон с ретраями, чтобы лагающая
    # сеть HF не блокировала FastAPI startup и первый входящий webhook.
    tg_task = asyncio.create_task(_register_telegram_metadata_with_retry())

    # 3. Планировщик стартует независимо от состояния сети.
    try:
        start_scheduler(get_bot())
    except Exception as exc:  # noqa: BLE001
        structlog.get_logger().warning("scheduler.start_failed", error=str(exc))

    yield

    # Завершение: гасим фоновую регистрацию, если она ещё бежит.
    tg_task.cancel()
    try:
        await tg_task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass

    await shutdown_scheduler()
    bot = get_bot()
    await bot.session.close()

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Meetup Planner", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(bot_webhook.router)
    app.include_router(routes_users.router, prefix="/api")
    app.include_router(routes_availability.router, prefix="/api")
    app.include_router(routes_meetings.router, prefix="/api")
    app.include_router(routes_polls.router, prefix="/api")
    app.include_router(routes_birthdays.router, prefix="/api")
    app.include_router(routes_calendar.router, prefix="/api")
    app.include_router(routes_admin.router, prefix="/api")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app

app = create_app()