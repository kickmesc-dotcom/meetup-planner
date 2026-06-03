"""GHG7 P5: handler медиа-реакций (грязная часть — aiogram + asyncio-серия).

Подсистема «оживляет» мемы участников, но не вытесняет живое общение: в режиме
`wait_then_chance` бот сперва даёт людям время отреагировать самим и реагирует
только если они промолчали (серия отложенных проверок с растущим шансом).

Чистое ядро (пулы, выбор, ролл шанса, get/set настроек) — в
`app/services/media_reactions.py`. Здесь — детектор медиа (одиночный мем vs
подборка-альбом), приём живых реакций, серия `asyncio.sleep`-тиков и сами
вызовы Telegram API (`set_message_reaction` / reply-фраза).

Состояние процесса (in-memory — бот в webhook-режиме, один процесс на HF Space,
как `_BOT_IDENTITY` в bot_reactions и `_state.pool` в proxies):
- `_reacted` — медиа, на которые УЖЕ была живая (человеческая) реакция;
- `_recent` — последний одиночный мем / последняя подборка на чат (для
  принудительных кнопок в админке, P5.5);
- `_albums` — буферы собираемых сейчас альбомов (debounce по `media_group_id`).
При рестарте Space состояние теряется — это приемлемо (эфемерные серии и
«последний мем» не критичны к перезапуску).

ВАЖНО (пропагация, ср. GHG7 P0.3.c): media-хэндлер матчит контент-типы, НЕ
`F.text`, поэтому с `bot_reactions` (F.text → SkipHandler) и `chat_capture`
не конфликтует. Для будущей совместимости `on_media` всё равно завершается
`raise SkipHandler` (чтобы апдейт мог дойти до роутеров ниже по цепочке).
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Literal

import structlog
from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import Message, MessageReactionUpdated, ReactionTypeEmoji
from sqlalchemy import select

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import User
from app.services.media_reactions import (
    WAIT_TICKS_MIN,
    get_collection_phrases,
    get_emoji_whitelist,
    get_single_phrases,
    pick_emoji,
    pick_phrase,
    roll_chance,
    substitute_username,
    tick_chance,
)
from app.services.admin_config import get_media_reactions_settings

log = structlog.get_logger()
router = Router()

MediaKind = Literal["single", "collection"]

# Контент-типы, которые считаем «медиа-мемом».
_MEDIA_CONTENT_TYPES = {
    "photo",
    "video",
    "animation",
    "document",
    "sticker",
    "voice",
    "video_note",
    "audio",
}

# Окно сбора альбома: Telegram шлёт элементы альбома отдельными апдейтами почти
# одновременно. Ждём это окно после первого элемента, потом решаем single vs
# collection. 2с с запасом покрывает разброс доставки.
_ALBUM_DEBOUNCE_SEC = 2.0

# --- in-memory состояние процесса ---
# Медиа с уже случившейся живой реакцией (chat_id, message_id).
_reacted: set[tuple[int, int]] = set()
# Последнее медиа на чат для принудительных кнопок: chat_id -> (kind, message_id, author_name).
_recent: dict[int, tuple[MediaKind, int, str]] = {}


@dataclass
class _AlbumBuf:
    """Буфер собираемого альбома (по media_group_id)."""

    chat_id: int
    author_id: int
    author_name: str
    first_message_id: int
    count: int = 1
    task: asyncio.Task | None = field(default=None, repr=False)


_albums: dict[str, _AlbumBuf] = {}


# --- helpers -----------------------------------------------------------------

_BOT_ID: int | None = None


async def _bot_id() -> int:
    """Кэш id бота (как в bot_reactions). Нужен, чтобы отличать живую реакцию
    человека от реакции самого бота."""
    global _BOT_ID
    if _BOT_ID is None:
        from app.bot.dispatcher import get_bot

        _BOT_ID = (await get_bot().me()).id
    return _BOT_ID


def _whitelist_set() -> set[int]:
    return {tg_id for tg_id, _ in get_settings().whitelist_pairs}


def _is_group(chat_id: int) -> bool:
    settings = get_settings()
    return bool(settings.group_chat_id) and chat_id == settings.group_chat_id


async def _author_name(tg_id: int) -> str:
    """display_name автора по telegram_id для подстановки %username%.
    Фолбэк — пустая строка (фраза без имени всё равно осмысленна)."""
    sm = get_sessionmaker()
    try:
        async with sm() as session:
            name = await session.scalar(
                select(User.display_name).where(User.telegram_id == tg_id)
            )
        return name or ""
    except Exception as exc:  # noqa: BLE001
        log.warning("media_reactions.author_name_failed", error=str(exc))
        return ""


# --- сами реакции (Telegram API) --------------------------------------------

async def _send_emoji_reaction(chat_id: int, message_id: int, emoji: str) -> bool:
    """set_message_reaction. True при успехе. Best-effort: глотаем ошибки
    (неподдерживаемый эмодзи / сетевые сбои не должны валить процесс)."""
    from app.bot.dispatcher import get_bot

    try:
        await get_bot().set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("media_reactions.emoji_failed", error=str(exc), emoji=emoji)
        return False


async def _send_reply_phrase(chat_id: int, message_id: int, text: str) -> bool:
    """Reply-фразой на медиа. True при успехе."""
    from app.bot.dispatcher import get_bot

    try:
        await get_bot().send_message(
            chat_id=chat_id, text=text, reply_to_message_id=message_id
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("media_reactions.reply_failed", error=str(exc))
        return False


async def _do_react(
    kind: MediaKind, chat_id: int, message_id: int, author_name: str
) -> None:
    """Выполнить реакцию согласно типу медиа и настройкам single_response_mode.

    - collection (подборка) → всегда reply-фразой из collection-пула.
    - single (одиночный мем) → по single_response_mode:
        emoji      — только эмодзи-реакция;
        phrase     — только reply-фраза (из single-пула);
        both       — и эмодзи, и фраза;
        random_one — случайно одно из двух.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        if kind == "collection":
            phrases = await get_collection_phrases(session)
            phrase = pick_phrase(phrases)
            if phrase:
                await _send_reply_phrase(
                    chat_id, message_id, substitute_username(phrase, author_name)
                )
            log.info("media_reactions.reacted", kind=kind, message_id=message_id)
            return

        settings = await get_media_reactions_settings(session)
        single_phrases = await get_single_phrases(session)
        whitelist = await get_emoji_whitelist(session)

    response_mode = settings["single_response_mode"]
    want_emoji = response_mode in {"emoji", "both"}
    want_phrase = response_mode in {"phrase", "both"}
    if response_mode == "random_one":
        if random.random() < 0.5:
            want_emoji = True
        else:
            want_phrase = True

    if want_emoji:
        emoji = pick_emoji(whitelist)
        if emoji:
            await _send_emoji_reaction(chat_id, message_id, emoji)
    if want_phrase:
        phrase = pick_phrase(single_phrases)
        if phrase:
            await _send_reply_phrase(
                chat_id, message_id, substitute_username(phrase, author_name)
            )
    log.info(
        "media_reactions.reacted",
        kind=kind,
        message_id=message_id,
        response_mode=response_mode,
    )


