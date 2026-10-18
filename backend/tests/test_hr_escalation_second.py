"""SemiTaskBot: вторая ступень эскалации просрочки.

Первая ступень уже проверена в `test_hr_flow` (когда уходит алерт и кому).
Здесь — то, что решает «админы не получат спам»: порог в часах, одноразовость
на цикл просрочки и границы настройки.

Почему чистыми функциями: сам тик ходит в БД, но решение «пора / не пора» —
это арифметика, и ошибка в ней либо будит админов каждые 15 минут, либо не
будит никогда. Запросы закрываются интеграционно на живом Postgres.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from datetime import UTC, datetime, timedelta  # noqa: E402

from app.db.hr_models import (  # noqa: E402
    TASK_DONE,
    TASK_IN_PROGRESS,
    TASK_OVERDUE,
    Task,
)
from app.services import hr_notify, hr_reminders, hr_settings  # noqa: E402

NOW = datetime(2026, 10, 18, 15, 0, tzinfo=UTC)


def _due(*, status: str = TASK_OVERDUE, since=NOW - timedelta(hours=5), hours=4, sent=False):
    return hr_reminders.second_escalation_due(
        status=status,
        overdue_since=since,
        now=NOW,
        hours=hours,
        already_sent=sent,
    )


# --------------------------------------------------------------------------
# Порог
# --------------------------------------------------------------------------


def test_fires_only_after_threshold():
    assert _due(since=NOW - timedelta(hours=3, minutes=59)) is False
    # Граница включительная: ровно N часов молчания — уже повод.
    assert _due(since=NOW - timedelta(hours=4)) is True
    assert _due(since=NOW - timedelta(hours=9)) is True


def test_task_must_still_be_overdue():
    # Любой другой статус — это реакция: доделали, вернули в работу, отменили.
    assert _due(status=TASK_DONE) is False
    assert _due(status=TASK_IN_PROGRESS) is False


def test_unknown_overdue_moment_is_not_a_reason_to_ping():
    assert _due(since=None) is False


def test_does_not_repeat_for_the_same_cycle():
    assert _due(sent=True) is False


def test_zero_hours_behaves_like_one_hour():
    """Кривой порог не должен превращать вторую ступень в дубль первой."""
    assert _due(since=NOW - timedelta(minutes=30), hours=0) is False
    assert _due(since=NOW - timedelta(hours=1), hours=0) is True


def test_naive_timestamps_are_treated_as_utc():
    naive_since = (NOW - timedelta(hours=5)).replace(tzinfo=None)
    assert _due(since=naive_since) is True


# --------------------------------------------------------------------------
# Одноразовость и новый цикл
# --------------------------------------------------------------------------


def test_marker_blocks_only_current_cycle():
    since = NOW - timedelta(hours=5)
    # Писали уже после того, как задача стала просроченной — молчим.
    assert hr_reminders.marker_covers_cycle(since + timedelta(minutes=1), since) is True
    # Задачу вернули в работу и она просрочилась заново: старый маркер не мешает.
    assert hr_reminders.marker_covers_cycle(since - timedelta(hours=2), since) is False
    assert hr_reminders.marker_covers_cycle(None, since) is False


def test_marker_without_overdue_event_still_blocks():
    assert hr_reminders.marker_covers_cycle(NOW, None) is True


# --------------------------------------------------------------------------
# Настройки
# --------------------------------------------------------------------------


def test_second_hours_are_clamped_to_sane_bounds():
    assert hr_settings.clamp_second_hours(0) == 1
    assert hr_settings.clamp_second_hours(200) == 72
    assert hr_settings.clamp_second_hours(6) == 6


def test_defaults_are_on_and_visible():
    """Вторая ступень включена по умолчанию и порог — 4 часа."""
    assert hr_settings.DEFAULT_ESCALATION_SECOND_ENABLED is True
    assert hr_settings.DEFAULT_ESCALATION_SECOND_HOURS == 4


# --------------------------------------------------------------------------
# Текст для админов
# --------------------------------------------------------------------------


def _candidate(
    *, task_id: int = 1, title: str = "Задача", reason: str = "waiting", hours_left: int = 2
) -> hr_reminders.EscalationCandidate:
    return hr_reminders.EscalationCandidate(
        task_id=task_id,
        title=title,
        due_at=NOW - timedelta(hours=5),
        overdue_since=NOW - timedelta(hours=5),
        hours_overdue=5,
        hours_left=hours_left,
        ready=reason == "ready",
        reason=reason,
    )


def test_dry_run_shows_ready_and_waiting():
    plan = hr_reminders.EscalationPlan(
        enabled=True,
        hours=4,
        admins=2,
        items=[
            _candidate(task_id=1, title="Пора", reason="ready"),
            _candidate(task_id=2, title="Подождём", hours_left=2),
        ],
    )
    text = hr_reminders.format_plan(plan)
    assert "к отправке сейчас: <b>1</b>" in text
    assert "«Пора»" in text
    assert "«Подождём» — через 2 ч" in text
    assert "Ничего не отправлено" in text


def test_dry_run_says_when_disabled_or_nobody_to_send():
    disabled = hr_reminders.EscalationPlan(enabled=False, hours=4, admins=2, items=[])
    assert "выключена" in hr_reminders.format_plan(disabled)
    lonely = hr_reminders.EscalationPlan(enabled=True, hours=4, admins=0, items=[])
    assert "некому" in hr_reminders.format_plan(lonely)


def test_text_names_the_task_and_the_wait():
    task = Task(title="Заменить фильтр", due_at=NOW - timedelta(hours=6))
    text = hr_notify.task_second_escalation_text(task, hours=4)
    assert "Заменить фильтр" in text
    assert "4 ч" in text
    # Это не «ещё раз то же»: админ должен понять, что реакция не пришла.
    assert "реакции руководителя нет" in text
