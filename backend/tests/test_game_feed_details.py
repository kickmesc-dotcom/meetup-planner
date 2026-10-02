"""Э22: раскрывающиеся подробности ленты — голосовые сдачи и треки подборки.

БД-стенда нет: `_attach_details` дёргает сервисы `voice`/`music`, их и
подменяем — проверяем, что подробности собираются для записей страницы.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.game import feed, music, voice


def _voice_item() -> dict:
    return feed._item(
        source="voice",
        row_id="voice:7",
        kind=feed.FEED_VOICE,
        at=None,
        text="«колыбельная» — +50 XP",
        user=None,
        detail={"condition": "спой", "reward": 50, "opened_at": None},
    )


def _music_item() -> dict:
    return feed._item(
        source="music",
        row_id="music:3",
        kind=feed.FEED_MUSIC,
        at=None,
        text="Подборка недели — 2 треков",
        user=None,
        detail={"selection_id": 3, "track_count": 2},
    )


@pytest.mark.asyncio
async def test_voice_item_gets_submissions(monkeypatch):
    async def fake_subs(session, task_id):
        assert task_id == 7
        return [SimpleNamespace(id=11, user_id=5, duration=3)]

    async def fake_names(session, ids):
        return {5: "Серёга"}

    monkeypatch.setattr(voice, "_submissions", fake_subs)
    monkeypatch.setattr(voice, "_user_names", fake_names)

    items = [_voice_item()]
    await feed._attach_details(None, items, user_id=1)
    assert items[0]["detail"]["submissions"] == [
        {"id": 11, "user_id": 5, "user_name": "Серёга", "duration": 3}
    ]
    # Условие и награда не потерялись.
    assert items[0]["detail"]["condition"] == "спой"
    assert items[0]["detail"]["reward"] == 50


@pytest.mark.asyncio
async def test_music_item_gets_tracks_with_likes(monkeypatch):
    async def fake_sel(session, sel_id):
        assert sel_id == 3
        return [SimpleNamespace(id=9, kind="link", title="T", performer="P", url="u")]

    async def fake_likes(session, ids):
        return {9: 4}

    async def fake_mine(session, uid, ids):
        return {9}

    monkeypatch.setattr(music, "selection_tracks", fake_sel)
    monkeypatch.setattr(music, "like_counts", fake_likes)
    monkeypatch.setattr(music, "liked_track_ids", fake_mine)

    items = [_music_item()]
    await feed._attach_details(None, items, user_id=1)
    assert items[0]["detail"]["tracks"] == [
        {
            "id": 9,
            "kind": "link",
            "title": "T",
            "performer": "P",
            "url": "u",
            "likes": 4,
            "liked": True,
        }
    ]


@pytest.mark.asyncio
async def test_music_without_liked_when_scope_all(monkeypatch):
    async def fake_sel(session, sel_id):
        return [SimpleNamespace(id=9, kind="link", title="T", performer="P", url="u")]

    async def fake_likes(session, ids):
        return {9: 4}

    monkeypatch.setattr(music, "selection_tracks", fake_sel)
    monkeypatch.setattr(music, "like_counts", fake_likes)

    items = [_music_item()]
    await feed._attach_details(None, items, user_id=None)
    assert items[0]["detail"]["tracks"][0]["liked"] is False


def test_item_carries_detail_field():
    item = feed._item(
        source="ach",
        row_id="ach:1",
        kind=feed.FEED_ACHIEVEMENT,
        at=None,
        text="x",
        user=None,
        detail={"code": "past_master", "description": "поймай паст"},
    )
    assert item["detail"] == {"code": "past_master", "description": "поймай паст"}
