"""Правила передачи смены.

Без базы: проверяем, кто видит сдачу, кто может её принять и вернуть. Ошибка
здесь означает либо чужие хвосты в журнале, либо «принято» без принимающего.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from types import SimpleNamespace  # noqa: E402

from app.db.hr_models import (  # noqa: E402
    HANDOVER_ACCEPTED,
    HANDOVER_REJECTED,
    HANDOVER_SENT,
    ROLE_ADMIN,
    ROLE_AUP,
    ROLE_EMPLOYEE,
    Employee,
)
from app.services import hr_handovers  # noqa: E402


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


def _handover(
    *,
    handover_id: int = 1,
    department_id: int | None = 7,
    sender: int | None = 2,
    recipient: int | None = 3,
    accepted_by: int | None = None,
    status: str = HANDOVER_SENT,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=handover_id,
        department_id=department_id,
        from_employee_id=sender,
        to_employee_id=recipient,
        accepted_by_employee_id=accepted_by,
        status=status,
    )


# --- Видимость ---------------------------------------------------------------


def test_participants_see_handover():
    card = _handover(sender=2, recipient=3)
    assert hr_handovers.can_view(_employee(employee_id=2), card)
    assert hr_handovers.can_view(_employee(employee_id=3), card)
    assert hr_handovers.can_view(_employee(employee_id=4), _handover(accepted_by=4))


def test_manager_sees_department_only():
    manager = _employee(employee_id=9, role=ROLE_AUP, department_id=7)
    assert hr_handovers.can_view(manager, _handover(department_id=7))
    assert not hr_handovers.can_view(manager, _handover(department_id=8))


def test_employee_does_not_see_foreign_handover():
    stranger = _employee(employee_id=5, department_id=7)
    assert not hr_handovers.can_view(stranger, _handover(sender=2, recipient=3))


def test_admin_sees_everything():
    admin = _employee(employee_id=1, role=ROLE_ADMIN, department_id=None)
    assert hr_handovers.can_view(admin, _handover(department_id=8))


def test_employee_without_department_does_not_see_by_department():
    lonely = _employee(employee_id=5, department_id=None)
    assert not hr_handovers.can_view(lonely, _handover(department_id=7))
    assert hr_handovers.can_view(lonely, _handover(department_id=None, sender=5))


# --- Приём и возврат ---------------------------------------------------------


def test_only_recipient_accepts_and_only_when_sent():
    recipient = _employee(employee_id=3)
    sender = _employee(employee_id=2)
    card = _handover(sender=2, recipient=3)

    assert hr_handovers.can_accept(recipient, card)
    assert not hr_handovers.can_accept(sender, card)
    assert not hr_handovers.can_accept(
        recipient, _handover(sender=2, recipient=3, status=HANDOVER_ACCEPTED)
    )
    assert not hr_handovers.can_accept(
        recipient, _handover(sender=2, recipient=3, status=HANDOVER_REJECTED)
    )


def test_manager_cannot_accept_for_the_recipient():
    manager = _employee(employee_id=9, role=ROLE_AUP, department_id=7)
    card = _handover(sender=2, recipient=3)
    assert hr_handovers.can_view(manager, card)
    assert not hr_handovers.can_accept(manager, card)


def test_reject_follows_accept_rules():
    recipient = _employee(employee_id=3)
    card = _handover(sender=2, recipient=3)
    assert hr_handovers.can_reject(recipient, card)
    assert not hr_handovers.can_reject(
        _employee(employee_id=2), card
    ), "сдающий не может вернуть свою же сдачу"
