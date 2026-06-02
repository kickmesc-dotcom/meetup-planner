"""GHG7 P5: тесты чистого ядра медиа-реакций (без БД/aiogram).

Покрывает substitute_username, pick_phrase/pick_emoji, tick_chance, roll_chance.
Детерминизм рандома — через random.Random(seed).
"""
from __future__ import annotations

import random

from app.services.media_reactions import (
    WAIT_TICKS_MIN,
    pick_emoji,
    pick_phrase,
    roll_chance,
    substitute_username,
    tick_chance,
)


def test_substitute_username_replaces_all():
    assert substitute_username("Хорошо постарался %username%", "Митян") == "Хорошо постарался Митян"
    assert substitute_username("%username% мемолог, %username%!", "Дрон") == "Дрон мемолог, Дрон!"


def test_substitute_username_no_placeholder():
    assert substitute_username("просто фраза", "Митян") == "просто фраза"


def test_pick_phrase_empty_returns_none():
    assert pick_phrase([]) is None


def test_pick_phrase_from_nonempty():
    rng = random.Random(42)
    assert pick_phrase(["a", "b", "c"], rng) in {"a", "b", "c"}


def test_pick_emoji_empty_returns_none():
    assert pick_emoji([]) is None


def test_pick_emoji_from_nonempty():
    rng = random.Random(1)
    assert pick_emoji(["🔥", "😁"], rng) in {"🔥", "😁"}


def test_tick_chance_endpoints():
    n = len(WAIT_TICKS_MIN)  # 10
    # Первый тик = база, последний = потолок.
    assert tick_chance(0, base_pct=10, max_pct=50, n_ticks=n) == 10
    assert tick_chance(n - 1, base_pct=10, max_pct=50, n_ticks=n) == 50


def test_tick_chance_monotonic_increasing():
    n = len(WAIT_TICKS_MIN)
    vals = [tick_chance(i, 10, 50, n) for i in range(n)]
    assert vals == sorted(vals)  # не убывает
    assert vals[0] == 10 and vals[-1] == 50


def test_tick_chance_clamps_index():
    n = len(WAIT_TICKS_MIN)
    # Индекс за границами зажимается, не выходит за base/max.
    assert tick_chance(-5, 10, 50, n) == 10
    assert tick_chance(999, 10, 50, n) == 50


def test_tick_chance_single_tick():
    assert tick_chance(0, base_pct=10, max_pct=50, n_ticks=1) == 50


def test_roll_chance_boundaries():
    assert roll_chance(0) is False
    assert roll_chance(100) is True
    assert roll_chance(-10) is False
    assert roll_chance(150) is True


def test_roll_chance_deterministic_with_seed():
    # random()*100 < pct. seed подбирает первый roll ~0.639 → *100=63.9.
    rng = random.Random(0)
    first = rng.random() * 100  # 63.9...
    rng2 = random.Random(0)
    assert roll_chance(int(first) + 1, rng2) is True
    rng3 = random.Random(0)
    assert roll_chance(int(first) - 1, rng3) is False
