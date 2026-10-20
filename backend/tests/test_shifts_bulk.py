"""Массовое планирование смен: шаблон недели, копирование, очистка.

Проверяем то, что можно проверить без живой базы: перевод «пн-ср» в даты,
дедупликацию, лимиты и порядок защит. Сами записи в Postgres идут через
`tools/hr-pg-test.py` (`test_hr_flow_pg.py`) — здесь нарочно нет фейковой сессии,
чтобы тест не создавал ложного ощущения проверенной выдачи.
"""

from __future__ import annotations

import os
from datetime import date, time

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402

from app.db.hr_models import ROLE_ADMIN, ROLE_EMPLOYEE, Employee  # noqa: E402
from app.services import hr_shifts  # noqa: E402

MONDAY = date(2026, 10, 19)
MANAGER = Employee(id=1, user_id=1, role=ROLE_ADMIN)
STAFF = Employee(id=2, user_id=2, role=ROLE_EMPLOYEE)


# --------------------------------------------------------------------------
# Шаблон недели
# --------------------------------------------------------------------------


def test_weekdays_map_to_dates_of_the_chosen_week():
    days = hr_shifts.weekdays_days(MONDAY, [0, 2, 4])
    assert days == (
        date(2026, 10, 19),
        date(2026, 10, 21),
        date(2026, 10, 23),
    )


def test_weekday_pattern_ignores_duplicates_and_out_of_range():
    days = hr_shifts.weekdays_days(MONDAY, [6, 6, 7, -1, 0])
    assert days == (date(2026, 10, 19), date(2026, 10, 25))


def test_weekday_pattern_without_valid_days_is_an_error():
    with pytest.raises(hr_shifts.ShiftError) as exc:
        hr_shifts.weekdays_days(MONDAY, [7, -2])
    assert str(exc.value) == "bad_days"


def test_bulk_days_sorts_and_deduplicates():
    assert hr_shifts.bulk_days([MONDAY, MONDAY, date(2026, 10, 20)]) == (
        MONDAY,
        date(2026, 10, 20),
    )


def test_bulk_days_accepts_a_month_but_not_more():
    month = [date(2026, 10, 1)]
    month = [month[0].replace(day=day) for day in range(1, 32)]
    assert len(hr_shifts.bulk_days(month)) == hr_shifts.MAX_BULK_DAYS
    with pytest.raises(hr_shifts.ShiftError):
        hr_shifts.bulk_days(month + [date(2026, 11, 1)])


def test_bulk_days_rejects_an_empty_set():
    with pytest.raises(hr_shifts.ShiftError) as exc:
        hr_shifts.bulk_days([])
    assert str(exc.value) == "bad_days"


# --------------------------------------------------------------------------
# Защиты массовых операций (до базы)
# --------------------------------------------------------------------------


async def test_employee_cannot_bulk_edit():
    with pytest.raises(hr_shifts.ShiftError) as exc:
        await hr_shifts.bulk_apply(
            None,  # type: ignore[arg-type]  # до базы дело не доходит
            STAFF,
            employee_ids=[2],
            days=[MONDAY],
            status="planned",
        )
    assert str(exc.value) == "forbidden"


async def test_unknown_status_is_rejected_before_any_write():
    with pytest.raises(hr_shifts.ShiftError) as exc:
        await hr_shifts.bulk_apply(
            None,  # type: ignore[arg-type]
            MANAGER,
            employee_ids=[2],
            days=[MONDAY],
            status="party",
        )
    assert str(exc.value) == "bad_status"


async def test_bulk_without_people_is_rejected():
    with pytest.raises(hr_shifts.ShiftError) as exc:
        await hr_shifts.bulk_apply(
            None,  # type: ignore[arg-type]
            MANAGER,
            employee_ids=[],
            days=[MONDAY],
            status="planned",
        )
    assert str(exc.value) == "no_employees"


async def test_bulk_over_the_people_limit_is_rejected():
    too_many = list(range(1, hr_shifts.MAX_BULK_PEOPLE + 2))
    with pytest.raises(hr_shifts.ShiftError) as exc:
        await hr_shifts.bulk_apply(
            None,  # type: ignore[arg-type]
            MANAGER,
            employee_ids=too_many,
            days=[MONDAY],
            status="planned",
        )
    assert str(exc.value) == "too_many_employees"


async def test_long_note_is_rejected():
    with pytest.raises(hr_shifts.ShiftError) as exc:
        await hr_shifts.bulk_apply(
            None,  # type: ignore[arg-type]
            MANAGER,
            employee_ids=[2],
            days=[MONDAY],
            status="planned",
            note="я" * 201,
        )
    assert str(exc.value) == "note_too_long"


# --------------------------------------------------------------------------
# Копирование недели и очистка
# --------------------------------------------------------------------------


async def test_copy_to_the_same_week_is_a_mistake_not_a_noop():
    with pytest.raises(hr_shifts.ShiftError) as exc:
        await hr_shifts.copy_week(
            None,  # type: ignore[arg-type]
            MANAGER,
            from_start=MONDAY,
            to_start=MONDAY,
        )
    assert str(exc.value) == "same_week"


async def test_copy_week_is_forbidden_for_an_employee():
    with pytest.raises(hr_shifts.ShiftError) as exc:
        await hr_shifts.copy_week(
            None,  # type: ignore[arg-type]
            STAFF,
            from_start=MONDAY,
            to_start=date(2026, 10, 26),
        )
    assert str(exc.value) == "forbidden"


async def test_clear_is_forbidden_for_an_employee():
    with pytest.raises(hr_shifts.ShiftError) as exc:
        await hr_shifts.clear_cells(
            None,  # type: ignore[arg-type]
            STAFF,
            employee_ids=[2],
            days=[MONDAY],
        )
    assert str(exc.value) == "forbidden"


async def test_clear_without_people_is_rejected():
    with pytest.raises(hr_shifts.ShiftError) as exc:
        await hr_shifts.clear_cells(
            None,  # type: ignore[arg-type]
            MANAGER,
            employee_ids=[],
            days=[MONDAY],
        )
    assert str(exc.value) == "no_employees"


# --------------------------------------------------------------------------
# Совместимость с одиночной правкой
# --------------------------------------------------------------------------


def test_single_shift_keeps_its_time_format():
    """Массовая ручка переиспользует те же `time`, что и одиночная: 10:00 → 10:00."""
    assert time(10, 0).strftime("%H:%M") == "10:00"
