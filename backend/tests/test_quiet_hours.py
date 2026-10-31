"""Тихие часы: экономия бюджета Neon не должна стоить пропущенных напоминаний.

Проверяем два разных обещания:

1. окно считается правильно, включая переход через полночь и «выключено»;
2. внутри окна задача выполняется не чаще раза в час, но **первый** запуск
   выполняется всегда — иначе поднятый ночью контейнер молчал бы до утра.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.services import quiet_hours


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setenv("QUIET_HOURS_START", "23")
    monkeypatch.setenv("QUIET_HOURS_END", "7")
    monkeypatch.setenv("QUIET_TICK_MINUTES", "60")
    quiet_hours.reset_state()
    yield
    quiet_hours.reset_state()


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 31, hour, minute)


def test_window_boundaries():
    assert quiet_hours.in_quiet_hours(at(22, 59)) is False
    assert quiet_hours.in_quiet_hours(at(23, 0)) is True
    assert quiet_hours.in_quiet_hours(at(3, 30)) is True
    assert quiet_hours.in_quiet_hours(at(6, 59)) is True
    # 07:00 — уже рабочий день: утренние сроки должны обрабатываться сразу.
    assert quiet_hours.in_quiet_hours(at(7, 0)) is False


def test_window_through_midnight_custom():
    assert quiet_hours.in_quiet_hours(at(21, 59), start=22, end=6) is False
    assert quiet_hours.in_quiet_hours(at(22, 0), start=22, end=6) is True
    assert quiet_hours.in_quiet_hours(at(2, 0), start=22, end=6) is True
    assert quiet_hours.in_quiet_hours(at(6, 0), start=22, end=6) is False


def test_window_can_be_disabled():
    # start == end — не «весь день», а «тихих часов нет».
    assert quiet_hours.in_quiet_hours(at(3, 0), start=0, end=0) is False


def test_daytime_always_runs():
    for hour in (8, 12, 18, 22):
        assert quiet_hours.should_run("reminders", now=at(hour)) is True


def test_quiet_window_runs_once_then_throttles():
    assert quiet_hours.should_run("reminders", now=at(23, 5)) is True  # первый
    assert quiet_hours.should_run("reminders", now=at(23, 10)) is False
    assert quiet_hours.should_run("reminders", now=at(23, 35)) is False
    # Час спустя — уже другие сутки: без прибавления дня это было бы «время
    # раньше последнего запуска», то есть проверялся бы не тот случай.
    next_day = at(0, 20) + timedelta(days=1)
    assert quiet_hours.should_run("reminders", now=next_day) is True
    assert quiet_hours.should_run("reminders", now=next_day + timedelta(minutes=20)) is False


def test_jobs_are_throttled_independently():
    assert quiet_hours.should_run("reminders", now=at(2, 0)) is True
    # Другая задача не должна «съесть» окно первой.
    assert quiet_hours.should_run("hr_tasks", now=at(2, 1)) is True
    assert quiet_hours.should_run("reminders", now=at(2, 2)) is False


def test_tick_interval_from_env(monkeypatch):
    monkeypatch.setenv("QUIET_TICK_MINUTES", "15")
    assert quiet_hours.should_run("hr_tasks", now=at(23, 0)) is True
    assert quiet_hours.should_run("hr_tasks", now=at(23, 10)) is False
    assert quiet_hours.should_run("hr_tasks", now=at(23, 16)) is True


def test_morning_resume_after_quiet_night():
    next_day = timedelta(days=1)
    assert quiet_hours.should_run("hr_tasks", now=at(23, 0)) is True
    # Ночью прореживание действует по часу, а не «выключает задачу».
    assert quiet_hours.should_run("hr_tasks", now=at(5, 30) + next_day) is True
    assert quiet_hours.should_run("hr_tasks", now=at(6, 0) + next_day) is False
    # 07:00 — выход из окна: задача идёт сразу, не дожидаясь часа.
    morning = at(7, 0) + next_day
    assert quiet_hours.should_run("hr_tasks", now=morning) is True
    assert quiet_hours.should_run("hr_tasks", now=morning + timedelta(minutes=1)) is True
