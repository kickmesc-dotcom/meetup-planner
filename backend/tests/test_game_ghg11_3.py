"""GHG11(3): магический шар (ачивки) и каскадное удаление записей ленты.

Каталог ачивок — чистая проверка. Каскад `feed_moderation` тестируем на фейковой
сессии: настоящая БД не нужна — проверяем, что по префиксу ключа ленты уходит
DELETE по нужной таблице, а ачивки (`ach:`) не стираются.
"""
from __future__ import annotations

import pytest

from app.services.game import achievements_catalog as cat
from app.services.game import feed_moderation as fm

# --- Каталог ачивок шара ---------------------------------------------------


def test_advice_achievements_in_catalog():
    seeker = cat.get("advice_seeker")
    assert seeker is not None
    assert seeker.kind == cat.KIND_COUNTER
    assert seeker.tiers == (10,)  # «впервые» + юбилей ×10

    sent = cat.get("advice_sent")
    assert sent is not None
    assert sent.kind == cat.KIND_INSTANT


def test_advice_achievements_grouped_under_deeds():
    assert cat.group_of("advice_seeker")[0] == "deeds"
    assert cat.group_of("advice_sent")[0] == "deeds"


# --- Каскадное удаление источников записи ленты ----------------------------


class _FakeSession:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.added: list[object] = []

    async def execute(self, stmt):  # noqa: ANN001
        self.executed.append(str(stmt))
        return None

    async def commit(self) -> None:
        return None

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)


@pytest.fixture(autouse=True)
def _no_existing_deletions(monkeypatch):
    async def _empty(session):  # noqa: ANN001
        return set()

    monkeypatch.setattr(fm, "deleted_item_ids", _empty)


@pytest.mark.asyncio
async def test_cascade_delete_removes_journal_row():
    session = _FakeSession()
    hard = await fm.delete_item(session, item_id="journal:5", actor=1)
    assert hard is True
    assert any("game_journal" in stmt for stmt in session.executed)
    # Пометка удаления всё же записана.
    assert session.added


@pytest.mark.asyncio
async def test_cascade_delete_music_game_round():
    session = _FakeSession()
    hard = await fm.delete_item(session, item_id="music_game:9")
    assert hard is True
    assert any("music_game_rounds" in stmt for stmt in session.executed)


@pytest.mark.asyncio
async def test_achievement_item_is_not_hard_deleted():
    session = _FakeSession()
    hard = await fm.delete_item(session, item_id="ach:12")
    # Ачивка — факт биографии: строку не стираем, только прячем запись ленты.
    assert hard is False
    assert session.executed == []


# --- GHG11(5) / H3: откат XP при админском удалении голосового задания -------


class _VoiceSession:
    """Фейк, достаточный для voice-ветки `_cascade_delete` (get/scalars/execute)."""

    def __init__(self, task, subs) -> None:  # noqa: ANN001
        self._task = task
        self._subs = list(subs)
        self.executed: list[str] = []
        self.added: list[object] = []

    async def get(self, model, key, **kwargs):  # noqa: ANN001
        from app.db.models import GameVoiceTask

        return self._task if model is GameVoiceTask else None

    async def scalars(self, stmt):  # noqa: ANN001
        subs = self._subs

        class _Res:
            def __iter__(self):
                return iter(subs)

            def all(self):
                return list(subs)

        return _Res()

    async def execute(self, stmt):  # noqa: ANN001
        self.executed.append(str(stmt))
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)


@pytest.mark.asyncio
async def test_cascade_delete_voice_revokes_xp_all(monkeypatch):
    from app.services.game import awards, voice

    session = _VoiceSession(task=type("T", (), {"reward": 50})(), subs=[
        type("S", (), {"id": 1, "user_id": 5})(),
        type("S", (), {"id": 2, "user_id": 6})(),
    ])
    revoked: list[tuple[int, int]] = []

    async def _mode(s, task_id):
        return voice.MODE_ALL

    async def _revoke(s, uid, *, points, at=None):
        revoked.append((uid, points))
        return points

    monkeypatch.setattr(voice, "get_task_mode", _mode)
    monkeypatch.setattr(voice, "record_withdrawal", lambda *a, **k: None)
    monkeypatch.setattr(awards, "revoke_voice", _revoke)

    hard = await fm.delete_item(session, item_id="voice:7", actor=1)
    assert hard is True
    # XP отозван у ВСЕХ сдавших (режим «участвуют все»).
    assert revoked == [(5, 50), (6, 50)]
    assert any("game_voice_submissions" in s for s in session.executed)
    assert any("game_voice_tasks" in s for s in session.executed)


@pytest.mark.asyncio
async def test_cascade_delete_voice_first_only_revokes_first(monkeypatch):
    from app.services.game import awards, voice

    session = _VoiceSession(task=type("T", (), {"reward": 30})(), subs=[
        type("S", (), {"id": 1, "user_id": 5})(),
        type("S", (), {"id": 2, "user_id": 6})(),
    ])
    revoked: list[tuple[int, int]] = []

    async def _mode(s, task_id):
        return voice.MODE_FIRST_ONLY

    async def _revoke(s, uid, *, points, at=None):
        revoked.append((uid, points))
        return points

    monkeypatch.setattr(voice, "get_task_mode", _mode)
    monkeypatch.setattr(voice, "record_withdrawal", lambda *a, **k: None)
    monkeypatch.setattr(awards, "revoke_voice", _revoke)

    await fm.delete_item(session, item_id="voice:7", actor=1)
    assert revoked == [(5, 30)]
