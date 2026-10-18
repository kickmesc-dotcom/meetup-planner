"""Правила кабинета управляющего: часы, статусы смены, обучение, доступ.

Тесты намеренно без базы: всё, что можно проверить как арифметику или как
решение по данным, вынесено в чистые функции (`hr_worktime`, `hr_ops`,
`hr_training`). Так правила не зависят от Postgres и проверяются за миллисекунды.
"""

from datetime import datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.db.hr_models import ROLE_ADMIN, ROLE_AUP, ROLE_EMPLOYEE
from app.services import hr_access, hr_ops, hr_training, hr_worktime

MSK = ZoneInfo("Europe/Moscow")


# --- Рабочие часы ---------------------------------------------------------


def test_morning_before_opening_is_inside_lead_window():
    now = datetime(2026, 10, 18, 9, 15, tzinfo=MSK)
    assert hr_worktime.in_work_window(
        now, opens_at=time(10, 0), closes_at=time(23, 0), lead_minutes=60
    )


def test_night_alert_is_blocked():
    now = datetime(2026, 10, 18, 3, 41, tzinfo=MSK)
    assert not hr_worktime.in_work_window(
        now, opens_at=time(10, 0), closes_at=time(23, 0), lead_minutes=60
    )


def test_after_closing_allowed_for_tail():
    now = datetime(2026, 10, 18, 23, 45, tzinfo=MSK)
    assert hr_worktime.in_work_window(
        now,
        opens_at=time(10, 0),
        closes_at=time(23, 0),
        lead_minutes=60,
        tail_minutes=60,
    )
    late = datetime(2026, 10, 19, 0, 30, tzinfo=MSK)
    assert not hr_worktime.in_work_window(
        late,
        opens_at=time(10, 0),
        closes_at=time(23, 0),
        lead_minutes=60,
        tail_minutes=60,
    )


def test_overnight_shift_window_wraps_midnight():
    """Ресторан 10:00–02:00: в 01:30 смена ещё идёт, уведомления разрешены."""
    now = datetime(2026, 10, 19, 1, 30, tzinfo=MSK)
    assert hr_worktime.in_work_window(
        now, opens_at=time(10, 0), closes_at=time(2, 0), lead_minutes=0
    )


def test_parse_hhmm_falls_back_on_garbage():
    assert hr_worktime.parse_hhmm("09:30", time(10, 0)) == time(9, 30)
    assert hr_worktime.parse_hhmm("99:99", time(10, 0)) == time(10, 0)
    assert hr_worktime.parse_hhmm(None, time(10, 0)) == time(10, 0)
    assert hr_worktime.format_hhmm(time(9, 5)) == "09:05"


# --- Статус смены ---------------------------------------------------------


def test_employee_status_progression():
    late_after = time(21, 0)
    assert (
        hr_ops.employee_status(
            has_run=False, done=0, total=5, now_time=time(12, 0), late_after=late_after
        )
        == hr_ops.STATUS_IDLE
    )
    assert (
        hr_ops.employee_status(
            has_run=True, done=2, total=5, now_time=time(12, 0), late_after=late_after
        )
        == hr_ops.STATUS_IN_PROGRESS
    )
    assert (
        hr_ops.employee_status(
            has_run=True, done=2, total=5, now_time=time(22, 0), late_after=late_after
        )
        == hr_ops.STATUS_LATE
    )
    assert (
        hr_ops.employee_status(
            has_run=True, done=5, total=5, now_time=time(22, 0), late_after=late_after
        )
        == hr_ops.STATUS_DONE
    )


def test_late_after_is_two_hours_before_close():
    assert hr_ops.late_after_from_close(time(23, 0)) == time(21, 0)
    # Закрытие в 02:00 — «вечер» наступает в полночь.
    assert hr_ops.late_after_from_close(time(2, 0)) == time(0, 0)


def test_viewer_scope_depends_on_role():
    assert hr_ops.viewer_scope(SimpleNamespace(role=ROLE_ADMIN)) == "all"
    assert hr_ops.viewer_scope(SimpleNamespace(role=ROLE_AUP)) == "department"


# --- Обучение -------------------------------------------------------------


def test_training_progress_counts_mandatory_lessons():
    empty = hr_training.progress_from_codes(set())
    assert (empty.done, empty.total, empty.percent, empty.complete) == (
        (),
        len(hr_training.LESSONS),
        0,
        False,
    )

    first = hr_training.LESSONS[0].code
    partly = hr_training.progress_from_codes({first, "unknown_code"})
    assert partly.done == (first,)
    assert 0 < partly.percent < 100

    all_codes = {lesson.code for lesson in hr_training.LESSONS}
    full = hr_training.progress_from_codes(all_codes)
    assert full.complete and full.percent == 100
    assert full.status() == "done"


def test_training_catalog_has_app_usage_lessons():
    codes = {lesson.code for lesson in hr_training.LESSONS}
    # Ровно те действия, которых не хватало в онбординге.
    assert {"shift_start", "photo_report", "report_problem", "quiet_hours"} <= codes
    for lesson in hr_training.LESSONS:
        assert lesson.steps and lesson.summary


# --- Доступ ---------------------------------------------------------------


def _settings_stub(monkeypatch, staff: set[int]):
    monkeypatch.setattr(
        hr_access,
        "get_settings",
        lambda: SimpleNamespace(staff_tg_id_set=staff),
    )


def test_default_role_uses_staff_list(monkeypatch):
    _settings_stub(monkeypatch, {10, 20})
    assert hr_access.default_role_for(20) == ROLE_ADMIN
    assert hr_access.default_role_for(30) == ROLE_EMPLOYEE


def test_staff_keeps_admin_cabinet_after_self_demotion(monkeypatch):
    """Снял себе admin — кабинет остался, иначе роль не вернуть."""
    _settings_stub(monkeypatch, {10})
    employee = SimpleNamespace(role=ROLE_EMPLOYEE)
    assert hr_access.is_admin(employee) is False
    assert hr_access.is_staff(employee, SimpleNamespace(telegram_id=10)) is True
    assert hr_access.is_staff(employee, SimpleNamespace(telegram_id=11)) is False


def test_set_role_locks_manual_choice():
    employee = SimpleNamespace(role=ROLE_ADMIN, role_locked=False)
    hr_access.set_role(employee, ROLE_EMPLOYEE)
    assert employee.role == ROLE_EMPLOYEE
    assert employee.role_locked is True

    with pytest.raises(hr_access.HrAccessError):
        hr_access.set_role(employee, "superuser")
