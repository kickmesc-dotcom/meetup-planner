"""GHG8 Q-NET.b: таймауты и пул соединений у бот-сессии.

Async-БД-стенда нет (зафиксированное ограничение) — кроем чистые резолверы
env и конструирование коннектора/сессии (без сети к Telegram). Проверяем,
что:
- дефолты совпадают с планом (keepalive 15, total 25, sock_connect 8,
  force_close off);
- env-override применяется;
- force_close=true НЕ передаёт keepalive (иначе aiohttp кидает ValueError);
- direct- и proxy-коннектор и сессия конструируются и закрываются без ошибок.
"""
from __future__ import annotations

import aiohttp
import pytest

from app.bot.dispatcher import (
    _build_session,
    _make_direct_connector,
    _make_proxy_connector,
    _pool_connector_kwargs,
    _resolve_force_close,
    _resolve_keepalive_timeout,
    _resolve_timeouts,
)


# --- резолверы env: дефолты ---

def test_defaults(monkeypatch):
    for k in (
        "BOT_KEEPALIVE_TIMEOUT",
        "BOT_FORCE_CLOSE",
        "BOT_TOTAL_TIMEOUT",
        "BOT_SOCK_CONNECT_TIMEOUT",
    ):
        monkeypatch.delenv(k, raising=False)
    assert _resolve_keepalive_timeout() == 15.0
    assert _resolve_force_close() is False
    assert _resolve_timeouts() == (25.0, 8.0)
    assert _pool_connector_kwargs() == {"keepalive_timeout": 15.0}


# --- резолверы env: override ---

def test_env_override(monkeypatch):
    monkeypatch.setenv("BOT_KEEPALIVE_TIMEOUT", "30")
    monkeypatch.setenv("BOT_TOTAL_TIMEOUT", "40")
    monkeypatch.setenv("BOT_SOCK_CONNECT_TIMEOUT", "12")
    monkeypatch.setenv("BOT_FORCE_CLOSE", "false")
    assert _resolve_keepalive_timeout() == 30.0
    assert _resolve_timeouts() == (40.0, 12.0)
    assert _resolve_force_close() is False
    assert _pool_connector_kwargs() == {"keepalive_timeout": 30.0}


def test_bad_int_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("BOT_KEEPALIVE_TIMEOUT", "не-число")
    monkeypatch.setenv("BOT_TOTAL_TIMEOUT", "")
    assert _resolve_keepalive_timeout() == 15.0
    assert _resolve_timeouts()[0] == 25.0


# --- force_close: keepalive НЕ передаётся (aiohttp ValueError guard) ---

def test_force_close_omits_keepalive(monkeypatch):
    monkeypatch.setenv("BOT_FORCE_CLOSE", "true")
    assert _resolve_force_close() is True
    kwargs = _pool_connector_kwargs()
    assert kwargs == {"force_close": True}
    assert "keepalive_timeout" not in kwargs


# --- конструирование коннекторов/сессии (под event loop) ---

@pytest.mark.asyncio
async def test_direct_connector_builds(monkeypatch):
    monkeypatch.delenv("BOT_FORCE_CLOSE", raising=False)
    monkeypatch.delenv("BOT_KEEPALIVE_TIMEOUT", raising=False)
    c = _make_direct_connector()
    try:
        assert c._keepalive_timeout == 15.0
        assert c._force_close is False
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_direct_connector_force_close_builds(monkeypatch):
    monkeypatch.setenv("BOT_FORCE_CLOSE", "true")
    # Главное — НЕ ловим ValueError «keepalive_timeout cannot be set if
    # force_close is True».
    c = _make_direct_connector()
    try:
        assert c._force_close is True
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_session_uses_granular_timeout(monkeypatch):
    monkeypatch.delenv("BOT_TOTAL_TIMEOUT", raising=False)
    monkeypatch.delenv("BOT_SOCK_CONNECT_TIMEOUT", raising=False)
    monkeypatch.setenv("BOT_FORCE_IPV4", "true")
    s = _build_session()
    try:
        assert isinstance(s.timeout, aiohttp.ClientTimeout)
        assert s.timeout.total == 25.0
        assert s.timeout.sock_connect == 8.0
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_proxy_connector_gets_pool_opts(monkeypatch):
    monkeypatch.delenv("BOT_FORCE_CLOSE", raising=False)

    class _Rec:
        type = "socks5"
        server = "1.2.3.4"
        port = 1080
        secret = None

    c = _make_proxy_connector(_Rec())
    if c is None:
        pytest.skip("aiohttp_socks недоступен в окружении")
    try:
        assert c._keepalive_timeout == 15.0
        assert c._force_close is False
    finally:
        await c.close()
