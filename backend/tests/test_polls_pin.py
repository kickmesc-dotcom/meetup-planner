"""GHG6 G2 — `pin_message_safely`: ошибки глотает, по умолчанию disable_notification.

Юнит-тест на чистую обёртку. Интеграция с `create_poll_in_chat` /
`create_game_choice_poll` (где обёртка зовётся при pin=True) проверяется руками
при первом релизе — отдельный sqlite-стенд для async-сервисов в проект не тащим.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

from app.bot.utils.pinning import pin_message_safely


def _make_bot(side_effect=None, return_value=None) -> MagicMock:
    bot = MagicMock()
    bot.pin_chat_message = AsyncMock(
        side_effect=side_effect, return_value=return_value
    )
    return bot


@pytest.mark.asyncio
async def test_pin_success_returns_true():
    bot = _make_bot(return_value=True)
    ok = await pin_message_safely(bot, chat_id=123, message_id=456)
    assert ok is True
    bot.pin_chat_message.assert_awaited_once()
    # disable_notification по умолчанию True
    kwargs = bot.pin_chat_message.await_args.kwargs
    assert kwargs.get("disable_notification") is True
    assert kwargs.get("chat_id") == 123
    assert kwargs.get("message_id") == 456


@pytest.mark.asyncio
async def test_pin_disable_notification_overridable():
    bot = _make_bot(return_value=True)
    ok = await pin_message_safely(
        bot, chat_id=1, message_id=2, disable_notification=False
    )
    assert ok is True
    assert bot.pin_chat_message.await_args.kwargs.get("disable_notification") is False


@pytest.mark.asyncio
async def test_pin_swallows_forbidden():
    # Используем самую обычную форму конструктора — aiogram-исключения
    # принимают `method`/`message` в разных версиях. Передаём минимально.
    bot = _make_bot(side_effect=TelegramForbiddenError(method=None, message="no rights"))
    ok = await pin_message_safely(bot, chat_id=1, message_id=2)
    assert ok is False


@pytest.mark.asyncio
async def test_pin_swallows_api_error():
    bot = _make_bot(side_effect=TelegramAPIError(method=None, message="bad"))
    ok = await pin_message_safely(bot, chat_id=1, message_id=2)
    assert ok is False


@pytest.mark.asyncio
async def test_pin_swallows_network():
    bot = _make_bot(side_effect=TelegramNetworkError(method=None, message="oops"))
    ok = await pin_message_safely(bot, chat_id=1, message_id=2)
    assert ok is False


@pytest.mark.asyncio
async def test_pin_swallows_retry_after():
    bot = _make_bot(
        side_effect=TelegramRetryAfter(method=None, message="flood", retry_after=30)
    )
    ok = await pin_message_safely(bot, chat_id=1, message_id=2)
    assert ok is False


@pytest.mark.asyncio
async def test_pin_swallows_timeout():
    async def slow(*_a, **_k):
        await asyncio.sleep(10.0)

    bot = MagicMock()
    bot.pin_chat_message = slow
    # Внутри pin_message_safely стоит asyncio.wait_for(timeout=5) — но для
    # ускорения теста подменяем глобальный timeout через monkeypatch не будем,
    # просто проверим, что любой timeout-сценарий не валит вызов. Заменяем
    # на немедленный TimeoutError через AsyncMock:
    bot.pin_chat_message = AsyncMock(side_effect=asyncio.TimeoutError())
    ok = await pin_message_safely(bot, chat_id=1, message_id=2)
    assert ok is False


@pytest.mark.asyncio
async def test_pin_swallows_unexpected_exception():
    """Любой другой Exception — не вылетает наружу."""
    bot = _make_bot(side_effect=RuntimeError("boom"))
    ok = await pin_message_safely(bot, chat_id=1, message_id=2)
    assert ok is False
