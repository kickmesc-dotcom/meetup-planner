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
            # Запоминаем имя здесь: после commit'а атрибуты истекли, а сессия
            # уже закрыта — снаружи `user.display_name` бросил бы исключение.
            user_name = user.display_name

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

            # GHG10 Э13: «социальный» слой — возвращение из поминовения, ответ
            # на случайное событие и контрабанда слов. Одна общая сессия и
            # строго best-effort: ни одна из трёх фич не имеет права стоить нам
            # самого сообщения или опыта за него.
            from app.services.game import contraband, events, memorial

            try:
                async with sm() as ssession:
                    await memorial.note_return(ssession, user_id=user_pk, at=message.date)
                    await events.try_answer(
                        ssession,
                        chat_id=message.chat.id,
                        telegram_id=message.from_user.id,
                        text=message.text,
                        has_media=False,
                        at=message.date,
                    )
                    await contraband.scan(
                        ssession,
                        author_id=user_pk,
                        author_name=user_name,
                        text=message.text,
                        at=message.date,
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("chat_capture.game_social_failed", error=str(exc))

            # Э19: подтверждение передачи червя — господин отвечает «да»/«нет».
            # Обрабатываем ПОСЛЕДНИМ и в своей сессии: трансфер может закрыть
            # текущее звание и создать новое, это не должно смешиваться с
            # социальным блоком выше.
            from app.services.game import worm_transfer

            try:
                async with sm() as tsession:
                    outcome = await worm_transfer.consume_confirmation(
                        tsession,
                        author_user_id=user_pk,
                        text=message.text,
                        chat_id=message.chat.id,
                        at=message.date,
                    )
                    if outcome is not None:
                        await worm_transfer.apply(tsession, outcome)
            except Exception as exc:  # noqa: BLE001
                log.warning("chat_capture.worm_transfer_failed", error=str(exc))

    except Exception as exc:  # noqa: BLE001
        log.warning("chat_capture.failed", error=str(exc))


@router.message(F.photo | F.sticker | F.animation | F.video)
async def on_group_media(message: Message) -> None:
    """Медиа в общем чате — единственный вход для «скинь мем» (Э13).

    Текст хендлера выше медиа не ловит, а призыв «скинь любимый мем» обязан
    засчитываться по самому факту картинки. Ничего не сохраняем (в отличие от
    текста): нам нужен только ответ на открытый промпт.
    """
    settings = get_settings()
    if not settings.group_chat_id or message.chat.id != settings.group_chat_id:
        return
    if not message.from_user or message.from_user.is_bot:
        return
    from app.services.game import events

    try:
        sm = get_sessionmaker()
        async with sm() as session:
            user_pk = await session.scalar(
                select(User.id).where(User.telegram_id == message.from_user.id)
            )
            if user_pk is None:
                return
            await events.try_answer(
                session,
                chat_id=message.chat.id,
                telegram_id=message.from_user.id,
                text=None,
                has_media=True,
                at=message.date,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("chat_capture.game_media_failed", error=str(exc))