"""GHG7 P0.3.c — гард: bot_reactions.on_message не должен глотать апдейт.

Корень бага: `@router.message(F.text)` матчит любое текстовое сообщение, а
любой не-`SkipHandler` исход (включая ранний `return None`) в aiogram
останавливает пропагацию между роутерами — и chat_capture, который
регистрируется ПОСЛЕ bot_reactions, переставал вызываться. Копилка фраз
(chat_messages) встала.

Инвариант, который защищаем: `on_message` ВСЕГДА завершается
`raise SkipHandler`, какой бы ни была ветка (не группа / не whitelist /
mention / reply / тихий проход). Тогда `trigger` вернёт `UNHANDLED` и
Dispatcher отдаст апдейт chat_capture.

Стенд минимальный (см. test_loser_outbox заголовок): мокаем настройки и
_react, реальную БД/сеть не трогаем.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.dispatcher.event.bases import SkipHandler

import app.bot.handlers.bot_reactions as br


class _Settings:
    def __init__(self, group_chat_id: int = -100, whitelist: list[int] | None = None):
        self.group_chat_id = group_chat_id
        self.whitelist_pairs = [(uid, f"name{uid}") for uid in (whitelist or [42])]


def _make_message(
    *,
    chat_id: int = -100,
    from_id: int | None = 42,
    is_bot: bool = False,
    text: str = "привет",
    reply_to: Any = None,
    entities: Any = None,
) -> MagicMock:
    m = MagicMock()
    m.chat.id = chat_id
    if from_id is None:
        m.from_user = None
    else:
        m.from_user = MagicMock()
        m.from_user.id = from_id
        m.from_user.is_bot = is_bot
    m.text = text
    m.entities = entities
    m.reply_to_message = reply_to
    return m


def _patch_common(monkeypatch, *, settings: _Settings, react: AsyncMock) -> None:
    monkeypatch.setattr(br, "get_settings", lambda: settings)
    monkeypatch.setattr(br, "_react", react)
    # _bot_identity и cfg — на случай, если дойдём до реакции.
    monkeypatch.setattr(br, "_bot_identity", AsyncMock(return_value=(999, "gunghogunsbot")))
    monkeypatch.setattr(
        br,
        "get_bot_reactions_settings",
        AsyncMock(
            return_value={
                "mention_enabled": True,
                "reply_all_enabled": False,
                "reply_except_phrases_enabled": True,
            }
        ),
    )
    # get_sessionmaker → контекст-менеджер с фейковой сессией.
    fake_sm = MagicMock()
    fake_sm.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    fake_sm.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(br, "get_sessionmaker", lambda: fake_sm)


def test_skiphandler_when_not_group(monkeypatch):
    """Сообщение из другого чата → не реагируем, но пропагацию НЕ глотаем."""
    react = AsyncMock()
    _patch_common(monkeypatch, settings=_Settings(group_chat_id=-100), react=react)
    msg = _make_message(chat_id=-555)  # чужой чат
    with pytest.raises(SkipHandler):
        asyncio.run(br.on_message(msg))
    react.assert_not_called()


def test_skiphandler_when_not_whitelisted(monkeypatch):
    react = AsyncMock()
    _patch_common(monkeypatch, settings=_Settings(whitelist=[42]), react=react)
    msg = _make_message(from_id=7)  # не в whitelist
    with pytest.raises(SkipHandler):
        asyncio.run(br.on_message(msg))
    react.assert_not_called()


def test_skiphandler_on_plain_text(monkeypatch):
    """Обычное сообщение без mention/reply → SkipHandler, без реакции.
    Это самый частый путь и именно он раньше глотал апдейт."""
    react = AsyncMock()
    _patch_common(monkeypatch, settings=_Settings(whitelist=[42]), react=react)
    msg = _make_message(from_id=42, text="просто болтаем", reply_to=None, entities=None)
    with pytest.raises(SkipHandler):
        asyncio.run(br.on_message(msg))
    react.assert_not_called()


def test_skiphandler_even_when_reacting_on_mention(monkeypatch):
    """Даже когда бот реагирует (mention) — SkipHandler всё равно поднимается,
    чтобы chat_capture сохранил сообщение."""
    react = AsyncMock()
    _patch_common(monkeypatch, settings=_Settings(whitelist=[42]), react=react)
    ent = MagicMock()
    ent.type = "mention"
    ent.offset = 0
    ent.length = len("@gunghogunsbot")
    msg = _make_message(
        from_id=42,
        text="@gunghogunsbot ауу",
        entities=[ent],
    )
    with pytest.raises(SkipHandler):
        asyncio.run(br.on_message(msg))
    react.assert_called_once()
