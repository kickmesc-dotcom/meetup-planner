"""GHG7 P2.1.a — эндпоинт /titles/current.

БД-интеграция (worm/chukhan/loser/birthday SELECT'ы) проверяется руками —
async-sqlite-стенда в проекте нет (см. test_worm заголовок). Здесь — чистая
логика выбора «главного лоха» с тай-брейком, единственная нетривиальная
часть эндпоинта.
"""
from __future__ import annotations

from app.api.routes_calendar import pick_main_loser


def test_pick_main_loser_empty_is_none():
    assert pick_main_loser({}) is None


def test_pick_main_loser_single():
    assert pick_main_loser({7: 3}) == 7


def test_pick_main_loser_max_count_wins():
    assert pick_main_loser({1: 2, 2: 5, 3: 1}) == 2


def test_pick_main_loser_tie_breaks_to_smaller_uid():
    # 2 и 9 оба по 4 ролла → берём меньший user_id (детерминизм).
    assert pick_main_loser({9: 4, 2: 4, 5: 1}) == 2


def test_pick_main_loser_zero_counts():
    # Все по нулю (теоретически) — всё равно детерминированно меньший uid.
    assert pick_main_loser({3: 0, 1: 0}) == 1
