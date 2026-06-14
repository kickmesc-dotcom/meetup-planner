"""GHG7 P5 / GHG8 F-media-fix: тесты чистого ядра медиа-реакций (без БД/aiogram).

Покрывает substitute_username, pick_phrase/pick_emoji, roll_chance,
clamp_wait_window. Модель шанса — один честный ролл на мем (серия tick_chance
удалена). Детерминизм рандома — через random.Random(seed).
"""
from __future__ import annotations

import random

from app.services.media_reactions import (
    WAIT_WINDOW_MIN_BOUNDS,
    clamp_wait_window,
    pick_emoji,
    pick_phrase,
    roll_chance,
    substitute_username,
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


def test_clamp_wait_window_within_bounds():
    assert clamp_wait_window(15) == 15
    assert clamp_wait_window(1) == 1
    assert clamp_wait_window(360) == 360


def test_clamp_wait_window_clamps_out_of_range():
    lo, hi = WAIT_WINDOW_MIN_BOUNDS
    assert clamp_wait_window(0) == lo
    assert clamp_wait_window(-100) == lo
    assert clamp_wait_window(99999) == hi


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
