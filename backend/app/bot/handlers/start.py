from __future__ import annotations

import structlog
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy import select

# Импорт get_bot удален отсюда для предотвращения Circular Import
from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import User
from app.services.avatars import sync_user_avatar

log = structlog.get_logger()
router = Router()


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    settings = get_settings()
    if message.from_user:
        # Локальный импорт внутри функции
        from app.bot.dispatcher import get_bot
        
        try:
            sm = get_sessionmaker()
            async with sm() as session:
                user = (
                    await session.scalars(
                        select(User).where(User.telegram_id == message.from_user.id)
                    )
                ).first()
                if user:
                    # Передаем результат вызова функции
                    await sync_user_avatar(session, get_bot(), user)
        except Exception as exc:  # noqa: BLE001
            log.warning("start.avatar_sync_failed", error=str(exc))

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📅 Открыть планер",
                    web_app=WebAppInfo(url=settings.mini_app_url),
                )
            ]
        ]
    )
    await message.answer(
        "Привет! Это планер встреч для нашей шестёрки.\n"
        "Жми кнопку, чтобы открыть календарь — там разметишь свободные/занятые дни, "
        "посмотришь когда могут собраться остальные.\n\n"
        "/whoami — узнать свой Telegram ID (нужно админу для добавления в список).",
        reply_markup=kb,
    )