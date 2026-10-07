"""GHG11(7): персональный фильтр ленты «по участникам».

`build_feed` собирает ленту из семи источников одним проходом. Здесь мы
подменяем источники-заглушками (БД-стенда нет), чтобы проверить ровно фильтр
`muted_ids`:
* события скрытого участника не показываем;
* записи без субъекта (задания/подборки) остаются;
* СВОИ события не выкидываем никогда — свою галочку отключить нельзя, иначе
  лента «сломается».
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.game import feed, feed_moderation, today_titles


def _item(row_id: str, uid: int | None, at: datetime) -> dict:
    return {
        "id": row_id,
        "source": "test",
        "kind": feed.FEED_ACHIEVEMENT,
        "icon": "🏆",
        "title": "Ачивка",
        "text": "",
        "at": at,
        "detail": None,
        "badges": [],
        "user_id": uid,
        "user_name": None if uid is None else f"u{uid}",
        "user_telegram_id": None,
        "avatar_url": None,
    }


@pytest.fixture
def quiet_feed(monkeypatch):
    """Все источники пустые, модерация/плашки/детали — no-op."""

    async def empty(session, **kwargs):
        return []

    async def no_attach(session, items, *, user_id):
        return None

    async def no_removed(session):
        return set()

    async def no_hidden(session, viewer_id):
        return set()

    async def no_badges(session):
        return {}

    for name in (
        "_achievement_items",
        "_loser_items",
        "_chukhan_items",
        "_voice_items",
        "_music_items",
        "_music_game_items",
        "_journal_items",
    ):
        monkeypatch.setattr(feed, name, empty)
    monkeypatch.setattr(feed, "_attach_details", no_attach)
    monkeypatch.setattr(feed_moderation, "deleted_item_ids", no_removed)
    monkeypatch.setattr(feed_moderation, "hidden_item_ids", no_hidden)
    monkeypatch.setattr(today_titles, "badge_map", no_badges)
    return monkeypatch


def _set_items(monkeypatch, items: list[dict]) -> None:
    async def source(session, **kwargs):
        return list(items)

    monkeypatch.setattr(feed, "_achievement_items", source)


NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_muted_participant_hidden_but_own_and_subjectless_kept(quiet_feed):
    items = [
        _item("ach:1", 5, NOW),  # свой (viewer=5) — остаётся
        _item("ach:2", 6, NOW),  # скрыт
        _item("ach:3", None, NOW),  # без субъекта — остаётся
    ]
    _set_items(quiet_feed, items)

    out = await feed.build_feed(
        None, viewer_id=5, limit=30, offset=0, muted_ids={5, 6}
    )
    assert [it["id"] for it in out] == ["ach:1", "ach:3"]


@pytest.mark.asyncio
async def test_no_mute_shows_everything(quiet_feed):
    items = [_item("ach:1", 5, NOW), _item("ach:2", 6, NOW)]
    _set_items(quiet_feed, items)

    out = await feed.build_feed(None, viewer_id=5, limit=30, offset=0)
    assert [it["id"] for it in out] == ["ach:1", "ach:2"]
