"""GHG8 T2.1 (прод-фидбек п.5/10): автоподбор не должен схлопывать
пересекающиеся пресеты.

Баг: пользователь задал слоты внахлёст (17-21/18-22/19-23/20-00), нажал
автоподбор — опрос не стартовал, т.к. жадный де-оверлап оставлял ровно ОДИН
непересекающийся слот → `len(slots) < 2` → `not_enough_slots`. Пресеты —
курируемые варианты, между которыми и идёт голосование; в preset-режиме
де-оверлап отключён, отдаём top_n по score как есть. Скользящее окно
(fallback) де-оверлап сохраняет (там окна избыточно пересекаются).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.db.models import AvailabilityRange, User
from app.services.auto_pick import find_best_slots


class _Result:
    def __init__(self, data: list[Any]) -> None:
        self._data = data

    def all(self) -> list[Any]:
        return self._data


class _FakeSession:
    """find_best_slots зовёт scalars дважды: (1) users, (2) ranges."""

    def __init__(self, users: list[User], ranges: list[AvailabilityRange]) -> None:
        self._users = users
        self._ranges = ranges
        self._call = 0

    async def scalars(self, _stmt: Any) -> _Result:
        self._call += 1
        return _Result(self._users if self._call == 1 else self._ranges)


def _user(uid: int) -> User:
    u = User()
    u.id = uid
    u.telegram_id = 1000 + uid
    u.display_name = f"U{uid}"
    return u


def _range(uid: int, start: datetime, end: datetime, *, status: int = 1) -> AvailabilityRange:
    r = AvailabilityRange()
    r.id = uid * 100
    r.user_id = uid
    r.starts_at = start
    r.ends_at = end
    r.status = status
    r.confidence = 3
    return r


# Тестовый день: окно — целиком 15-е, чтобы все пресеты попали внутрь.
_DAY = datetime(2026, 6, 15, 0, 0, tzinfo=timezone.utc)
_WINDOW_START = _DAY
_WINDOW_END = _DAY + timedelta(days=1)

# Пользователь свободен весь день — каждый пресет полностью покрыт.
def _free_all_day_session(n_users: int = 2) -> _FakeSession:
    users = [_user(i) for i in range(1, n_users + 1)]
    ranges = [_range(u.id, _DAY, _WINDOW_END) for u in users]
    return _FakeSession(users, ranges)


# Пресеты внахлёст из фидбека: 17-21, 18-22, 19-23, 20-00(=24:00→конец дня).
_OVERLAP_PRESETS = [
    {"start": "17:00", "end": "21:00"},
    {"start": "18:00", "end": "22:00"},
    {"start": "19:00", "end": "23:00"},
    {"start": "20:00", "end": "23:59"},
]


@pytest.mark.asyncio
async def test_overlapping_presets_all_returned() -> None:
    # Главный баг п.5/10: 4 пересекающихся пресета → должны вернуться все 4
    # (top_n=5), а не схлопнуться в один.
    session = _free_all_day_session()
    slots = await find_best_slots(
        session,  # type: ignore[arg-type]
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        top_n=5,
        presets=_OVERLAP_PRESETS,
    )
    assert len(slots) == 4, [s.starts_at.hour for s in slots]
    # Достаточно вариантов для старта опроса (порог >= 2).
    assert len(slots) >= 2


@pytest.mark.asyncio
async def test_presets_respect_top_n() -> None:
    # top_n остаётся верхней границей даже в preset-режиме.
    session = _free_all_day_session()
    slots = await find_best_slots(
        session,  # type: ignore[arg-type]
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        top_n=2,
        presets=_OVERLAP_PRESETS,
    )
    assert len(slots) == 2


@pytest.mark.asyncio
async def test_sliding_window_fallback_still_dedups_overlap() -> None:
    # Без пресетов (fallback) де-оверлап ДОЛЖЕН остаться: скользящее окно
    # 2ч с шагом 1ч даёт пересекающиеся окна — оставляем непересекающиеся.
    session = _free_all_day_session()
    slots = await find_best_slots(
        session,  # type: ignore[arg-type]
        window_start=_DAY + timedelta(hours=17),
        window_end=_DAY + timedelta(hours=23),
        duration=timedelta(hours=2),
        step=timedelta(hours=1),
        top_n=5,
        presets=None,
    )
    # Соседние выбранные слоты не пересекаются.
    for a, b in zip(slots, slots[1:]):
        assert a.ends_at <= b.starts_at or a.starts_at >= b.ends_at
