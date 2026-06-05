"""GHG6 E9: реакции бота на @-mention и reply.

Три независимых master-toggle (см. GHG6.txt п.9):
- `bot_reactions.mention_enabled` (default true) — @mention бота в чате.
- `bot_reactions.reply_all_enabled` (default false) — reply на ЛЮБОЕ сообщение
  бота → ответ рандом-фразой.
- `bot_reactions.reply_except_phrases_enabled` (default true) — reply на
  сообщение бота, КРОМЕ рандом-цитат → ответ. Работает независимо от
  `reply_all_enabled`: при включённом `reply_all` всё равно отвечаем (он
  «шире», цитаты тоже попадают). При выключенном `reply_all` и включённом
  `reply_except_phrases` — отвечаем только на не-цитаты.

Ответ — короткая «шизо-цитата» через `compose_random_phrase(session, n=1)`.
Используется тот же пул, что и для автопоста, но без жирной шапки —
просто текст без обёртки.

Whitelist: реагируем только на сообщения от участников whitelist (как
chat_capture). Чужие сообщения игнорируем молча.

ВАЖНО (GHG7 P0.3.c): handler матчит `F.text` (любое текстовое сообщение) и
регистрируется ДО chat_capture. В aiogram первый сматчившийся router-handler
останавливает пропагацию, поэтому раньше chat_capture НЕ вызывался и копилка
фраз перестала пополняться. Фикс: `on_message` всегда завершается
`raise SkipHandler`, благодаря чему апдейт доходит до chat_capture и
сохраняется. Реакция (mention/reply) при этом выполняется как побочный эффект.
"""
from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import Message

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.services.admin_config import get_bot_reactions_settings

log = structlog.get_logger()
router = Router()

# Сигнатуры рандом-цитат (см. services/random_phrases.py::compose_random_phrase).
# Если reply пришёл на сообщение бота, которое начинается с одной из этих
# подстрок — считаем, что это рандом-цитата.
_PHRASE_PREFIXES = ("🗣 ", "👤 ")

# Кэш bot identity (username/id). bot.me() — сетевой вызов, держим один раз
# на процесс. Если бот меняет username — нужен restart, и это ок.
_BOT_IDENTITY: tuple[int, str] | None = None


async def _bot_identity() -> tuple[int, str]:
    global _BOT_IDENTITY
    if _BOT_IDENTITY is not None:
        return _BOT_IDENTITY
    from app.bot.dispatcher import get_bot

    bot_user = await get_bot().me()
    _BOT_IDENTITY = (bot_user.id, bot_user.username or "")
    return _BOT_IDENTITY


def _is_phrase_message(text: str | None) -> bool:
    if not text:
        return False
    return any(text.startswith(p) for p in _PHRASE_PREFIXES)


def _mentions_bot(message: Message, bot_username: str, bot_id: int) -> bool:
    """True если в сообщении явно тегнут наш бот.

    Поддерживаем два типа упоминаний:
    - `mention` (`@username` в тексте) — сравниваем substring.
    - `text_mention` (упоминание без username, через профиль) — сравниваем по id.
    """
    if not message.entities or not message.text:
        return False
    handle = f"@{bot_username.lower()}"
    for ent in message.entities:
        if ent.type == "mention":
            chunk = message.text[ent.offset : ent.offset + ent.length].lower()
            if chunk == handle:
                return True
        elif ent.type == "text_mention" and ent.user and ent.user.id == bot_id:
            return True
    return False


def _whitelist_set() -> set[int]:
    return {tg_id for tg_id, _ in get_settings().whitelist_pairs}


async def _react(message: Message) -> None:
    """Сгенерировать и отправить ответ. Reply на исходное сообщение —
    чтобы в групповом чате было понятно, на что бот реагирует.

    GHG6 hotfix: используем `compose_bot_reply_phrase` (без шапки автора)
    вместо `compose_random_phrase` (с 🗣/👤). Reply бота — это голос самого
    бота, а не цитата от другого участника.
    """
    from app.services.admin_config import (
        get_random_phrases_recency_quarantine_hours,
        get_random_phrases_recency_quarantine_weight,
    )
    from app.services.random_phrases import compose_bot_reply_phrase

    sm = get_sessionmaker()
    async with sm() as session:
        # P13: reply — главный источник «передразнивания» свежих сообщений,
        # поэтому карантин свежести применяется и здесь.
        recency_hours = await get_random_phrases_recency_quarantine_hours(session)
        recency_weight = await get_random_phrases_recency_quarantine_weight(session)
        text = await compose_bot_reply_phrase(
            session,
            recency_quarantine_hours=recency_hours,
            recency_quarantine_weight=recency_weight,
        )
    if not text:
        return
    try:
        await message.reply(text, parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        log.warning("bot_reactions.send_failed", error=str(exc))


async def _maybe_react(message: Message) -> None:
    """Решить, реагировать ли на сообщение, и отреагировать. Без управления
    пропагацией — этим занимается `on_message`."""
    # Реагируем только в группе и только на whitelist'е.
    settings = get_settings()
    if not settings.group_chat_id or message.chat.id != settings.group_chat_id:
        return
    if not message.from_user or message.from_user.is_bot:
        return
    if message.from_user.id not in _whitelist_set():
        return

    bot_id, bot_username = await _bot_identity()

    sm = get_sessionmaker()
    async with sm() as session:
        cfg = await get_bot_reactions_settings(session)

    # 1. @-mention
    if cfg["mention_enabled"] and bot_username and _mentions_bot(
        message, bot_username, bot_id
    ):
        log.info("bot_reactions.mention", from_id=message.from_user.id)
        await _react(message)
        return

    # 2. Reply на сообщение бота — две независимых ветки.
    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.from_user and replied.from_user.id == bot_id:
            is_phrase = _is_phrase_message(replied.text or replied.html_text or "")
            should_reply = False
            if cfg["reply_all_enabled"]:
                should_reply = True
            elif cfg["reply_except_phrases_enabled"] and not is_phrase:
                should_reply = True
            if should_reply:
                log.info(
                    "bot_reactions.reply",
                    from_id=message.from_user.id,
                    is_phrase=is_phrase,
                )
                await _react(message)


@router.message(F.text)
async def on_message(message: Message) -> None:
    """GHG7 P0.3.c фикс: этот handler матчит ЛЮБОЙ `F.text`, поэтому в aiogram
    он останавливал пропагацию апдейта (router возвращал не-`UNHANDLED`) и
    `chat_capture` ниже по цепочке НИКОГДА не вызывался — копилка фраз встала.
    Раннего `return` достаточно, чтобы апдейт считался обработанным.

    Поэтому делаем реакцию (если нужна) и ВСЕГДА `raise SkipHandler`: тогда
    `trigger` вернёт `UNHANDLED`, и Dispatcher передаст апдейт следующему
    роутеру (`chat_capture`), который сохранит сообщение."""
    await _maybe_react(message)
    raise SkipHandler
