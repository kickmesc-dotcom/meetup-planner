"""Э16 (H.8): ручной запуск мьюзик-гейма командой `/musicgame`.

Авто-вызов мьюзик-гейма — опция (по умолчанию выключена). Но ведущему удобно
иногда «выкинуть» раунд вручную; команда доступна только админам, чтобы опрос
«угадай, кто предложил трек» не превращался в спам.

Саму механику (выбор трека, опрос, закрытие) целиком делает сервис
`services.game.music_game` — здесь только проверка прав и ответ на неудачу.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

import structlog
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.services.game import music_game

log = structlog.get_logger()
router = Router()


@router.message(
    Command("musicgame"),
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
)
async def on_musicgame(message: Message) -> None:
    """Админ запускает раунд вручную: бот тянет случайный трек из предложки."""
    if message.from_user is None:
        return
    if message.from_user.id not in get_settings().admin_tg_id_set:
        return

    from app.bot.dispatcher import get_bot

    try:
        sm = get_sessionmaker()
        async with sm() as session:
            round_ = await music_game.open_round(
                session,
                get_bot(),
                now=datetime.now(timezone.utc),
                rng=random.Random(),
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("music_game.manual_failed", error=str(exc))
        await message.answer("🎵 Не получилось запустить мьюзик-гейм, попробуй позже.")
        return

    if round_ is None:
        await message.answer(
            "🎵 Пока не из чего выбирать: нужно минимум два участника с треками "
            "в предложке и хотя бы один не разыгранный трек."
        )
