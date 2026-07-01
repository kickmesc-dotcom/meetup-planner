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

import random
import time

import structlog
from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import Message

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.services.admin_config import get_bot_reactions_settings

log = structlog.get_logger()
router = Router()

# T3.6.8 (б): кулдаун поддакивания — in-memory, `chat_id -> monotonic-время
# последнего поддакивания`. Намеренно БЕЗ persist: после рестарта словарь пуст,
# бот может поддакнуть сразу — по согласованию с пользователем это допустимо
# (поддакивания редкие). monotonic() не зависит от системных часов.
_last_agree_at: dict[int, float] = {}

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

    # T3.4 «магический шар». Два триггера совета, оба ДО обычной реакции:
    #  - хештег #совет/#advice — самостоятельный, не зависит от тоглов реакций;
    #  - @-mention бота + текст заканчивается на «?» — «однозначный триггер»
    #    (см. фидбек 13.06 #1). Без «?» mention идёт по старому сценарию ниже.
    # Оба гейтятся advice.enabled внутри reply_advice (вернёт False если выкл/пуст).
    from app.bot.handlers.chat_commands import reply_advice
    from app.services.advice import ends_with_question, text_has_advice_hashtag

    text = message.text or ""
    mentions_bot = bool(bot_username) and _mentions_bot(message, bot_username, bot_id)

    if text_has_advice_hashtag(text):
        if await reply_advice(message):
            return
    if mentions_bot and ends_with_question(text):
        if await reply_advice(message):
            return

    # T3.6 (в): хештег #punish/#наказать — альт-триггер /punish (помимо команды).
    # Гейт целиком внутри _handle_punish (только текущий господин + тоглы), так
    # что для не-господина это тихий no-op. Стоит ДО обычных реакций.
    from app.services.worm_master import text_has_punish_hashtag

    if text_has_punish_hashtag(text):
        from app.bot.handlers.chat_commands import _handle_punish

        if await _handle_punish(message):
            return

    # T3.6.8 (б): поддакивание господину. Реагируем на ЛЮБОЕ его сообщение (не
    # только mention/reply), поэтому стоит отдельной веткой ДО обычных реакций.
    # Гейт целиком внутри — для не-господина тихий no-op. Не return'им после:
    # поддакивание — «побочный» комментарий, не мешает mention/reply-сценарию
    # ниже, если сообщение заодно тегает бота.
    await _maybe_agree(message)

    # 1. @-mention (старый сценарий: рандом-фраза в ответ на упоминание без «?»)
    if cfg["mention_enabled"] and mentions_bot:
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


async def _maybe_agree(message: Message) -> None:
    """T3.6.8 (б): бот-подхалим изредка поддакивает сообщениям господина.

    Гейт: worm_master.enabled + yes_enabled + отправитель == текущий
    червь-господин. Затем честный ролл yes_pct и in-memory кулдаун
    yes_cooldown_min. Изредка (decide_nag) подмешиваем напоминание про /отвали.

    Не трогает пропагацию — как и остальной _maybe_react, финальный SkipHandler
    в on_message сохранит сообщение в chat_capture."""
    from app.services.admin_config import (
        get_worm_master_agrees,
        get_worm_master_nag,
        get_worm_master_yes_cooldown_min,
        get_worm_master_yes_pct,
        is_worm_master_enabled,
        is_worm_master_yes_enabled,
    )
    from app.services.loser import get_current_worm
    from app.services.phrase_weights import (
        WORM_MASTER_AGREE_USE_COUNTS_KEY,
        get_use_counts,
        increment_use_count,
    )
    from app.services.worm_master import choose, decide_agree, decide_nag, pick_nag, render

    from app.db.models import User

    sm = get_sessionmaker()
    async with sm() as session:
        if not await is_worm_master_enabled(session):
            return
        if not await is_worm_master_yes_enabled(session):
            return
        # Отправитель — текущий господин?
        worm = await get_current_worm(session)
        if worm is None:
            return
        master = await session.get(User, worm.user_id)
        if master is None or master.telegram_id != message.from_user.id:
            return

        # Ролл шанса.
        pct = await get_worm_master_yes_pct(session)
        if not decide_agree(enabled=True, pct=pct, rng_value=random.random()):
            return

        # Кулдаун (in-memory, без persist).
        cooldown_min = await get_worm_master_yes_cooldown_min(session)
        now = time.monotonic()
        last = _last_agree_at.get(message.chat.id)
        if last is not None and (now - last) < cooldown_min * 60:
            return

        # Выбор фразы (взвешенно, как у лоха/чухана).
        pool = await get_worm_master_agrees(session)
        counts = await get_use_counts(session, WORM_MASTER_AGREE_USE_COUNTS_KEY)
        raw = choose(pool, counts)
        if raw is None:
            return
        await increment_use_count(session, WORM_MASTER_AGREE_USE_COUNTS_KEY, raw)
        await session.commit()

        agree = render(raw, username=master.display_name)

        # Изредка подмешиваем напоминание про /отвали.
        nag_text: str | None = None
        if decide_nag(random.random()):
            nag_pool = await get_worm_master_nag(session)
            nag_text = pick_nag(nag_pool, username=master.display_name)

    _last_agree_at[message.chat.id] = now
    out = agree if nag_text is None else f"{agree}\n\n{nag_text}"
    try:
        await message.reply(out, parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        log.warning("worm_master.agree_send_failed", error=str(exc))


@router.message(F.text)
async def on_message(message: Message) -> None:
    """GHG7 P0.3.c фикс: этот handler матчит ЛЮБОЙ `F.text`, поэтому в aiogram
    он останавливал пропагацию апдейта (router возвращал не-`UNHANDLED`) и
    `chat_capture` ниже по цепочке НИКОГДА не вызывался — копилка фраз встала.
    Раннего `return` достаточно, чтобы апдейт считался обработанным.

    Поэтому делаем реакцию (если нужна) и ВСЕГДА `raise SkipHandler`: тогда
    `trigger` вернёт `UNHANDLED`, и Dispatcher передаст апдейт следующему
    роутеру (`chat_capture`), который сохранит сообщение.

    Реакция обёрнута в try: любой сбой внутри (сеть/БД/поддакивание) НЕ должен
    съесть `SkipHandler` — иначе chat_capture не вызовется и копилка встанет
    (тот самый инвариант, что чинил P0.3.c)."""
    try:
        await _maybe_react(message)
    except Exception:  # noqa: BLE001
        log.exception("bot_reactions.maybe_react_failed")
    raise SkipHandler
