"""Чат-команда `/changelog`: что нового, обычными словами.

Почему не «вот список коммитов». Коммит пишется для разработчика: `fix(ui):
шапка и вкладки на узком экране` сотруднику ничего не говорит. Поэтому текст
сначала проходит адаптацию (редакторскую или автоматическую) и только потом
попадает в чат — см. `services/changelog.py`. Здесь только доставка.

Команда открыта всем, кто пишет боту: это история продукта, а не внутренняя
кухня. Сеть (GitHub) может быть недоступна — тогда сервис отдаёт то, что уже
описано вручную, и честно об этом пишет.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.services.changelog import build_changelog, render_changelog

router = Router()


@router.message(Command("changelog"))
async def on_changelog(message: Message) -> None:
    view = await build_changelog()
    text = render_changelog(view)
    await message.reply(text, parse_mode="HTML", disable_web_page_preview=True)
