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
