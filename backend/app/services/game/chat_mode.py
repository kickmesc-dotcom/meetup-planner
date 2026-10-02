"""Э20: режим вывода бота в основной чат — одна дверь для проверки.

Два софт-режима приглушения (`game.chat.output_mode`):

* ``normal``       — как было, всё пишется в чат;
* ``achievements`` — РЕЖИМ 1: анонсы ачивок уезжают в ленту мини-аппа;
* ``all``          — РЕЖИМ 2: вся проактивная активность уезжает в ленту, в чат
                     бот молчит (кроме ответов на команды/@-упоминания и
                     напоминаний, инициированных человеком).

Почему отдельный модуль, а не функция в `journal`: `journal` в тестах часто
подменяют фейком (без новых методов), а проверку режима хотят все сервисы
(чухан, музыка, голосовые, случайные фразы). Отдельный модуль не ломает фейки
и держит одно чтение конфига в одном месте.

Любой сбой чтения (нет сессии, тестовая fake-сессия без `admin_config`) —
безопасный ``normal``: лучше показать сообщение в чате, чем молча потерять его.
"""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.admin_config import get_chat_output_mode

log = structlog.get_logger()

MODE_NORMAL = "normal"
MODE_ACHIEVEMENTS = "achievements"
MODE_ALL = "all"

# Виды анонсов, которые в режиме 1 не имеют права попасть в чат.
ACHIEVEMENT_SILENT_KINDS = ("achievement", "achievement_pool")


async def get_chat_mode(session: AsyncSession | None) -> str:
    """Прочитать режим. Без сессии — откроем короткую; при ошибке — `normal`."""
    try:
        if session is not None:
            return await get_chat_output_mode(session)
        from app.db.base import get_sessionmaker

        sm = get_sessionmaker()
        async with sm() as own:
            return await get_chat_output_mode(own)
    except Exception as exc:  # noqa: BLE001
        log.warning("game.chat_mode_read_failed", error=str(exc))
        return MODE_NORMAL


async def chat_all_silent(session: AsyncSession | None) -> bool:
    """True, если активен режим 2 — вся проактивная активность в приложении."""
    return await get_chat_mode(session) == MODE_ALL


async def achievements_silent(session: AsyncSession | None) -> bool:
    """True, если анонсы ачивок в чат запрещены (режим 1 или 2)."""
    return await get_chat_mode(session) in (MODE_ACHIEVEMENTS, MODE_ALL)
