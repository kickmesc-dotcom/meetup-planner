"""Расписание обучения: чистые правила (без БД).

Здесь проверяем то, на чём легко ошибиться и что дороже всего в живом
приложении: первые N смен после найма учебные, ручное правило сильнее расчёта,
а без даты найма работает старый флаг «учимся вместе».
"""

from __future__ import annotations

import os
from datetime import date, timedelta

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("ADMIN_TG_IDS", "")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from app.db.hr_models import RATE_FULL, RATE_PARTIAL, Employee  # noqa: E402
from app.services import hr_training_plan as plan  # noqa: E402

TODAY = date(2026, 10, 19)


def _employee(**kwargs) -> Employee:  # noqa: ANN003
    values = {
        "id": 1,
        "user_id": 1,
        "role": "employee",
        "training_days": 3,
        "learning_mode": False,
        "rate_type": RATE_FULL,
    }
    values.update(kwargs)
    return Employee(**values)


def test_first_shifts_after_hire_are_training() -> None:
    employee = _employee(hire_date=TODAY - timedelta(days=1), training_days=3)
    assert plan.default_is_training(employee, TODAY)
    assert plan.default_is_training(employee, TODAY + timedelta(days=1))
    # Четвёртая смена после найма — уже обычная.
    assert not plan.default_is_training(employee, TODAY + timedelta(days=2))


def test_day_before_hire_is_not_training() -> None:
    employee = _employee(hire_date=TODAY, training_days=3)
    assert not plan.default_is_training(employee, TODAY - timedelta(days=1))


def test_zero_training_days_means_no_training_shifts() -> None:
    employee = _employee(hire_date=TODAY, training_days=0)
    assert not plan.default_is_training(employee, TODAY)


def test_without_hire_date_learning_mode_is_the_rule() -> None:
    assert plan.default_is_training(_employee(learning_mode=True), TODAY)
    assert not plan.default_is_training(_employee(learning_mode=False), TODAY)


def test_manual_day_beats_default_rule() -> None:
    employee = _employee(hire_date=TODAY, training_days=1)
    tomorrow = TODAY + timedelta(days=1)
    days = plan.build_days(
        employee, start=TODAY, days=3, overrides={tomorrow: True}
    )
    assert [(item.day, item.is_training, item.explicit) for item in days] == [
        (TODAY, True, False),
        (tomorrow, True, True),
        (TODAY + timedelta(days=2), False, False),
    ]


def test_timesheet_beats_calendar() -> None:
    """Заполненный табель сильнее календаря: день без смены — не учебный."""
    employee = _employee(hire_date=TODAY, training_days=3)
    marks = {
        TODAY: plan.ShiftMark(status="worked", is_training=True),
        TODAY + timedelta(days=1): plan.ShiftMark(status="sick", is_training=False),
    }
    days = plan.build_days(
        employee, start=TODAY, days=3, overrides={}, marks=marks
    )
    assert [(item.is_training, item.shift_status) for item in days] == [
        (True, "worked"),
        (False, "sick"),
        (False, None),
    ]


def test_manual_rule_beats_timesheet() -> None:
    employee = _employee(hire_date=TODAY, training_days=3)
    marks = {TODAY: plan.ShiftMark(status="worked", is_training=False)}
    days = plan.build_days(
        employee, start=TODAY, days=1, overrides={TODAY: True}, marks=marks
    )
    assert days[0].is_training is True and days[0].explicit is True
    assert days[0].shift_status == "worked"


def test_horizon_and_training_days_are_clamped() -> None:
    assert plan.clamp_horizon(0) == 1
    assert plan.clamp_horizon(9999) == plan.MAX_HORIZON_DAYS
    assert plan.clamp_training_days(-5) == 0
    assert plan.clamp_training_days(999) == plan.MAX_TRAINING_DAYS


def test_rate_labels_cover_both_rates() -> None:
    assert plan.RATE_LABELS[RATE_FULL]
    assert plan.RATE_LABELS[RATE_PARTIAL]
