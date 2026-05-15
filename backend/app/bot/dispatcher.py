from __future__ import annotations

import os
import socket

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from app.bot.handlers import (
    admin_chukhan,
    chat_capture,
    chat_commands,
    next_meeting,
    poll_answer,
    start,
    whoami,
)
from app.config import get_settings

_bot: Bot | None = None
_dispatcher: Dispatcher | None = None


def _env_truthy(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


class _IPv4AiohttpSession(AiohttpSession):
    """aiogram session that pins outbound traffic to IPv4.

    Hugging Face Spaces frequently fails to reach api.telegram.org over IPv6
    (timeouts, address-not-routable). Forcing AF_INET fixes it without
    blocking the event loop or fiddling with DNS overrides.
    """

    async def create_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                family=socket.AF_INET,
                ssl=True,
                ttl_dns_cache=300,
                limit=20,
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                trust_env=True,
            )
        return self._session


def _build_session() -> AiohttpSession | None:
    """Return a session that forces IPv4, or None to use aiogram default.

    aiogram 3.13 expects a numeric `timeout` (seconds, float) on the session;
    it is passed straight to `aiohttp.ClientSession.post(timeout=...)` per call.
    30 s total is enough for Telegram and short enough to fail fast on HF.
    """
    if not _env_truthy("BOT_FORCE_IPV4", True):
        return None
    return _IPv4AiohttpSession(timeout=30.0)


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        settings = get_settings()
        token = settings.bot_token

        # Token may be SecretStr in future config; keep the guard.
        if hasattr(token, "get_secret_value"):
            token = token.get_secret_value()

        session = _build_session()
        kwargs: dict = {
            "token": str(token),
            "default": DefaultBotProperties(parse_mode=ParseMode.HTML),
        }
        if session is not None:
            kwargs["session"] = session

        _bot = Bot(**kwargs)
    return _bot


def get_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = Dispatcher()
        _dispatcher.include_router(start.router)
        _dispatcher.include_router(whoami.router)
        _dispatcher.include_router(poll_answer.router)
        _dispatcher.include_router(admin_chukhan.router)
        _dispatcher.include_router(next_meeting.router)
        _dispatcher.include_router(chat_commands.router)
        _dispatcher.include_router(chat_capture.router)
    return _dispatcher