async def react_now(
    kind: MediaKind, chat_id: int, message_id: int, author_name: str
) -> None:
    """Немедленная реакция без серии и проверки шанса — для принудительных
    кнопок в админке (P5.5)."""
    await _do_react(kind, chat_id, message_id, author_name)


def get_recent(chat_id: int, kind: MediaKind) -> tuple[int, str] | None:
    """Последнее сохранённое медиа нужного типа на чат: (message_id, author_name)
    или None. Для force-кнопок."""
    rec = _recent.get(chat_id)
    if rec is None or rec[0] != kind:
        return None
    return rec[1], rec[2]


# --- серия отложенных проверок ----------------------------------------------

async def _reaction_series(
    kind: MediaKind, chat_id: int, message_id: int, author_name: str
) -> None:
    """Серия тиков WAIT_TICKS_MIN. На каждом: если уже была живая реакция —
    выходим молча; иначе ролл tick_chance → при успехе реагируем и выходим.

    Режим wait_then_chance проходит всю серию (растущий шанс). Режим chance
    тоже использует эту серию (живая реакция всё равно отменяет — это ок,
    «дать людям шанс» осмысленно для обоих). Режимы always/never обрабатываются
    в `_schedule_reaction` до запуска серии.
    """
    sm = get_sessionmaker()
    async with sm() as session:
        settings = await get_media_reactions_settings(session)
    base = settings["chance_base_pct"]
    mx = settings["chance_max_pct"]

    prev_min = 0
    for i, tick_min in enumerate(WAIT_TICKS_MIN):
        await asyncio.sleep((tick_min - prev_min) * 60)
        prev_min = tick_min
        if (chat_id, message_id) in _reacted:
            log.info(
                "media_reactions.skipped_human", kind=kind, message_id=message_id
            )
            return
        pct = tick_chance(i, base, mx)
        if roll_chance(pct):
            await _do_react(kind, chat_id, message_id, author_name)
            return
    log.info("media_reactions.series_exhausted", kind=kind, message_id=message_id)


