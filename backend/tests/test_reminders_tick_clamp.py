"""GHG8 G (п.14): верхний кламп тика напоминаний 120→360 мин.

Async-БД-стенда нет — подменяем хранилище `AdminConfig` лёгким фейком сессии
поверх dict (тот же приём, что в test_phrase_use_counts): session.get →
add/commit. Покрываем get/set_reminders_tick_minutes: нижняя граница (1),
новый потолок (360), отсечение выше потолка и значение внутри диапазона.
"""
from __future__ import annotations

import pytest

from app.services import admin_config as ac
from app.services.admin_config import (
    AdminConfig,
    get_reminders_tick_minutes,
    set_reminders_tick_minutes,
)


class _FakeSession:
    """Минимальный стенд: словарь key→AdminConfig, как одна таблица AdminConfig."""

    def __init__(self) -> None:
        self._store: dict[str, AdminConfig] = {}

    async def get(self, model, key):  # noqa: ANN001 — повторяем сигнатуру session.get
        return self._store.get(key)

    def add(self, row) -> None:  # noqa: ANN001
        self._store[row.key] = row

    async def commit(self) -> None:
        pass


@pytest.mark.asyncio
async def test_reminders_tick_new_ceiling_is_360() -> None:
    session = _FakeSession()
    # Ровно потолок проходит без отсечения (раньше срезалось бы до 120).
    await set_reminders_tick_minutes(session, 360)
    assert await get_reminders_tick_minutes(session) == 360


@pytest.mark.asyncio
async def test_reminders_tick_clamps_above_ceiling() -> None:
    session = _FakeSession()
    await set_reminders_tick_minutes(session, 10_000)
    assert await get_reminders_tick_minutes(session) == 360


@pytest.mark.asyncio
async def test_reminders_tick_floor_is_one() -> None:
    session = _FakeSession()
    await set_reminders_tick_minutes(session, 0)
    assert await get_reminders_tick_minutes(session) == 1


@pytest.mark.asyncio
async def test_reminders_tick_value_in_range_passes_through() -> None:
    session = _FakeSession()
    await set_reminders_tick_minutes(session, 360 // 2)
    assert await get_reminders_tick_minutes(session) == 180
