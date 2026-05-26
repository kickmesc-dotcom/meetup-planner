"""GHG6 G2 — безопасное закрепление сообщений в чате.

`bot.pin_chat_message` может упасть по сети/таймауту/правам (бот не админ,
бот не может пинить, etc.). Все эти ошибки — не повод валить вызывающий
поток: опрос (или любое другое сообщение) уже опубликован, пин — это
nice-to-have поверх. Поэтому ошибки глотаем в warning, возвращаем bool.

Таймаут жёсткий (5с) — пин-эндпоинт обычно отвечает мгновенно; долгое
зависание = проблемы с прокси, нет смысла блокировать ASGI-роут.
"""
from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

log = structlog.get_logger()

_PIN_TIMEOUT_SEC = 5.0


async def pin_message_safely(
    bot: Bot,
    chat_id: int,
    message_id: int,
    *,
    disable_notification: bool = True,
) -> bool:
    """Закрепить сообщение, проглотив все Telegram-ошибки.

    Возвращает True при успехе, False — иначе. Логирует warning с типом
    ошибки. `disable_notification=True` по умолчанию, чтобы пин не звенел
    у всех (для опросов это обычно не нужно — авто-пост опроса и так
    шумит).
    """
    try:
        await asyncio.wait_for(
            bot.pin_chat_message(
                chat_id=chat_id,
                message_id=message_id,
                disable_notification=disable_notification,
            ),
            timeout=_PIN_TIMEOUT_SEC,
        )
        return True
    except (
        TelegramRetryAfter,
        TelegramForbiddenError,
        TelegramNetworkError,
        TelegramAPIError,
        asyncio.TimeoutError,
    ) as exc:
        log.warning(
            "pin.failed",
            error=str(exc),
            error_type=type(exc).__name__,
            chat_id=chat_id,
            message_id=message_id,
        )
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "pin.unexpected",
            error=str(exc),
            error_type=type(exc).__name__,
            chat_id=chat_id,
            message_id=message_id,
        )
        return False
