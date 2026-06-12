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
    _resolve_api_server,
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
async def test_session_uses_flat_timeout(monkeypatch):
    # HOTFIX 2026-06-12: Q-NET.b ставил ClientTimeout(total=25, sock_connect=8);
    # sock_connect=8 рубил TLS-handshake к Telegram под РКН-throttling и ослепил
    # прод (100% исходящих → timeout). Откатили на плоский float-таймаут (как до
    # f629fa0). aiogram передаёт его в session.post(timeout=...) как число.
    monkeypatch.delenv("BOT_TOTAL_TIMEOUT", raising=False)
    monkeypatch.setenv("BOT_FORCE_IPV4", "true")
    s = _build_session()
    try:
        assert s.timeout == 30.0
    finally:
        await s.close()

    monkeypatch.setenv("BOT_TOTAL_TIMEOUT", "40")
    s2 = _build_session()
    try:
        assert s2.timeout == 40.0
    finally:
        await s2.close()


# --- BOT_API_SERVER: кастомный реверс-прокси (инцидент 12.06) ---
# Корень «бот молчал 2 дня»: Bot(server=...) МОЛЧА игнорируется в aiogram 3.x —
# server проваливается в **kwargs. Кастомный сервер задаётся ТОЛЬКО на сессии
# (BaseSession(api=...)). Эти тесты пинят, что api реально доходит до сессии и
# собранный URL указывает на воркер, а не на api.telegram.org.

def test_api_server_unset_is_none(monkeypatch):
    monkeypatch.delenv("BOT_API_SERVER", raising=False)
    assert _resolve_api_server() is None


def test_api_server_resolves_from_env(monkeypatch):
    monkeypatch.setenv("BOT_API_SERVER", "https://telegram-proxy.kickmesc.workers.dev")
    api = _resolve_api_server()
    assert api is not None
    assert api.base == "https://telegram-proxy.kickmesc.workers.dev/bot{token}/{method}"


def test_api_server_blank_is_none(monkeypatch):
    monkeypatch.setenv("BOT_API_SERVER", "   ")
    assert _resolve_api_server() is None


@pytest.mark.asyncio
async def test_session_carries_custom_api(monkeypatch):
    # Главное: api долетает до session.api, а не теряется (как было с
    # Bot(server=...)). Собранный URL должен бить в воркер.
    monkeypatch.setenv("BOT_API_SERVER", "https://telegram-proxy.kickmesc.workers.dev")
    monkeypatch.setenv("BOT_FORCE_IPV4", "true")
    s = _build_session()
    try:
        url = s.api.api_url(token="123:abc", method="getMe")
        assert url.startswith("https://telegram-proxy.kickmesc.workers.dev/")
        assert "api.telegram.org" not in url
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_session_default_api_is_telegram(monkeypatch):
    # Без BOT_API_SERVER сессия ходит напрямую (дефолт aiogram).
    monkeypatch.delenv("BOT_API_SERVER", raising=False)
    monkeypatch.setenv("BOT_FORCE_IPV4", "true")
    s = _build_session()
    try:
        url = s.api.api_url(token="123:abc", method="getMe")
        assert "api.telegram.org" in url
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
