"""GHG10 Э15: музыкальная предложка — чистая логика и приём треков.

БД-стенда нет: расписание/текст/выбор — чистыми функциями, `add_track` — через
фейк-сессию с очередью ответов `scalar`.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from app.db.models import MusicTrack
from app.services.game import music
from app.services.game.config import (
    MUSIC_MAX_TRACKS,
    MUSIC_MIN_TRACKS,
    MUSIC_PER_USER_WEEKLY,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)  # среда


# --------------------------------------------------------------------------
# Чистая логика
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("https://youtu.be/abc", True),
        ("  http://example.com/x  ", True),
        ("посмотри https://x.y", False),
        ("просто текст", False),
        (None, False),
        ("", False),
    ],
)
def test_looks_like_link(text, expected):
    assert music.looks_like_link(text) is expected


def test_scheduled_utc_uses_chat_local_time():
    """«Вторник 12:00» — по времени чата (UTC+3), а не UTC."""
    # Среда 12:00 UTC = среда 15:00 по чату; вторник этой недели уже прошёл.
    scheduled = music.scheduled_utc(NOW, weekday=1, hour=12)
    assert scheduled == datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc)
    # Суббота ещё не наступила — окно не открыто.
    assert music.scheduled_utc(NOW, weekday=5, hour=12) is None


def test_build_publication_lines_with_and_without_attribution():
    tracks = [
        MusicTrack(user_id=1, kind="link", url="https://youtu.be/a", title="Трек А"),
        MusicTrack(user_id=2, kind="audio", file_id="fid", title="Трек Б"),
    ]
    names = {1: "Митян", 2: "Сомов"}
    with_attr = music.build_publication_lines(tracks, names, attribute=True)
    assert "https://youtu.be/a" in with_attr[0]
    assert "(от Митян)" in with_attr[0]
    assert "(от Сомов)" in with_attr[1]
    # Без подписи автора — имён нет.
    anon = music.build_publication_lines(tracks, names, attribute=False)
    assert "Митян" not in anon[0] and "Сомов" not in anon[1]


def test_pick_for_publication_caps_and_sorts_by_arrival():
    tracks = [
        MusicTrack(id=i, user_id=1, kind="link", url=f"u{i}", added_at=NOW)
        for i in range(1, MUSIC_MAX_TRACKS + 6)
    ]
    chosen = music.pick_for_publication(tracks, rng=random.Random(0))
    assert len(chosen) == MUSIC_MAX_TRACKS
    # Порядок стабильный: по времени поступления.
    assert [t.id for t in chosen] == sorted(t.id for t in chosen)
    # Когда треков мало — берём все.
    assert len(music.pick_for_publication(tracks[:3], rng=random.Random(0))) == 3


def test_texts():
    assert str(MUSIC_MIN_TRACKS) in music.shortfall_text(have=2, need=MUSIC_MIN_TRACKS)
    assert "Подборка" in music.publication_header(count=5)


# --------------------------------------------------------------------------
# Приём трека (фейк-сессия)
# --------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, scalars: list | None = None):
        self.scalar_queue = list(scalars or [])
        self.added: list = []
        self.commits = 0

    async def scalar(self, *_a, **_k):  # noqa: ANN002, ANN003
        return self.scalar_queue.pop(0) if self.scalar_queue else None

    def add(self, row) -> None:  # noqa: ANN001
        self.added.append(row)

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_add_track_unknown_user():
    session = _FakeSession([None])
    res = await music.add_track(
        session, telegram_id=1, kind="link", url="https://x.y", at=NOW
    )
    assert res.status == music.UNKNOWN_USER


@pytest.mark.asyncio
async def test_add_track_rejects_non_link():
    session = _FakeSession([5])
    res = await music.add_track(
        session, telegram_id=1, kind="link", url="просто текст", at=NOW
    )
    assert res.status == music.BAD


@pytest.mark.asyncio
async def test_add_track_weekly_limit():
    # user_id, потом счётчик недели = лимит
    session = _FakeSession([5, MUSIC_PER_USER_WEEKLY])
    res = await music.add_track(
        session, telegram_id=1, kind="audio", file_id="fid", at=NOW
    )
    assert res.status == music.LIMIT


@pytest.mark.asyncio
async def test_add_track_duplicate():
    # user_id, счётчик=0, дубль найден
    session = _FakeSession([5, 0, 7])
    res = await music.add_track(
        session, telegram_id=1, kind="link", url="https://x.y", at=NOW
    )
    assert res.status == music.DUPLICATE


@pytest.mark.asyncio
async def test_add_track_ok_counts_after_insert():
    # user_id, счётчик=0, дубля нет, счётчик после вставки=1
    session = _FakeSession([5, 0, None, 1])
    res = await music.add_track(
        session, telegram_id=1, kind="link", url="https://x.y", title="X", at=NOW
    )
    assert res.status == music.OK
    assert res.week_count == 1
    assert session.commits == 1
    saved = [r for r in session.added if isinstance(r, MusicTrack)]
    assert len(saved) == 1 and saved[0].url == "https://x.y"
