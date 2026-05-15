from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("whoami"))
async def on_whoami(message: Message) -> None:
    if message.from_user is None:
        return
    u = message.from_user
    full = " ".join(p for p in (u.first_name, u.last_name) if p)
    await message.answer(
        f"Твой Telegram ID: <code>{u.id}</code>\n"
        f"Имя: {full}\n"
        f"Username: @{u.username if u.username else '—'}\n\n"
        "Скинь этот ID админу, чтобы он добавил тебя в список шестёрки."
    )
