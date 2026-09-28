"""H.4 + J.1: импорт снапшота — дельта-сводка и тег источника.

Async-БД-стенда в проекте нет, поэтому подменяем хранилище `admin_config` лёгким
фейком сессии поверх dict (тот же приём, что в `test_phrase_use_counts.py`).
Проверяем ровно то, что добавили в фидбеке:

- H.4 (01.07 #1): `summary.pools[pool]` несёт `before/added/removed`, а не только
  итоговый `count` — на этом строится «+N / −M» в админке;
- J.1: параметр `source` метит импортируемые фразы (`ai` для контент-дропа), а
  секция `meta` снапшота восстанавливает `source/hidden`.
"""
from __future__ import annotations

import pytest

from app.services import admin_config as ac
from app.services.phrase_meta import is_hidden, load_meta, source_of
from app.services.phrase_snapshot import (
    SNAPSHOT_FORMAT,
    SNAPSHOT_VERSION,
    apply_snapshot,
)
from app.services.phrase_weights import phrase_hash


class _FakeRow:
    def __init__(self, key: str, value: str) -> None:
        self.key = key
        self.value = value


class _FakeSession:
    """Словарь key→row, повторяющий контракт `_get_value`/`_set_value`."""

    def __init__(self) -> None:
        self._store: dict[str, _FakeRow] = {}

    async def get(self, model, key):  # noqa: ANN001 — сигнатура session.get
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


def _snap(**over) -> dict:
    snap = {"format": SNAPSHOT_FORMAT, "version": SNAPSHOT_VERSION}
    snap.update(over)
    return snap


# ------------------------------------------------------------------- H.4: дельта


@pytest.mark.asyncio
async def test_merge_reports_delta(session):
    before = await ac.get_loser_reasons(session)
    incoming = [*before, "свежая фраза из дропа", "ещё одна свежая"]
    summary = await apply_snapshot(
        session, _snap(pools={"loser_reasons": incoming}), mode="merge"
    )
    s = summary["pools"]["loser_reasons"]
    assert s["before"] == len(set(before))
    assert s["added"] == 2
    assert s["removed"] == 0
    assert s["count"] == s["before"] + 2


@pytest.mark.asyncio
async def test_replace_reports_removals(session):
    before = await ac.get_loser_reasons(session)
    summary = await apply_snapshot(
        session, _snap(pools={"loser_reasons": ["единственная"]}), mode="replace"
    )
    s = summary["pools"]["loser_reasons"]
    assert s["count"] == 1
    assert s["added"] == 1
    assert s["removed"] == len(set(before))
    assert s["before"] == len(set(before))


@pytest.mark.asyncio
async def test_merge_is_idempotent_for_delta(session):
    """Повторный merge того же снапшота даёт нулевую дельту (дубли не плодятся)."""
    await apply_snapshot(
        session, _snap(pools={"loser_reasons": ["дубль-проверка"]}), mode="merge"
    )
    summary = await apply_snapshot(
        session, _snap(pools={"loser_reasons": ["дубль-проверка"]}), mode="merge"
    )
    s = summary["pools"]["loser_reasons"]
    assert (s["added"], s["removed"]) == (0, 0)


@pytest.mark.asyncio
async def test_delta_only_for_pools_present_in_snapshot(session):
    summary = await apply_snapshot(
        session, _snap(pools={"advice": ["Да."]}), mode="merge"
    )
    assert set(summary["pools"]) == {"advice"}


@pytest.mark.asyncio
async def test_unknown_mode_rejected(session):
    with pytest.raises(ValueError):
        await apply_snapshot(session, _snap(pools={}), mode="nope")


# -------------------------------------------------------------- J.1: тег и мета


@pytest.mark.asyncio
async def test_source_tags_only_incoming_phrases(session):
    before = await ac.get_loser_reasons(session)
    old = before[0]
    await apply_snapshot(
        session,
        _snap(pools={"loser_reasons": ["новьё от ИИ"]}),
        mode="merge",
        source="ai",
    )
    meta = await load_meta(session)
    assert source_of(meta, "loser_reasons", "новьё от ИИ") == "ai"
    # Старая фраза не помечается: тег получает только то, что пришло в импорте.
    assert source_of(meta, "loser_reasons", old) == "manual"


@pytest.mark.asyncio
async def test_no_source_flag_keeps_manual(session):
    await apply_snapshot(
        session, _snap(pools={"loser_reasons": ["без тега"]}), mode="merge"
    )
    meta = await load_meta(session)
    assert source_of(meta, "loser_reasons", "без тега") == "manual"


@pytest.mark.asyncio
async def test_snapshot_meta_section_restored(session):
    summary = await apply_snapshot(
        session,
        _snap(
            pools={"loser_reasons": ["фраза с метой"]},
            meta={
                "loser_reasons": {
                    phrase_hash("фраза с метой"): {"source": "ai", "hidden": True}
                }
            },
        ),
        mode="merge",
    )
    meta = await load_meta(session)
    assert is_hidden(meta, "loser_reasons", "фраза с метой") is True
    assert source_of(meta, "loser_reasons", "фраза с метой") == "ai"
    assert summary["meta"] == {"merged": 1}


@pytest.mark.asyncio
async def test_meta_section_merges_without_dropping_existing(session):
    await apply_snapshot(
        session,
        _snap(
            pools={"loser_reasons": ["a", "b"]},
            meta={"loser_reasons": {phrase_hash("a"): {"source": "ai"}}},
        ),
        mode="merge",
    )
    await apply_snapshot(
        session,
        _snap(
            pools={"loser_reasons": ["b"]},
            meta={"loser_reasons": {phrase_hash("b"): {"hidden": True}}},
        ),
        mode="merge",
    )
    meta = await load_meta(session)
    assert source_of(meta, "loser_reasons", "a") == "ai"
    assert is_hidden(meta, "loser_reasons", "b") is True
