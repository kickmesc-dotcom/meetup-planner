"""GHG10 Э17: лайки трекам подборки и «топ треков недели» (задел H.8).

БД-стенда нет: `top_window_start` — чистая функция, `toggle_like`/`like_counts`/
`liked_track_ids`/`top_tracks` — через фейк-сессии с очередями ответов.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import MusicTrack, MusicTrackLike
from app.services.game import music
from app.services.game.config import MUSIC_TOP_TRACKS_LIMIT, MUSIC_TOP_WINDOW_DAYS

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Чистая логика
# --------------------------------------------------------------------------


def test_top_window_start_is_seven_days_back():
    assert music.top_window_start(NOW) == NOW - timedelta(days=MUSIC_TOP_WINDOW_DAYS)


# --------------------------------------------------------------------------
# toggle_like
# --------------------------------------------------------------------------


class _ToggleSession:
    def __init__(self, *, track, scalars: list | None = None) -> None:
        self.track = track
        self.scalar_queue = list(scalars or [])
        self.added: list = []
        self.deleted: list = []
        self.commits = 0

    async def get(self, *_a, **_k):  # noqa: ANN002, ANN003
        return self.track

    async def scalar(self, *_a, **_k):  # noqa: ANN002, ANN003
        return self.scalar_queue.pop(0) if self.scalar_queue else None

    def add(self, row) -> None:  # noqa: ANN001
        self.added.append(row)

    async def delete(self, row) -> None:  # noqa: ANN001
        self.deleted.append(row)

    async def commit(self) -> None:
        self.commits += 1


def _published_track() -> MusicTrack:
    return MusicTrack(id=5, user_id=1, kind="link", url="u", status="published")


@pytest.mark.asyncio
async def test_toggle_like_rejects_track_that_is_not_published():
    session = _ToggleSession(
        track=MusicTrack(id=5, user_id=1, kind="link", url="u", status="pool")
    )
    res = await music.toggle_like(session, user_id=1, track_id=5)
    assert res.status == music.LIKE_NOT_PUBLISHED
    assert session.added == [] and session.commits == 0


@pytest.mark.asyncio
async def test_toggle_like_rejects_missing_track():
    session = _ToggleSession(track=None)
    res = await music.toggle_like(session, user_id=1, track_id=999)
    assert res.status == music.LIKE_NOT_PUBLISHED


@pytest.mark.asyncio
async def test_toggle_like_sets_and_counts():
    # existing=None (лайка нет), затем count=1
    session = _ToggleSession(track=_published_track(), scalars=[None, 1])
    res = await music.toggle_like(session, user_id=7, track_id=5)
    assert res.status == music.LIKE_OK
    assert res.liked is True and res.likes == 1
    saved = [r for r in session.added if isinstance(r, MusicTrackLike)]
    assert len(saved) == 1 and saved[0].track_id == 5 and saved[0].user_id == 7


@pytest.mark.asyncio
async def test_toggle_like_removes_existing():
    existing = MusicTrackLike(user_id=7, track_id=5)
    # existing найден, затем count=0
    session = _ToggleSession(track=_published_track(), scalars=[existing, 0])
    res = await music.toggle_like(session, user_id=7, track_id=5)
    assert res.status == music.LIKE_OK
    assert res.liked is False and res.likes == 0
    assert session.deleted == [existing]
    assert [r for r in session.added if isinstance(r, MusicTrackLike)] == []


# --------------------------------------------------------------------------
# like_counts / liked_track_ids / top_tracks
# --------------------------------------------------------------------------


class _Rows:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)


class _ExecSession:
    def __init__(self, rows: list | None = None, scalars: list | None = None) -> None:
        self.execute_rows = list(rows or [])
        self.scalars_rows = list(scalars or [])

    async def execute(self, *_a, **_k):  # noqa: ANN002, ANN003
        return _Rows(self.execute_rows.pop(0) if self.execute_rows else [])

    async def scalars(self, *_a, **_k):  # noqa: ANN002, ANN003
        return _Rows(self.scalars_rows.pop(0) if self.scalars_rows else [])


@pytest.mark.asyncio
async def test_like_counts_is_empty_for_no_tracks():
    session = _ExecSession()
    assert await music.like_counts(session, []) == {}


@pytest.mark.asyncio
async def test_like_counts_maps_rows():
    session = _ExecSession(rows=[[(5, 3), (6, 1)]])
    assert await music.like_counts(session, [5, 6]) == {5: 3, 6: 1}


@pytest.mark.asyncio
async def test_liked_track_ids_returns_set():
    session = _ExecSession(scalars=[[5, 6]])
    assert await music.liked_track_ids(session, 1, [5, 6, 7]) == {5, 6}


@pytest.mark.asyncio
async def test_top_tracks_returns_track_and_count_pairs():
    track = MusicTrack(id=5, user_id=1, kind="link", url="u", status="published")
    session = _ExecSession(rows=[[(track, 4)]])
    got = await music.top_tracks(session, since=NOW, limit=MUSIC_TOP_TRACKS_LIMIT)
    assert got == [(track, 4)]
