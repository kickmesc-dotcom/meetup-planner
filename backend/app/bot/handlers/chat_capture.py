"""Захват текстовых сообщений из общей группы для будущих «рандомных фраз».

Сохраняем только текст из `settings.group_chat_id`, только от известных юзеров
(в whitelist). Храним сообщения только за последние 7 дней.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy import delete, select

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import ChatMessage, User

log = structlog.get_logger()
router = Router()

# Настройка горизонта памяти
RETENTION_DAYS = 7


async def cleanup_old_messages(session) -> None:
    """Удаляет сообщения старше RETENTION_DAYS из всей таблицы.

    GHG7 P0.3: используем aware UTC (`datetime.now(timezone.utc)`), а не
    naive `utcnow()`. `ChatMessage.sent_at` — `TIMESTAMP WITH TIME ZONE`,
    и сравнение naive vs timestamptz Postgres интерпретирует как локальное
    время сервера. На HF Space TZ обычно UTC и баг не проявлялся, но
    рассинхрон с reader'ами (`random_phrases.py`, `routes_admin.get_rp_pool`),
    которые уже используют aware UTC, делал чистку латентно-хрупкой.
    """
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    try:
        await session.execute(
            delete(ChatMessage).where(ChatMessage.sent_at < cutoff_date)
        )
        await session.commit()
    except Exception as exc:
        log.warning("chat_capture.cleanup_failed", error=str(exc))


@router.message(F.text & ~F.text.startswith("/"))
async def on_group_message(message: Message) -> None:
    settings = get_settings()
    
    # Проверка на правильный чат
    if not settings.group_chat_id or message.chat.id != settings.group_chat_id:
        return
    if not message.from_user or message.from_user.is_bot:
        return
    if not message.text or not message.text.strip():
        return

    user_pk: int | None = None
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            # Проверяем, есть ли юзер в нашей базе (whitelist)
            user = await session.scalar(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            if user is None:
                return  # игнорим чужаков

            # Сохраняем новое сообщение
            session.add(
                ChatMessage(
                    chat_id=message.chat.id,
                    tg_message_id=message.message_id,
                    user_id=user.id,
                    text=message.text[:2000].strip(),
                    sent_at=message.date,
                )
            )
            await session.commit()

            # Сразу после записи чистим хвосты за прошлую неделю
            # Это держит базу в идеальном тонусе
            await cleanup_old_messages(session)
            user_pk = user.id

        # GHG8 P7: текст от участника = чат жив. Внутри — троттлинг 15 мин
        # и best-effort, сюда исключения не долетают.
        from app.services.dead_chat import touch_chat_activity

        await touch_chat_activity(message.date)

        # GHG10 (2.1): «сообщение = 1 XP» + durable счётчик активности.
        # Через фасад `awards`: он сам проверяет рубильник `game.enabled`
        # (при выключенной игре — один дешёвый SELECT и выход) и пишет оба
        # изменения ОДНИМ commit'ом. Порядок важен: сообщение в `chat_messages`
        # уже закоммичено, поэтому сбой игры не может стоить нам сообщения.
        if user_pk is not None:
            from app.services.game import awards

            async with sm() as gsession:
                await awards.message(gsession, user_pk, at=message.date)

            # GHG10 Э7: сообщение может быть откликом на мем — reply на пост
            # или «ответ сразу под постом». Своя сессия и best-effort: телеметрия
            # не имеет права стоить нам самого сообщения (как и опыт — порядок
            # «сначала факт, потом игра» соблюдён).
            from app.services.game import memes

            reply_to = (
                message.reply_to_message.message_id
                if message.reply_to_message is not None
                else None
            )
            try:
                async with sm() as msession:
                    await memes.record_message_response(
                        msession,
                        chat_id=message.chat.id,
                        telegram_id=message.from_user.id,
                        at=message.date,
                        reply_to_tg_message_id=reply_to,
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("chat_capture.game_response_failed", error=str(exc))

    except Exception as exc:  # noqa: BLE001
        log.warning("chat_capture.failed", error=str(exc))