async def _schedule_reaction(
    kind: MediaKind, chat_id: int, message_id: int, author_id: int, author_name: str
) -> None:
    """Решить, реагировать ли на медиа, и запустить нужный путь по настройкам."""
    sm = get_sessionmaker()
    async with sm() as session:
        settings = await get_media_reactions_settings(session)

    if not settings["enabled"]:
        return
    if kind == "single" and not settings["single_enabled"]:
        return
    if kind == "collection" and not settings["collection_enabled"]:
        return

    # Запомним как «последнее медиа» для force-кнопок.
    _recent[chat_id] = (kind, message_id, author_name)

    mode = settings["mode"]
    if mode == "never":
        return
    if mode == "always":
        await _do_react(kind, chat_id, message_id, author_name)
        return
    # chance / wait_then_chance — серия отложенных проверок.
    asyncio.create_task(
        _reaction_series(kind, chat_id, message_id, author_name)
    )


# --- детектор: одиночный мем vs альбом --------------------------------------

def classify_album(count: int) -> MediaKind:
    """Тип медиа по числу собранных элементов альбома: 2+ → подборка, иначе
    одиночный мем. Выделено отдельной чистой функцией для юнит-тестов."""
    return "collection" if count >= 2 else "single"


async def _finalize_album(media_group_id: str) -> None:
    """По истечении debounce-окна решаем тип собранного альбома и планируем
    реакцию. count>=2 → collection, иначе single."""
    await asyncio.sleep(_ALBUM_DEBOUNCE_SEC)
    buf = _albums.pop(media_group_id, None)
    if buf is None:
        return
    kind: MediaKind = classify_album(buf.count)
    log.info(
        "media_reactions.album_finalized",
        media_group_id=media_group_id,
        count=buf.count,
        kind=kind,
    )
    await _schedule_reaction(
        kind, buf.chat_id, buf.first_message_id, buf.author_id, buf.author_name
    )


async def _on_media_impl(message: Message) -> None:
    """Фильтры + агрегация. Без управления пропагацией (этим занят on_media)."""
    if not _is_group(message.chat.id):
        return
    if not message.from_user or message.from_user.is_bot:
        return
    if message.from_user.id not in _whitelist_set():
        return

    chat_id = message.chat.id
    author_id = message.from_user.id
    mgid = message.media_group_id

    if mgid is None:
        # Одиночное медиа — реагируем сразу (планируем серию/реакцию).
        author_name = await _author_name(author_id)
        await _schedule_reaction(
            "single", chat_id, message.message_id, author_id, author_name
        )
        return

    # Часть альбома — собираем в буфер с debounce.
    buf = _albums.get(mgid)
    if buf is None:
        author_name = await _author_name(author_id)
        buf = _AlbumBuf(
            chat_id=chat_id,
            author_id=author_id,
            author_name=author_name,
            first_message_id=message.message_id,
        )
        _albums[mgid] = buf
        buf.task = asyncio.create_task(_finalize_album(mgid))
    else:
        buf.count += 1
        # reply вешаем на первый элемент альбома — он уже сохранён в буфере.


@router.message(F.content_type.in_(_MEDIA_CONTENT_TYPES))
async def on_media(message: Message) -> None:
    """Матчит медиа-контент. Реагирует как побочный эффект и завершается
    `raise SkipHandler` (см. модульный docstring про пропагацию)."""
    try:
        await _on_media_impl(message)
    except Exception as exc:  # noqa: BLE001
        log.warning("media_reactions.on_media_failed", error=str(exc))
    raise SkipHandler


@router.message_reaction()
async def on_reaction(update: MessageReactionUpdated) -> None:
    """Живая реакция человека на медиа → помечаем, чтобы серия отложенных
    проверок отменилась и бот не лез поверх людей. Реакцию самого бота и
    реакции вне нашей группы игнорируем."""
    try:
        if not _is_group(update.chat.id):
            return
        # actor_chat — анонимная реакция от имени канала; нас интересует human-user.
        if update.user is None:
            return
        if update.user.id == await _bot_id():
            return
        if not update.new_reaction:
            return  # реакцию сняли — не считаем за «живую»
        _reacted.add((update.chat.id, update.message_id))
        log.info(
            "media_reactions.human_reaction",
            message_id=update.message_id,
            user_id=update.user.id,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("media_reactions.on_reaction_failed", error=str(exc))
