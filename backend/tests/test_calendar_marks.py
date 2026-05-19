"""Тесты для GHG6 BD4: чистая логика build_marks."""
from __future__ import annotations

from datetime import date

from app.api.routes_calendar import build_marks


def test_loser_inside_window():
    out = build_marks(
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        loser_rolls=[(date(2026, 5, 10), 7)],
        chukhan_weeks=[],
    )
    assert [(m.date, m.user_id, m.type) for m in out] == [
        (date(2026, 5, 10), 7, "loser"),
    ]


def test_loser_outside_window_dropped():
    out = build_marks(
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        loser_rolls=[(date(2026, 4, 30), 7), (date(2026, 5, 31), 7)],
        chukhan_weeks=[],
    )
    assert out == []  # граница end_date — exclusive, start_date — inclusive


def test_loser_dedup_same_day_same_user():
    out = build_marks(
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        loser_rolls=[(date(2026, 5, 10), 7), (date(2026, 5, 10), 7)],
        chukhan_weeks=[],
    )
    assert len(out) == 1


def test_chukhan_expands_to_7_days():
    out = build_marks(
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        loser_rolls=[],
        # Понедельник 2026-05-11. Должно превратиться в 7 marks: 11..17 мая.
        chukhan_weeks=[(date(2026, 5, 11), 3)],
    )
    assert [m.date for m in out] == [date(2026, 5, 11 + i) for i in range(7)]
    assert all(m.user_id == 3 and m.type == "chukhan" for m in out)


def test_chukhan_week_partially_outside_window():
    # Окно — только пн 2026-05-11; неделя стартует в этот же день,
    # но 6 из 7 marks (вт..вс) должны отрезаться по end_date.
    out = build_marks(
        start_date=date(2026, 5, 11),
        end_date=date(2026, 5, 12),  # exclusive
        loser_rolls=[],
        chukhan_weeks=[(date(2026, 5, 11), 3)],
    )
    assert len(out) == 1
    assert out[0].date == date(2026, 5, 11)


def test_chukhan_week_starts_before_window_tail_inside():
    # Неделя 2026-05-04..2026-05-10. Окно 2026-05-08..2026-05-15.
    # Должны попасть пт/сб/вс (8/9/10) — 3 marks.
    out = build_marks(
        start_date=date(2026, 5, 8),
        end_date=date(2026, 5, 15),
        loser_rolls=[],
        chukhan_weeks=[(date(2026, 5, 4), 5)],
    )
    assert [m.date for m in out] == [
        date(2026, 5, 8),
        date(2026, 5, 9),
        date(2026, 5, 10),
    ]


def test_loser_and_chukhan_both_kept_on_same_day():
    # Разные `type` — обе отметки выживают (фронт показывает обе).
    out = build_marks(
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        loser_rolls=[(date(2026, 5, 11), 3)],
        chukhan_weeks=[(date(2026, 5, 11), 3)],
    )
    assert len(out) >= 2
    same_day = [m for m in out if m.date == date(2026, 5, 11) and m.user_id == 3]
    types = {m.type for m in same_day}
    assert types == {"loser", "chukhan"}


def test_output_sorted_by_date_user_type():
    out = build_marks(
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        loser_rolls=[(date(2026, 5, 20), 2), (date(2026, 5, 10), 5)],
        chukhan_weeks=[],
    )
    dates = [m.date for m in out]
    assert dates == sorted(dates)
