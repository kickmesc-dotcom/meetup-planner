"""Правила журнала операционных проблем.

Тесты без базы: всё, что решает «можно ли видеть/править/закрыть карточку» и
«допустим ли переход статуса», вынесено в чистые функции
`services/hr_issues.py`. Именно эти правила защищают журнал: если они поедут,
сотрудник увидит чужие проблемы, а руководитель — не увидит своих.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from types import SimpleNamespace  # noqa: E402

from app.db.hr_models import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_AUP,
    ROLE_EMPLOYEE,
    ISSUE_CANCELLED,
    ISSUE_IN_PROGRESS,
    ISSUE_OPEN,
    ISSUE_RESOLVED,
    Employee,
)
from app.services import hr_issues  # noqa: E402


def _employee(
    employee_id: int = 1,
    role: str = ROLE_EMPLOYEE,
    department_id: int | None = 7,
) -> Employee:
    return Employee(
        id=employee_id,
        user_id=employee_id,
        role=role,
        department_id=department_id,
        is_active=True,
    )


def _issue(
    *,
    issue_id: int = 1,
    department_id: int | None = 7,
    created_by: int | None = 2,
    assignee: int | None = None,
    status: str = ISSUE_OPEN,
    severity: str = "normal",
) -> SimpleNamespace:
    """Лёгкий двойник `Issue`: правилам нужны только эти поля."""
    return SimpleNamespace(
        id=issue_id,
        department_id=department_id,
        created_by_employee_id=created_by,
        assignee_employee_id=assignee,
        status=status,
        severity=severity,
    )


# --- Область видимости -------------------------------------------------------


def test_scope_depends_on_role_and_department():
    # Журнал общий для смены: отдел виден всем его людям, не только руководителю.
    assert (
        hr_issues.scope_for(_employee(role=ROLE_EMPLOYEE))
        == hr_issues.SCOPE_DEPARTMENT
    )
    assert (
        hr_issues.scope_for(_employee(role=ROLE_AUP)) == hr_issues.SCOPE_DEPARTMENT
    )
    assert (
        hr_issues.scope_for(_employee(role=ROLE_EMPLOYEE, department_id=None))
        == hr_issues.SCOPE_SELF
    )
    assert (
        hr_issues.scope_for(_employee(role=ROLE_ADMIN, department_id=None))
        == hr_issues.SCOPE_ALL
    )


def test_employee_sees_own_department_and_own_cards_only():
    viewer = _employee(employee_id=5, department_id=7, role=ROLE_EMPLOYEE)

    assert hr_issues.can_view(viewer, _issue(department_id=7, created_by=99))
    assert hr_issues.can_view(
        viewer, _issue(department_id=99, created_by=5)
    ), "свою проблему видно даже из чужого отдела"
    assert hr_issues.can_view(
        viewer, _issue(department_id=99, created_by=99, assignee=5)
    ), "назначенный видит карточку"
    assert not hr_issues.can_view(
        viewer, _issue(department_id=99, created_by=99)
    ), "чужая проблема чужого отдела не видна"


def test_employee_without_department_sees_only_related_cards():
    viewer = _employee(employee_id=5, department_id=None, role=ROLE_EMPLOYEE)
    assert not hr_issues.can_view(viewer, _issue(department_id=None, created_by=99))
    assert hr_issues.can_view(viewer, _issue(department_id=None, created_by=5))


def test_manager_sees_department_but_not_foreign_one():
    manager = _employee(employee_id=6, department_id=7, role=ROLE_AUP)
    assert hr_issues.can_view(manager, _issue(department_id=7, created_by=99))
    assert not hr_issues.can_view(manager, _issue(department_id=8, created_by=99))
    assert hr_issues.can_view(
        manager, _issue(department_id=8, created_by=6)
    ), "собственную карточку руководитель видит всегда"


def test_admin_sees_everything():
    admin = _employee(employee_id=1, department_id=None, role=ROLE_ADMIN)
    assert hr_issues.can_view(admin, _issue(department_id=8, created_by=99))


# --- Права на правку и закрытие ---------------------------------------------


def test_author_edits_own_open_card_only():
    author = _employee(employee_id=5)
    assert hr_issues.can_edit(author, _issue(created_by=5, status=ISSUE_OPEN))
    assert not hr_issues.can_edit(
        author, _issue(created_by=5, status=ISSUE_IN_PROGRESS, assignee=9)
    ), "карточку в работе правит ответственный, а не автор"


def test_assignee_cannot_edit_but_closes():
    assignee = _employee(employee_id=9)
    issue = _issue(created_by=5, assignee=9, status=ISSUE_IN_PROGRESS)
    assert not hr_issues.can_edit(assignee, issue)
    assert hr_issues.can_close(assignee, issue)


def test_stranger_cannot_close():
    stranger = _employee(employee_id=11, department_id=7)
    issue = _issue(created_by=5, assignee=9, status=ISSUE_OPEN)
    assert hr_issues.can_view(stranger, issue), "свой отдел видно"
    assert not hr_issues.can_close(stranger, issue)


def test_manager_moderates_own_department_only():
    manager = _employee(employee_id=6, department_id=7, role=ROLE_AUP)
    assert hr_issues.can_moderate(manager, _issue(department_id=7))
    assert not hr_issues.can_moderate(manager, _issue(department_id=8))
    admin = _employee(employee_id=1, role=ROLE_ADMIN)
    assert hr_issues.can_moderate(admin, _issue(department_id=8))


def test_employee_assigns_only_self():
    employee = _employee(employee_id=5)
    manager = _employee(employee_id=6, role=ROLE_AUP)
    assert hr_issues.can_assign(employee, 5)
    assert not hr_issues.can_assign(employee, 9)
    assert not hr_issues.can_assign(employee, None), "снять ответственного — право руководителя"
    assert hr_issues.can_assign(manager, 9)
    assert hr_issues.can_assign(manager, None)


def test_reopen_is_manager_only():
    author = _employee(employee_id=5)
    manager = _employee(employee_id=6, role=ROLE_AUP)
    resolved = _issue(created_by=5, status=ISSUE_RESOLVED)
    assert not hr_issues.can_reopen(author, resolved)
    assert hr_issues.can_reopen(manager, resolved)


# --- Переходы статусов -------------------------------------------------------


def test_transitions_from_open():
    assert hr_issues.can_transition(ISSUE_OPEN, ISSUE_IN_PROGRESS)
    assert hr_issues.can_transition(ISSUE_OPEN, ISSUE_RESOLVED)
    assert hr_issues.can_transition(ISSUE_OPEN, ISSUE_CANCELLED)
    assert not hr_issues.can_transition(ISSUE_OPEN, "nonsense")


def test_resolved_can_only_be_reopened():
    assert hr_issues.can_transition(ISSUE_RESOLVED, ISSUE_OPEN)
    assert not hr_issues.can_transition(ISSUE_RESOLVED, ISSUE_IN_PROGRESS)
    assert hr_issues.can_transition(ISSUE_CANCELLED, ISSUE_OPEN)


def test_unknown_status_is_rejected():
    for bad in ("", "done", "OPEN", None):
        assert not hr_issues.can_transition(ISSUE_OPEN, bad)  # type: ignore[arg-type]


def test_is_open_helper():
    assert hr_issues.is_open(_issue(status=ISSUE_OPEN))
    assert hr_issues.is_open(_issue(status=ISSUE_IN_PROGRESS))
    assert not hr_issues.is_open(_issue(status=ISSUE_RESOLVED))
