"""Э14: приём голосовых сообщений для заданий.

Два пути сдачи, как в задании:

* **реплай** на сообщение-задание в общем чате (только реплай — иначе бот
  ловил бы вообще любое голосовое);
* **личка** боту: в личке задание одно (последнее открытое), поэтому реплай не
  нужен.

Роутер подключается ПОСЛЕ `media_reactions`: тот матчит `F.voice` как «медиа» и
завершается `raise SkipHandler`, поэтому телеметрия мемов не ломается, а наш
хендлер всё равно получает апдейт. Ломать нельзя: голосовуха-первым-сообщением
в мем-механике — валидный кейс.
"""
from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.services.game import voice

log = structlog.get_logger()
router = Router()


async def _answer(message: Message, res: voice.SubmitResult, *, private: bool) -> None:
    """Ответить на сдачу. Тексты короткие: это подтверждение, а не отчёт."""
    try:
        if res.status == voice.OK:
            await message.reply(
                f"🎙 Принято, <b>{res.name or 'участник'}</b>! +{res.reward} XP.",
                parse_mode="HTML",
            )
        elif res.status == voice.ALREADY:
            await message.reply("Этот вариант уже принят — один на участника.")
        elif res.status == voice.CLOSED:
            await message.reply("Задание уже закрыто, жди следующее.")
        elif private and res.status == voice.NO_TASK:
            await message.answer("Сейчас нет активных голосовых заданий.")
        elif private and res.status == voice.UNKNOWN_USER:
            await message.answer("Ты не в списке участников — попроси админа добавить.")
        # NO_TASK в группе — молчим: реплай мог быть на что угодно.
    except Exception as exc:  # noqa: BLE001
        log.warning("voice_tasks.answer_failed", error=str(exc))


@router.message(F.voice, F.chat.type == ChatType.PRIVATE)
async def on_private_voice(message: Message) -> None:
    if message.from_user is None or message.voice is None:
        return
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            res = await voice.submit(
                session,
                telegram_id=message.from_user.id,
                file_id=message.voice.file_id,
                duration=message.voice.duration,
                tg_message_id=message.message_id,
                chat_id=message.chat.id,
                reply_to_message_id=None,
                at=message.date,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("voice_tasks.private_failed", error=str(exc))
        return
    await _answer(message, res, private=True)


@router.message(F.voice, F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def on_group_voice(message: Message) -> None:
    settings = get_settings()
    if not settings.group_chat_id or message.chat.id != settings.group_chat_id:
        return
    if message.from_user is None or message.voice is None:
        return
    reply_to = (
        message.reply_to_message.message_id
        if message.reply_to_message is not None
        else None
    )
    if reply_to is None:
        return  # в группе принимаем только реплаем на задание
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            res = await voice.submit(
                session,
                telegram_id=message.from_user.id,
                file_id=message.voice.file_id,
                duration=message.voice.duration,
                tg_message_id=message.message_id,
                chat_id=message.chat.id,
                reply_to_message_id=reply_to,
                at=message.date,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("voice_tasks.group_failed", error=str(exc))
        return
    await _answer(message, res, private=False)
