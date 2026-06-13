"""Точечная правка use_counts (вариант 2 из прод-фидбека): ручной сброс
счётчика отдельной фразы из админки.

Async-БД-стенда нет — подменяем `AdminConfig`-хранилище лёгким фейком сессии
поверх dict (повторяет контракт `_get_value`/`_set_value`: session.get →
add/commit). Покрываем set_one_use_count: выставление, обнуление (count<=0 →
запись удаляется, вес возвращается к 1.0), идемпотентность по hash.
"""
from __future__ import annotations

import pytest

from app.services import admin_config as ac
from app.services.phrase_weights import (
    get_use_counts,
    increment_use_count,
    phrase_hash,
    set_one_use_count,
    weighted_choice,
)

KEY = "loser_reasons.use_counts"


class _FakeRow:
    def __init__(self, key: str, value: str) -> None:
        self.key = key
        self.value = value


class _FakeSession:
    """Минимальный стенд: словарь key→_FakeRow, как одна таблица AdminConfig."""

    def __init__(self) -> None:
        self._store: dict[str, _FakeRow] = {}

    async def get(self, model, key):  # noqa: ANN001 — повторяем сигнатуру session.get
        return self._store.get(key)

    def add(self, row) -> None:  # noqa: ANN001
        self._store[row.key] = row

    async def commit(self) -> None:
        pass


@pytest.fixture
def session(monkeypatch):
    s = _FakeSession()
    # _set_value создаёт AdminConfig(key=..., value=...) — подменяем на _FakeRow.
    monkeypatch.setattr(ac, "AdminConfig", _FakeRow)
    return s


@pytest.mark.asyncio
async def test_set_one_use_count_sets_value(session):
    await set_one_use_count(session, KEY, "опять проспал", 5)
    counts = await get_use_counts(session, KEY)
    assert counts[phrase_hash("опять проспал")] == 5


@pytest.mark.asyncio
async def test_set_one_use_count_zero_removes_entry(session):
    await set_one_use_count(session, KEY, "сам себе буратино", 3)
    await set_one_use_count(session, KEY, "сам себе буратино", 0)
    counts = await get_use_counts(session, KEY)
    # count<=0 — запись УДАЛЕНА (не хранится как 0), вес снова 1.0.
    assert phrase_hash("сам себе буратино") not in counts


@pytest.mark.asyncio
async def test_set_one_use_count_zero_restores_full_weight(session):
    # После сброса фраза в weighted_choice имеет максимальный вес (как нетронутая).
    await set_one_use_count(session, KEY, "залип", 9)
    await set_one_use_count(session, KEY, "залип", 0)
    counts = await get_use_counts(session, KEY)
    w = 1.0 / (1.0 + counts.get(phrase_hash("залип"), 0))
    assert w == 1.0


@pytest.mark.asyncio
async def test_set_one_use_count_overwrites_increment(session):
    await increment_use_count(session, KEY, "проспал")
    await increment_use_count(session, KEY, "проспал")
    await set_one_use_count(session, KEY, "проспал", 1)
    counts = await get_use_counts(session, KEY)
    assert counts[phrase_hash("проспал")] == 1


@pytest.mark.asyncio
async def test_set_one_use_count_independent_phrases(session):
    await set_one_use_count(session, KEY, "первая", 4)
    await set_one_use_count(session, KEY, "вторая", 0)
    counts = await get_use_counts(session, KEY)
    assert counts[phrase_hash("первая")] == 4
    assert phrase_hash("вторая") not in counts


def test_weighted_choice_respects_manual_zero():
    # Прямая проверка эффекта: фраза со сброшенным счётчиком (нет в dict)
    # весит больше, чем многократно использованная.
    pool = ["свежая", "заезженная"]
    counts = {phrase_hash("заезженная"): 50}  # "свежая" отсутствует → вес 1.0
    hits = {"свежая": 0, "заезженная": 0}
    # Детерминизма нет, но при весах 1.0 vs ~0.02 «свежая» должна доминировать.
    import random

    random.seed(1337)
    for _ in range(200):
        hits[weighted_choice(pool, counts)] += 1
    assert hits["свежая"] > hits["заезженная"] * 5
