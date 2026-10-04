"""GHG11: единая модель доставки бота (off/chat/app/both) и мастер-свитчеры.

Проверяем чистые решения по режиму, разрешение режима фичи (оверрайд → мастер →
дефолт), каскад мастер-свитчера и гейтинг `journal.announce`.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.game import delivery, journal


class _StoreSession:
    """Сессия с реальным хранилищем `admin_config` (dict объектов)."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._rows: dict[str, SimpleNamespace] = {
            k: SimpleNamespace(value=v) for k, v in (values or {}).items()
        }
        self.added: list = []
        self.commits = 0

    async def get(self, _model, key):
        return self._rows.get(key)

    def add(self, obj) -> None:
        if hasattr(obj, "key"):
            self._rows[obj.key] = obj
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass


def test_pure_mode_helpers():
    assert delivery.chat_enabled(delivery.MODE_CHAT) is True
    assert delivery.chat_enabled(delivery.MODE_BOTH) is True
    assert delivery.chat_enabled(delivery.MODE_APP) is False
    assert delivery.chat_enabled(delivery.MODE_OFF) is False
    assert delivery.app_enabled(delivery.MODE_APP) is True
    assert delivery.app_enabled(delivery.MODE_BOTH) is True
    assert delivery.app_enabled(delivery.MODE_CHAT) is False
    assert delivery.is_active(delivery.MODE_OFF) is False
    assert delivery.is_active(delivery.MODE_CHAT) is True


@pytest.mark.asyncio
async def test_default_is_chat_without_config():
    session = _StoreSession()
    assert await delivery.get_feature_mode(session, "loser_auto") == delivery.MODE_CHAT
    assert await delivery.get_master_status(session, delivery.MODULE_GENERAL) == delivery.MODE_CHAT


@pytest.mark.asyncio
async def test_master_cascades_to_all_features():
    session = _StoreSession()
    await delivery.set_master_mode(session, delivery.MODULE_GENERAL, delivery.MODE_APP)
    modes = await delivery.get_mode_map(session)
    for f in delivery.features_of(delivery.MODULE_GENERAL):
        assert modes[f.key] == delivery.MODE_APP
    assert await delivery.get_master_status(session, delivery.MODULE_GENERAL) == delivery.MODE_APP
    # Ачивки — отдельный модуль, их мастер не тронут.
    assert await delivery.get_feature_mode(session, "achievements") == delivery.MODE_CHAT
    # Legacy-режим Э20 синхронизирован: app → all (чтобы чат реально замолчал).
    assert session._rows["game.chat.output_mode"].value == "all"


@pytest.mark.asyncio
async def test_master_back_to_chat_restores_legacy_mode():
    session = _StoreSession()
    await delivery.set_master_mode(session, delivery.MODULE_GENERAL, delivery.MODE_APP)
    await delivery.set_master_mode(session, delivery.MODULE_GENERAL, delivery.MODE_CHAT)
    assert session._rows["game.chat.output_mode"].value == "normal"


@pytest.mark.asyncio
async def test_feature_override_makes_master_custom():
    session = _StoreSession()
    await delivery.set_master_mode(session, delivery.MODULE_GENERAL, delivery.MODE_CHAT)
    await delivery.set_feature_mode(session, "contraband", delivery.MODE_OFF)
    assert await delivery.get_master_status(session, delivery.MODULE_GENERAL) == delivery.CUSTOM
    assert await delivery.get_feature_mode(session, "contraband") == delivery.MODE_OFF
    assert await delivery.get_feature_mode(session, "phrases") == delivery.MODE_CHAT


@pytest.mark.asyncio
async def test_achievements_master_is_separate():
    session = _StoreSession()
    await delivery.set_master_mode(session, delivery.MODULE_ACHIEVEMENTS, delivery.MODE_APP)
    assert await delivery.get_feature_mode(session, "achievements") == delivery.MODE_APP
    # Общий мастер остался chat.
    assert await delivery.get_feature_mode(session, "events") == delivery.MODE_CHAT


@pytest.mark.asyncio
async def test_rejects_unknown_feature_or_mode():
    session = _StoreSession()
    with pytest.raises(ValueError):
        await delivery.set_feature_mode(session, "nope", delivery.MODE_CHAT)
    with pytest.raises(ValueError):
        await delivery.set_feature_mode(session, "events", "bogus")


@pytest.mark.asyncio
async def test_record_feed_event_writes_feed_only_row():
    session = _StoreSession()
    ok = await delivery.record_feed_event(
        session, feature="advice", text="🔮 Да.", user_id=5
    )
    assert ok is True
    assert len(session.added) == 1
    entry = session.added[0]
    assert entry.kind == "feature"
    assert entry.sent_at is not None
    assert entry.subject_user_id == 5


@pytest.mark.asyncio
async def test_announce_off_drops_event(monkeypatch):
    session = _StoreSession({"delivery.feature.events": delivery.MODE_OFF})

    async def _send(*_a, **_k):  # pragma: no cover
        raise AssertionError("off: в чат не пишем")

    monkeypatch.setattr(journal, "send_now", _send)
    assert await journal.announce(session, kind=journal.KIND_EVENT, text="⚡️ ивент") is False
    assert session.added == []


@pytest.mark.asyncio
async def test_announce_app_records_feed_only(monkeypatch):
    session = _StoreSession({"delivery.feature.events": delivery.MODE_APP})

    async def _send(*_a, **_k):  # pragma: no cover
        raise AssertionError("app: в чат не пишем")

    monkeypatch.setattr(journal, "send_now", _send)
    assert await journal.announce(session, kind=journal.KIND_EVENT, text="⚡️ ивент") is True
    assert len(session.added) == 1
    assert session.added[0].sent_at is not None


@pytest.mark.asyncio
async def test_announce_both_sends_and_records(monkeypatch):
    session = _StoreSession({"delivery.feature.events": delivery.MODE_BOTH})
    sent: list[str] = []

    async def _send(text, **_kw):
        sent.append(text)
        return True

    async def _digest_off(_session):
        return False

    monkeypatch.setattr(journal, "send_now", _send)
    monkeypatch.setattr(journal, "get_game_digest_enabled", _digest_off)
    assert await journal.announce(session, kind=journal.KIND_EVENT, text="⚡️ ивент") is True
    assert sent == ["⚡️ ивент"]
    assert len(session.added) == 1
