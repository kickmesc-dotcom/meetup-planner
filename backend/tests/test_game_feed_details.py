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

    async def fake_likes(session, ids):
        assert ids == [11]
        return {11: 2}

    async def fake_mine(session, uid, ids):
        assert uid == 1
        return {11}

    async def fake_mode(session, task_id):
        return voice.MODE_ALL

    async def fake_avatars(session, ids):
        return {5: "http://a/5.png"}

    monkeypatch.setattr(voice, "_submissions", fake_subs)
    monkeypatch.setattr(voice, "_user_names", fake_names)
    monkeypatch.setattr(voice, "like_counts", fake_likes)
    monkeypatch.setattr(voice, "liked_ids", fake_mine)
    monkeypatch.setattr(voice, "get_task_mode", fake_mode)
    monkeypatch.setattr(feed, "_submission_avatars", fake_avatars)

    items = [_voice_item()]
    await feed._attach_details(None, items, user_id=1)
    assert items[0]["detail"]["submissions"] == [
        {
            "id": 11,
            "user_id": 5,
            "user_name": "Серёга",
            "avatar_url": "http://a/5.png",
            "duration": 3,
            "likes": 2,
            "liked": True,
            "xp": 50,
        }
    ]
    # Условие и награда не потерялись.
    assert items[0]["detail"]["condition"] == "спой"
    assert items[0]["detail"]["reward"] == 50


@pytest.mark.asyncio
async def test_music_item_gets_tracks_with_likes(monkeypatch):
    async def fake_sel(session, sel_id):
        assert sel_id == 3
        return [
            SimpleNamespace(
                id=9, kind="link", title="T", performer="P", url="u", user_id=5
            )
        ]

    async def fake_likes(session, ids):
        return {9: 4}

    async def fake_mine(session, uid, ids):
        return {9}

    async def fake_meta(session, ids):
        return {5: {"user_name": "Серёга", "avatar_url": "http://a/5.png"}}

    monkeypatch.setattr(music, "selection_tracks", fake_sel)
    monkeypatch.setattr(music, "like_counts", fake_likes)
    monkeypatch.setattr(music, "liked_track_ids", fake_mine)
    monkeypatch.setattr(feed, "_user_meta", fake_meta)

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
            "user_id": 5,
            "user_name": "Серёга",
            "avatar_url": "http://a/5.png",
        }
    ]
    # GHG11(4): миниатюры участников подборки — владелец + суммарные лайки.
    assert items[0]["detail"]["participants"] == [
        {
            "user_id": 5,
            "user_name": "Серёга",
            "avatar_url": "http://a/5.png",
            "xp": 0,
            "likes": 4,
        }
    ]


@pytest.mark.asyncio
async def test_music_without_liked_when_scope_all(monkeypatch):
    async def fake_sel(session, sel_id):
        return [
            SimpleNamespace(
                id=9, kind="link", title="T", performer="P", url="u", user_id=5
            )
        ]

    async def fake_likes(session, ids):
        return {9: 4}

    async def fake_meta(session, ids):
        return {5: {"user_name": "Серёга", "avatar_url": None}}

    monkeypatch.setattr(music, "selection_tracks", fake_sel)
    monkeypatch.setattr(music, "like_counts", fake_likes)
    monkeypatch.setattr(feed, "_user_meta", fake_meta)

    items = [_music_item()]
    await feed._attach_details(None, items, user_id=None)
    assert items[0]["detail"]["tracks"][0]["liked"] is False


def _subject() -> SimpleNamespace:
    return SimpleNamespace(
        id=5,
        display_name="Серёга",
        telegram_id=306733739,
        avatar_url="http://a/5.png",
    )


@pytest.mark.asyncio
async def test_loser_and_chukhan_get_single_participant(monkeypatch):
    """GHG11(5): лох/чухан получают миниатюру-субъекта (без XP/лайков)."""
    loser = feed._item(
        source="loser",
        row_id="loser:3",
        kind=feed.FEED_LOSER,
        at=None,
        text="«причина»",
        user=_subject(),
        detail={"reason": "причина"},
    )
    chukhan = feed._item(
        source="chukhan",
        row_id="chukhan:4",
        kind=feed.FEED_CHUKHAN,
        at=None,
        text="«другая»",
        user=_subject(),
        detail={"reason": "другая"},
    )
    await feed._attach_details(None, [loser, chukhan], user_id=1)
    expected = [
        {
            "user_id": 5,
            "user_name": "Серёга",
            "avatar_url": "http://a/5.png",
            "xp": 0,
            "likes": 0,
        }
    ]
    assert loser["detail"]["participants"] == expected
    assert chukhan["detail"]["participants"] == expected
    # прежние поля подробностей не потерялись
    assert loser["detail"]["reason"] == "причина"


@pytest.mark.asyncio
async def test_feature_journal_item_gets_participant(monkeypatch):
    """GHG11(5): активность фичи (kind=feature) тоже даёт миниатюру участника."""
    feature = feed._item(
        source="journal",
        row_id="journal:9",
        kind=feed.FEED_FEATURE,
        at=None,
        text="🔮 совет",
        user=_subject(),
    )
    await feed._attach_details(None, [feature], user_id=1)
    assert feature["detail"]["participants"] == [
        {
            "user_id": 5,
            "user_name": "Серёга",
            "avatar_url": "http://a/5.png",
            "xp": 0,
            "likes": 0,
        }
    ]


@pytest.mark.asyncio
async def test_generic_journal_event_has_no_participant():
    """Глобальные события (event/holiday) остаются без миниатюр-участников."""
    event = feed._item(
        source="journal",
        row_id="journal:11",
        kind="event",
        at=None,
        text="⚡️ событие",
        user=_subject(),
    )
    await feed._attach_details(None, [event], user_id=1)
    assert event["detail"] is None


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
