"""GHG8 J.1: тесты чистого ядра метаданных фраз (без БД).

Покрывает normalize_source / is_hidden / visible_phrases / update_entry /
items_for / parse_meta / normalize_meta. Async-обёртки (load_meta/save_meta/
effective_pool/set_flags/bulk_set_flags/prune) ходят в admin_config —
тестируются вручную (async-БД-стенда в проекте нет).
"""
from __future__ import annotations

from app.services.phrase_meta import (
    META_KEY,
    SOURCE_AI,
    SOURCE_IMPORT,
    SOURCE_MANUAL,
    entry_for,
    filter_by_source_mode,
    is_hidden,
    items_for,
    normalize_meta,
    normalize_source,
    parse_meta,
    source_of,
    update_entry,
    visible_phrases,
)
from app.services.phrase_weights import phrase_hash


def test_meta_key_stable():
    # Ключ в admin_config не должен «переезжать» без миграции.
    assert META_KEY == "phrases.meta"


# ---------------------------------------------------------------- normalize_source

def test_normalize_source_known():
    assert normalize_source("ai") == SOURCE_AI
    assert normalize_source("IMPORT") == SOURCE_IMPORT
    assert normalize_source("  manual ") == SOURCE_MANUAL


def test_normalize_source_fallback_and_garbage():
    assert normalize_source(None) == SOURCE_MANUAL
    assert normalize_source(123) == SOURCE_MANUAL
    assert normalize_source("говно") == SOURCE_MANUAL


# ---------------------------------------------------------------- defaults

def test_missing_entry_is_manual_and_visible():
    meta: dict = {}
    assert entry_for(meta, "loser_reasons", "фраза") == {}
    assert is_hidden(meta, "loser_reasons", "фраза") is False
    assert source_of(meta, "loser_reasons", "фраза") == SOURCE_MANUAL


def test_visible_phrases_filters_hidden_preserving_order():
    phrases = ["a", "b", "c", "d"]
    meta = {
        "p": {
            phrase_hash("b"): {"hidden": True},
            phrase_hash("d"): {"hidden": True, "source": SOURCE_AI},
        }
    }
    assert visible_phrases(meta, "p", phrases) == ["a", "c"]


# ---------------------------------------------------------------- source mode

def test_filter_by_source_mode_manual_and_ai():
    """Э19: глобальный свитчер ручные/ИИ/оба на чистом ядре.

    `import` = ручной путь, `persona` = генерация (ИИ), как дроп.
    """
    phrases = ["ручная", "дроп", "импорт", "персона"]
    meta = {
        "p": {
            phrase_hash("дроп"): {"source": SOURCE_AI},
            phrase_hash("импорт"): {"source": SOURCE_IMPORT},
            phrase_hash("персона"): {"source": "persona"},
        }
    }
    assert filter_by_source_mode(meta, "p", phrases, "both") == phrases
    assert filter_by_source_mode(meta, "p", phrases, "manual") == ["ручная", "импорт"]
    assert filter_by_source_mode(meta, "p", phrases, "ai") == ["дроп", "персона"]
    # Неизвестный режим — безопасный дефолт «оба».
    assert filter_by_source_mode(meta, "p", phrases, "wat") == phrases


def test_visible_phrases_all_hidden_returns_empty():
    phrases = ["a"]
    meta = {"p": {phrase_hash("a"): {"hidden": True}}}
    assert visible_phrases(meta, "p", phrases) == []


def test_visible_phrases_empty_pool():
    assert visible_phrases({}, "p", []) == []


# ---------------------------------------------------------------- update_entry

def test_update_entry_sets_hidden_and_source():
    meta: dict = {}
    entry = update_entry(meta, "p", "фраза", source=SOURCE_AI, hidden=True)
    assert entry["source"] == SOURCE_AI
    assert entry["hidden"] is True
    assert is_hidden(meta, "p", "фраза") is True
    assert source_of(meta, "p", "фраза") == SOURCE_AI
    # added_at проставляется автоматически и остаётся немым.
    assert entry.get("added_at")


def test_update_entry_removes_default_entry():
    # Скрыли, а потом вернули и источник оставили дефолтным → запись исчезает
    # (держим phrases.meta компактным).
    meta: dict = {}
    update_entry(meta, "p", "фраза", hidden=True)
    assert "p" in meta
    update_entry(meta, "p", "фраза", hidden=False)
    assert meta == {}


def test_update_entry_keeps_entry_when_source_non_default():
    meta: dict = {}
    update_entry(meta, "p", "фраза", source=SOURCE_AI, hidden=False)
    # visible, но источник ai — запись нужна (иначе потеряем метку ИИ-слопа).
    assert is_hidden(meta, "p", "фраза") is False
    assert source_of(meta, "p", "фраза") == SOURCE_AI


def test_update_entry_partial_keeps_other_field():
    meta: dict = {}
    update_entry(meta, "p", "фраза", source=SOURCE_AI)
    update_entry(meta, "p", "фраза", hidden=True)
    assert source_of(meta, "p", "фраза") == SOURCE_AI
    assert is_hidden(meta, "p", "фраза") is True


def test_update_entry_records_added_by():
    meta: dict = {}
    entry = update_entry(meta, "p", "фраза", source=SOURCE_AI, added_by=42)
    assert entry["added_by"] == 42


def test_update_entry_isolated_per_pool():
    meta: dict = {}
    update_entry(meta, "pool_a", "x", hidden=True)
    assert is_hidden(meta, "pool_a", "x") is True
    assert is_hidden(meta, "pool_b", "x") is False


# ---------------------------------------------------------------- items_for

def test_items_for_joins_in_pool_order():
    phrases = ["первая", "вторая", "третья"]
    meta = {"p": {phrase_hash("вторая"): {"source": SOURCE_AI, "hidden": True}}}
    items = items_for(meta, "p", phrases)
    assert [i["phrase"] for i in items] == phrases
    assert items[1] == {"phrase": "вторая", "source": SOURCE_AI, "hidden": True}
    assert items[0] == {"phrase": "первая", "source": SOURCE_MANUAL, "hidden": False}
    assert items[2] == {"phrase": "третья", "source": SOURCE_MANUAL, "hidden": False}


# ---------------------------------------------------------------- parse/normalize

def test_parse_meta_none_and_empty():
    assert parse_meta(None) == {}
    assert parse_meta("") == {}


def test_parse_meta_invalid_json():
    assert parse_meta("{не json") == {}
    assert parse_meta("[1,2,3]") == {}


def test_parse_meta_roundtrip():
    meta = {"p": {phrase_hash("x"): {"source": SOURCE_AI, "hidden": True}}}
    import json

    assert parse_meta(json.dumps(meta, ensure_ascii=False)) == meta


def test_normalize_meta_drops_garbage():
    data = {
        "p": {phrase_hash("x"): {"source": "ai"}},
        123: {"bad": 1},          # не строковый пул
        "q": "не словарь",          # не словарь записей
        "r": {"h": "не словарь"},   # запись не словарь
    }
    out = normalize_meta(data)
    assert set(out.keys()) == {"p"}
    assert out["p"][phrase_hash("x")]["source"] == "ai"


def test_normalize_meta_drops_empty_pool():
    assert normalize_meta({"p": {}}) == {}
    assert normalize_meta(None) == {}
