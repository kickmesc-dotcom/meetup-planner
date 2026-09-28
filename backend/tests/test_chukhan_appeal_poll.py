"""GHG8 H.3: тесты клампа длительности опроса-обжалования чухана (без БД).

Раньше `open_period` был захардкожен (3600с = 1ч). Теперь значение
настраивается; кламп — чистая функция, как у media_reactions.clamp_wait_window.
"""
from __future__ import annotations

import pytest

from app.services import admin_config as ac
from app.services.admin_config import (
    _CHUKHAN_APPEAL_POLL_MINUTES_DEFAULT,
    CHUKHAN_APPEAL_POLL_MINUTES_BOUNDS,
    clamp_appeal_poll_minutes,
    get_chukhan_appeal_poll_minutes,
    set_chukhan_appeal_poll_minutes,
)


class _FakeRow:
    def __init__(self, key: str, value: str) -> None:
        self.key = key
        self.value = value


class _FakeSession:
    """Минимальный стенд `admin_config`: dict key→row (как один ряд таблицы)."""

    def __init__(self) -> None:
        self._store: dict[str, _FakeRow] = {}

    async def get(self, model, key):  # noqa: ANN001
        return self._store.get(key)

    def add(self, row) -> None:  # noqa: ANN001
        self._store[row.key] = row

    async def commit(self) -> None:
        pass


@pytest.fixture
def session(monkeypatch):
    s = _FakeSession()
    monkeypatch.setattr(ac, "AdminConfig", _FakeRow)
    return s


def test_default_is_raised_above_old_hardcode():
    # Прод-фидбек 22.06 #1: часа было мало, дефолт поднят.
    assert _CHUKHAN_APPEAL_POLL_MINUTES_DEFAULT >= 60
    lo, hi = CHUKHAN_APPEAL_POLL_MINUTES_BOUNDS
    assert lo <= _CHUKHAN_APPEAL_POLL_MINUTES_DEFAULT <= hi


def test_bounds_sane():
    lo, hi = CHUKHAN_APPEAL_POLL_MINUTES_BOUNDS
    assert 0 < lo < hi


def test_clamp_within_range_untouched():
    lo, hi = CHUKHAN_APPEAL_POLL_MINUTES_BOUNDS
    assert clamp_appeal_poll_minutes(lo) == lo
    assert clamp_appeal_poll_minutes(hi) == hi
    mid = (lo + hi) // 2
    assert clamp_appeal_poll_minutes(mid) == mid


def test_clamp_out_of_range():
    lo, hi = CHUKHAN_APPEAL_POLL_MINUTES_BOUNDS
    assert clamp_appeal_poll_minutes(0) == lo
    assert clamp_appeal_poll_minutes(-100) == lo
    assert clamp_appeal_poll_minutes(10**9) == hi


def test_clamp_garbage_falls_back_to_default():
    assert clamp_appeal_poll_minutes("мусор") == _CHUKHAN_APPEAL_POLL_MINUTES_DEFAULT  # type: ignore[arg-type]
    assert clamp_appeal_poll_minutes(None) == _CHUKHAN_APPEAL_POLL_MINUTES_DEFAULT  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_returns_default_when_key_absent(session):
    assert (
        await get_chukhan_appeal_poll_minutes(session)
        == _CHUKHAN_APPEAL_POLL_MINUTES_DEFAULT
    )


@pytest.mark.asyncio
async def test_set_then_get_roundtrip(session):
    await set_chukhan_appeal_poll_minutes(session, 720)
    assert await get_chukhan_appeal_poll_minutes(session) == 720


@pytest.mark.asyncio
async def test_set_clamps_out_of_range(session):
    lo, hi = CHUKHAN_APPEAL_POLL_MINUTES_BOUNDS
    await set_chukhan_appeal_poll_minutes(session, 5)
    assert await get_chukhan_appeal_poll_minutes(session) == lo
    await set_chukhan_appeal_poll_minutes(session, hi + 5000)
    assert await get_chukhan_appeal_poll_minutes(session) == hi
