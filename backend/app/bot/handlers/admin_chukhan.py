from __future__ import annotations

import structlog
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

# Импорт get_bot удален отсюда, чтобы избежать циклической ошибки
from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import User, WeeklyChukhan
from app.services.chukhan import announce_chukhan, current_week_start

log = structlog.get_logger()
router = Router()


def _is_admin(tg_id: int) -> bool:
    return tg_id in get_settings().admin_tg_id_set


@router.message(Command("forcechukhan"))
async def on_force_chukhan(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    
    # Импортируем get_bot прямо здесь, когда функция уже вызвана
    from app.bot.dispatcher import get_bot
    
    sm = get_sessionmaker()
    async with sm() as session:
        ws = current_week_start()
        existing = await session.scalar(
            select(WeeklyChukhan).where(WeeklyChukhan.week_start == ws)
        )
        if existing is not None:
            await session.delete(existing)
            await session.commit()
        
        # Теперь передаем вызванный get_bot()
        row = await announce_chukhan(get_bot(), session)
        
    if row is None:
        await message.answer("⚠️ GROUP_CHAT_ID не настроен.")
    else:
        await message.answer("✅ Чухан перевыбран и отправлен в чат.")


@router.message(Command("chukhan"))
async def on_show_chukhan(message: Message) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        ws = current_week_start()
        row = await session.scalar(
            select(WeeklyChukhan).where(WeeklyChukhan.week_start == ws)
        )
        if row is None:
            await message.answer("На этой неделе чухан ещё не назначен.")
            return
        user = await session.get(User, row.user_id)
    name = user.display_name if user else "???"
    await message.answer(f"💩 Чухан этой недели: <b>{name}</b>", parse_mode="HTML")