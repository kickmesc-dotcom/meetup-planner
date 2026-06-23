"""GHG8 T3.1: тесты чистого ядра снапшота фраз (без БД).

Покрывает merge_pool (дедуп + порядок) и validate_snapshot (формат-маркер,
типы секций, опциональность). build_snapshot/apply_snapshot ходят в БД —
тестируются вручную (async-БД-стенда в проекте нет).
"""
from __future__ import annotations

from app.services.phrase_snapshot import (
    SNAPSHOT_FORMAT,
    SNAPSHOT_VERSION,
    _POOL_KEYS,
    _USE_COUNT_KEYS,
    _use_count_key_map,
    merge_pool,
    validate_snapshot,
)


def test_merge_pool_dedup_preserves_order():
    assert merge_pool(["a", "b"], ["b", "c", "a", "d"]) == ["a", "b", "c", "d"]


def test_merge_pool_strips_and_drops_blank():
    assert merge_pool(["  a ", ""], [" b", "a", "   "]) == ["a", "b"]


def test_merge_pool_empty_sides():
    assert merge_pool([], ["x", "x"]) == ["x"]
    assert merge_pool(["y"], []) == ["y"]
    assert merge_pool([], []) == []


def _valid_snapshot() -> dict:
    return {
        "format": SNAPSHOT_FORMAT,
        "version": SNAPSHOT_VERSION,
        "pools": {"loser_reasons": ["a", "b"], "advice": []},
        "use_counts": {"loser_reasons": {"abcd": 3}},
        "personas": [{"telegram_id": 1, "display_name": "X", "persona_text": "t"}],
    }


def test_validate_accepts_full_snapshot():
    ok, err = validate_snapshot(_valid_snapshot())
    assert ok, err


def test_validate_accepts_minimal_snapshot():
    # Только маркер + версия — секции опциональны.
    ok, err = validate_snapshot({"format": SNAPSHOT_FORMAT, "version": 1})
    assert ok, err


def test_validate_rejects_non_dict():
    ok, _ = validate_snapshot(["not", "a", "dict"])
    assert not ok


def test_validate_rejects_wrong_format():
    snap = _valid_snapshot()
    snap["format"] = "something-else"
    ok, _ = validate_snapshot(snap)
    assert not ok


def test_validate_rejects_missing_version():
    snap = _valid_snapshot()
    del snap["version"]
    ok, _ = validate_snapshot(snap)
    assert not ok


def test_validate_rejects_bad_pool_type():
    snap = _valid_snapshot()
    snap["pools"]["loser_reasons"] = "not-a-list"
    ok, _ = validate_snapshot(snap)
    assert not ok


def test_validate_rejects_non_string_in_pool():
    snap = _valid_snapshot()
    snap["pools"]["advice"] = ["ok", 123]
    ok, _ = validate_snapshot(snap)
    assert not ok


def test_validate_rejects_persona_without_keys():
    snap = _valid_snapshot()
    snap["personas"] = [{"telegram_id": 1}]  # нет persona_text
    ok, _ = validate_snapshot(snap)
    assert not ok


def test_validate_rejects_bad_use_counts_type():
    snap = _valid_snapshot()
    snap["use_counts"] = ["x"]
    ok, _ = validate_snapshot(snap)
    assert not ok


# ----- T3.6: новые пулы червя-господина учтены в снапшоте -----

def test_worm_master_pools_enumerated():
    for name in (
        "worm_master_prefixes",
        "worm_master_suffixes",
        "worm_master_agrees",
        "worm_master_nag",
        "worm_punish",
        "worm_announce_lines",
    ):
        assert name in _POOL_KEYS


def test_worm_use_count_pools_consistent():
    # use_counts ведём для prefix/suffix/agree/punish; nag/announce — нет.
    for name in (
        "worm_master_prefixes",
        "worm_master_suffixes",
        "worm_master_agrees",
        "worm_punish",
    ):
        assert name in _USE_COUNT_KEYS
    assert "worm_master_nag" not in _USE_COUNT_KEYS
    assert "worm_announce_lines" not in _USE_COUNT_KEYS


def test_use_count_key_map_matches_use_count_keys():
    # каждый снапшот-пул со счётчиком имеет запись в key_map, и наоборот.
    assert set(_use_count_key_map().keys()) == set(_USE_COUNT_KEYS)


def test_use_count_key_map_values_unique():
    vals = list(_use_count_key_map().values())
    assert len(vals) == len(set(vals)), "ключи use_counts в admin_config не должны дублироваться"
