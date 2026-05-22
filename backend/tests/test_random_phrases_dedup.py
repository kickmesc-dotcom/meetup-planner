"""GHG6 E4: дедуп цитат в шизо-цитатнике.

Пользователь сообщал, что в 70% случаев (особенно у Русланище) в одном
сообщении дважды-трижды повторяется одна и та же фраза с микропереформулировкой.
Корень — `[random.choice(user_pool) for _ in range(n)]` (выбор с возвратом).
`dedup_chunks` строит уникальный набор через `difflib.SequenceMatcher` на
нормализованных строках.

Тестируем чистую функцию (без БД) — она единственная меняет поведение.
"""
from __future__ import annotations

import random

from app.services.random_phrases import dedup_chunks, _normalize_chunk


def test_normalize_collapses_whitespace_and_lowercases():
    assert _normalize_chunk("  Привет,  Мир  ") == "привет, мир"
    assert _normalize_chunk("Test\nMulti\tline") == "test multi line"


def test_exact_duplicates_removed():
    picked = ["так-то да", "так-то да", "так-то да"]
    out = dedup_chunks(picked, all_pool=picked, target_n=3)
    # Все три — точные дубли, пул тоже пуст для добора. Остаётся один.
    assert len(out) == 1
    assert out[0] == "так-то да"


def test_near_duplicates_removed_by_ratio():
    # Микропереформулировки одной мысли — типичный кейс Русланище.
    picked = [
        "ну я короче пошёл спать",
        "Ну я короче пошёл спать!",     # ratio ~0.95 — дубль
        "ну я, короче, пошёл спать",    # ratio ~0.90 — дубль
        "вообще я ушёл",                # совсем другое
    ]
    out = dedup_chunks(picked, all_pool=picked, target_n=4)
    assert len(out) == 2
    assert out[0] == "ну я короче пошёл спать"
    assert "вообще я ушёл" in out


def test_filler_from_pool_when_picked_has_dupes():
    # picked содержит дубли, но pool богат — должны добрать до target_n.
    random.seed(42)
    picked = ["а", "а", "а"]  # все дубли друг друга
    pool = ["а", "б совсем другое", "в тоже отличное", "г ещё одно"]
    out = dedup_chunks(picked, all_pool=pool, target_n=3)
    assert len(out) == 3
    # Первый — из picked, остальные — добор из пула.
    assert out[0] == "а"


def test_returns_what_it_has_when_pool_too_small():
    picked = ["один", "один", "один"]
    pool = picked  # пул совпадает, добирать не из чего
    out = dedup_chunks(picked, all_pool=pool, target_n=5)
    assert out == ["один"]  # один уникальный элемент, граничный случай


def test_threshold_strictness_below_85():
    # Похожие на ~80% — не должны считаться дублями (порог 0.85).
    picked = [
        "сегодня дождь идёт",
        "вчера солнце было",
    ]
    out = dedup_chunks(picked, all_pool=picked, target_n=2)
    assert len(out) == 2  # они достаточно разные


def test_empty_or_whitespace_dropped():
    picked = ["", "   ", "\n\t", "нормальная цитата"]
    out = dedup_chunks(picked, all_pool=picked, target_n=4)
    assert out == ["нормальная цитата"]


def test_target_zero_returns_empty():
    assert dedup_chunks(["а", "б"], all_pool=["а", "б"], target_n=0) == []


def test_empty_picked_returns_empty():
    assert dedup_chunks([], all_pool=["а", "б"], target_n=3) == []
