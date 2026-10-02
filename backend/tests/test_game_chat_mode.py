"""Э20: два софт-режима приглушения (`game.chat.output_mode`).

Проверяем, что:
* отсутствие ключа = `normal` (поведение не меняется);
* режим 1 (`achievements`) режет только анонсы ачивок;
* режим 2 (`all`) режет всю проактивную активность и пишет её в ленту.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.game import chat_mode, journal


class _CfgSession:
    """Сессия с admin_config-строкой: `get` отдаёт value по ключу."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = values or {}
        self.added: list = []
        self.commits = 0

    async def get(self, _model, key):
        if key in self._values:
            return SimpleNamespace(value=self._values[key])
        return None

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass


@pytest.mark.asyncio
async def test_default_mode_is_normal_without_key():
    session = _CfgSession()
    assert await chat_mode.get_chat_mode(session) == "normal"
    assert await chat_mode.chat_all_silent(session) is False
    assert await chat_mode.achievements_silent(session) is False


@pytest.mark.asyncio
async def test_achievements_mode_only_silences_achievements(monkeypatch):
    session = _CfgSession({"game.chat.output_mode": "achievements"})
    assert await chat_mode.get_chat_mode(session) == "achievements"
    assert await chat_mode.achievements_silent(session) is True
    assert await chat_mode.chat_all_silent(session) is False

    sent: list[str] = []

    async def _send(text, **_kw):
        sent.append(text)
        return True

    async def _digest_off(_session):
        return False

    monkeypatch.setattr(journal, "send_now", _send)
    monkeypatch.setattr(journal, "get_game_digest_enabled", _digest_off)

    # Ачивка — только в ленту (запись с sent_at, чтобы дайджест не подхватил).
    ok = await journal.announce(
        session, kind=journal.KIND_ACHIEVEMENT, text="🏆 Аня", subject_user_id=7
    )
    assert ok is True
    assert sent == []
    assert len(session.added) == 1
    assert session.added[0].sent_at is not None

    # Событие — как прежде, идёт в чат.
    ok = await journal.announce(session, kind=journal.KIND_EVENT, text="⚡️ ивент")
    assert ok is True
    assert sent == ["⚡️ ивент"]


@pytest.mark.asyncio
async def test_all_mode_silences_everything(monkeypatch):
    session = _CfgSession({"game.chat.output_mode": "all"})
    assert await chat_mode.chat_all_silent(session) is True

    async def _send(*_a, **_k):  # pragma: no cover
        raise AssertionError("в режиме 'all' в чат не пишем")

    monkeypatch.setattr(journal, "send_now", _send)

    ok = await journal.announce(session, kind=journal.KIND_EVENT, text="⚡️ ивент")
    assert ok is True
    assert len(session.added) == 1
    assert session.added[0].kind == journal.KIND_EVENT
    assert session.added[0].sent_at is not None
