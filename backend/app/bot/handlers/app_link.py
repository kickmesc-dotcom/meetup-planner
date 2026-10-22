"""`/app` — открыть приложение на компьютере.

Зачем команда. Мини-апп внутри Telegram Desktop живёт в узком окне, которое
клиент не даёт расширить программно. Широкая версия — это та же страница,
открытая в обычном браузере, но там нет `initData`, поэтому нужен вход по
ссылке. Команда выпускает такую ссылку и присылает кнопкой.

Правила доставки:
* ссылка показывается один раз и только в личке — в групповой чат секрет не
  отправляем;
* если человека ещё нет в базе (он ни разу не открывал мини-апп), честно
  просим сначала зайти через кнопку меню: сервер сам заведёт профиль.

Отзыв — в профиле приложения («Веб-версия») или повторный выпуск новой ссылки:
старые сверх лимита отзываются автоматически.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import User
from app.services import app_access

router = Router()


@router.message(Command("app"))
async def on_app(message: Message) -> None:
    if message.from_user is None:
        return
    if message.chat.type != ChatType.PRIVATE:
        # В общем чате ссылка = пароль: не светим её перед коллегами.
        await message.reply("Ссылку для входа с компьютера пришлю в личку — напиши мне /app там.")
        return

    settings = get_settings()
    async with get_sessionmaker()() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if user is None:
            await message.answer(
                "Сначала открой приложение кнопкой меню — я заведу твой профиль. "
                "После этого /app выдаст ссылку для компьютера."
            )
            return
        link, token = await app_access.issue(
            session,
            user=user,
            mini_app_url=settings.mini_app_url,
        )

    url = app_access.build_url(settings.mini_app_url, token)
    if not url:
        await message.answer(
            "Не настроен адрес приложения (MINI_APP_URL) — ссылку собрать не из чего."
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть на компьютере", url=url)]]
    )
    await message.answer(
        "🖥 <b>Веб-версия для компьютера</b>\n\n"
        "Открой ссылку в браузере — там широкий экран с разделами, как в "
        "админ-панели.\n\n"
        f"Ссылка действует до {link.expires_at:%d.%m.%Y} и работает как пароль: "
        "не пересылай её другим. Отозвать можно в профиле приложения, раздел "
        "«Веб-версия».",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )
