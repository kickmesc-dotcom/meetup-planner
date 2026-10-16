"""SemiTaskBot: правила видимости ленты, напоминания/эскалация и HR-настройки.

Живого Postgres-стенда в проекте нет, поэтому проверяем ЧИСТЫЕ правила: кто что
видит в ленте, когда пора напомнить о сроке, кому уходит эскалация, как
зажимаются границы настроек. Запросы к БД (сборка ленты, тик планировщика)
покрываются интеграционно — здесь их не подменяем фейками, чтобы не создать
ложного ощущения проверенности.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from datetime import UTC, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402

from app.db.hr_models import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_AUP,
    ROLE_EMPLOYEE,
    TASK_DONE,
    TASK_IN_PROGRESS,
    TASK_NEW,
    TASK_OVERDUE,
    Department,
    Employee,
    Task,
)
from app.services import hr_feed, hr_pending, hr_reminders, hr_settings  # noqa: E402


def _employee(
    employee_id: int = 1,
    role: str = ROLE_EMPLOYEE,
    department_id: int | None = None,
) -> Employee:
    return Employee(id=employee_id, user_id=employee_id, role=role, department_id=department_id)


# --------------------------------------------------------------------------
# Лента: правила видимости
# --------------------------------------------------------------------------


def test_scope_for_employee_is_self_only():
    assert hr_feed.viewer_scope(_employee(role=ROLE_EMPLOYEE)) == hr_feed.SCOPE_SELF
    assert not hr_feed.can_filter(_employee(role=ROLE_EMPLOYEE))


def test_scope_for_department_manager_is_department():
    viewer = _employee(role=ROLE_AUP, department_id=7)
    assert hr_feed.viewer_scope(viewer) == hr_feed.SCOPE_DEPARTMENT
    assert hr_feed.can_filter(viewer)


def test_manager_without_department_sees_everything():
    """АУП без привязки — «управляющий вообще»: видит всё с фильтрами."""
    viewer = _employee(role=ROLE_AUP, department_id=None)
    assert hr_feed.viewer_scope(viewer) == hr_feed.SCOPE_ALL
    assert hr_feed.can_filter(viewer)


def test_admin_sees_everything():
    viewer = _employee(role=ROLE_ADMIN)
    assert hr_feed.viewer_scope(viewer) == hr_feed.SCOPE_ALL
    assert hr_feed.can_filter(viewer)


# Рукописные заглушки вместо строк БД: правила фильтра — чистая функция, и
# ей достаточно полей, которые участвуют в решении (id, department_id).
_DEPARTMENTS = [
    Department(id=1, name="Цех", slug="tseh"),
    Department(id=2, name="Склад", slug="sklad"),
]


def test_feed_filters_hide_departments_from_employee():
    """Сотруднику фильтровать нечего — списки фильтра пусты, а не «все минус один»."""
    assert hr_feed.scoped_departments(_employee(role=ROLE_EMPLOYEE), _DEPARTMENTS) == []


def test_feed_filters_limit_manager_to_own_department():
    """Руководитель видит в фильтре только своё подразделение."""
    viewer = _employee(role=ROLE_AUP, department_id=2)
    assert [d.id for d in hr_feed.scoped_departments(viewer, _DEPARTMENTS)] == [2]


def test_feed_filters_show_all_departments_to_manager():
    """Управляющий (АУП без привязки или админ) фильтрует по всем подразделениям."""
    admin_view = hr_feed.scoped_departments(_employee(role=ROLE_ADMIN), _DEPARTMENTS)
    assert [d.id for d in admin_view] == [1, 2]
    assert [
        d.id
        for d in hr_feed.scoped_departments(
            _employee(role=ROLE_AUP, department_id=None), _DEPARTMENTS
        )
    ] == [1, 2]


def test_employee_filter_allows_own_id_and_unrestricted():
    # Сотрудник может смотреть только себя.
    assert hr_feed.resolve_employee_filter(1, {1}) == 1
    # Управляющему доступен любой id.
    assert hr_feed.resolve_employee_filter(99, None) == 99
    # Без фильтра — None.
    assert hr_feed.resolve_employee_filter(None, {1}) is None


def test_employee_filter_rejects_foreign_id():
    with pytest.raises(PermissionError):
        hr_feed.resolve_employee_filter(42, {1, 2})


def test_all_kinds_are_stable():
    """Список видов фиксирован — иначе фильтр `kinds` молча теряет события."""
    assert set(hr_feed.ALL_KINDS) == {
        "checklist_done",
        "checklist_item",
        "task_created",
        "task_status",
        "task_photo",
        "task_issue",
    }


# --------------------------------------------------------------------------
# Напоминания и просрочка
# --------------------------------------------------------------------------


def _task(status: str, due_at: datetime | None) -> Task:
    return Task(id=1, title="t", scope="employee", status=status, due_at=due_at)


def test_reminder_due_only_inside_window():
    now = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    inside = now + timedelta(minutes=30)
    outside = now + timedelta(minutes=90)
    assert hr_reminders.reminder_due(_task(TASK_NEW, inside), now, before_minutes=60)
    assert not hr_reminders.reminder_due(_task(TASK_NEW, outside), now, before_minutes=60)


def test_reminder_skips_expired_and_closed():
    now = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    past = now - timedelta(minutes=1)
    # Уже просрочено — это ветка эскалации, «напоминать» поздно.
    assert not hr_reminders.reminder_due(_task(TASK_NEW, past), now, 60)
    # Закрытая задача не напоминает о себе.
    assert not hr_reminders.reminder_due(_task(TASK_DONE, now + timedelta(minutes=5)), now, 60)
    # Без срока напоминать не о чем.
    assert not hr_reminders.reminder_due(_task(TASK_IN_PROGRESS, None), now, 60)


def test_unique_employees_keeps_order():
    first = _employee(2)
    second = _employee(1)
    out = hr_reminders.unique_employees([first, second, _employee(2)])
    assert [e.id for e in out] == [2, 1]


def test_escalation_recipients_dedupes_creator():
    """Автор поручения обычно и есть руководитель — два уведомления не нужны."""
    manager = _employee(1, role=ROLE_AUP)
    other = _employee(2, role=ROLE_ADMIN)
    recipients = hr_reminders.escalation_recipients(
        managers=[manager, other], creator=manager
    )
    assert [e.id for e in recipients] == [1, 2]


def test_escalation_recipients_includes_creator_outside_managers():
    creator = _employee(5, role=ROLE_AUP)
    recipients = hr_reminders.escalation_recipients(managers=[], creator=creator)
    assert [e.id for e in recipients] == [5]


def test_open_statuses_exclude_terminal_ones():
    assert TASK_NEW in hr_reminders.hr_tasks.OPEN_STATUSES
    assert TASK_IN_PROGRESS in hr_reminders.hr_tasks.OPEN_STATUSES
    assert TASK_DONE not in hr_reminders.hr_tasks.OPEN_STATUSES
    assert TASK_OVERDUE not in hr_reminders.hr_tasks.OPEN_STATUSES


# --------------------------------------------------------------------------
# Настройки
# --------------------------------------------------------------------------


def test_settings_clamps_respect_bounds():
    assert hr_settings.clamp_before_minutes(0) == 5
    assert hr_settings.clamp_before_minutes(60) == 60
    assert hr_settings.clamp_before_minutes(99999) == 24 * 60
    assert hr_settings.clamp_tick_minutes(1) == 5
    assert hr_settings.clamp_tick_minutes(15) == 15
    assert hr_settings.clamp_tick_minutes(99999) == 24 * 60


def test_settings_defaults_are_sane():
    assert hr_settings.DEFAULT_REMINDERS_ENABLED is True
    assert hr_settings.DEFAULT_ESCALATION_ENABLED is True
    assert 5 <= hr_settings.DEFAULT_TICK_MINUTES <= 1440
    assert 5 <= hr_settings.DEFAULT_REMIND_BEFORE_MINUTES <= 1440


# --------------------------------------------------------------------------
# Ожидающее действие бота
# --------------------------------------------------------------------------


def test_pending_roundtrip():
    pending = hr_pending.Pending(
        kind=hr_pending.KIND_TASK_PHOTO, target_id=42, extra={"employee_id": 3}
    )
    restored = hr_pending.parse(pending.as_json())
    assert restored == pending


def test_pending_parse_rejects_garbage():
    assert hr_pending.parse(None) is None
    assert hr_pending.parse("") is None
    assert hr_pending.parse("not-json") is None
    assert hr_pending.parse("[1,2,3]") is None
    assert hr_pending.parse('{"kind": "x"}') is None  # нет target_id
    assert hr_pending.parse('{"target_id": 5}') is None  # нет kind


# --------------------------------------------------------------------------
# Подключение ручек
# --------------------------------------------------------------------------


def test_feed_and_settings_routes_registered():
    from app.main import create_app

    app = create_app()
    paths = {
        (method, getattr(route, "path", ""))
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    }
    for expected in (
        ("GET", "/api/feed"),
        ("GET", "/api/admin/settings/hr"),
        ("PUT", "/api/admin/settings/hr"),
    ):
        assert expected in paths, f"нет ручки {expected}"
