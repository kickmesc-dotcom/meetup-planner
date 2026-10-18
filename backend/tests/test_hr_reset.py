"""SemiTaskBot: сброс текущей работы.

Кнопка необратимая, поэтому проверяем ровно то, что может навредить:

* права — руководитель не должен убрать чужой отдел, а АУП без отдела —
  всю базу;
* токен — подпись, срок и привязка к показанным цифрам;
* текст подтверждения — цифры и предупреждение о необратимости.

Сами SQL-удаления проверяются интеграционно на живом Postgres: здесь нет
смысла подменять их фейками.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from app.db.hr_models import ROLE_ADMIN, ROLE_AUP, ROLE_EMPLOYEE, Employee  # noqa: E402
from app.services import hr_reset  # noqa: E402


def _employee(
    employee_id: int = 1,
    role: str = ROLE_AUP,
    department_id: int | None = 7,
) -> Employee:
    return Employee(
        id=employee_id, user_id=employee_id, role=role, department_id=department_id
    )


# --------------------------------------------------------------------------
# Права
# --------------------------------------------------------------------------


def test_admin_scope_is_everything():
    scope = hr_reset.resolve_scope(_employee(role=ROLE_ADMIN, department_id=None))
    assert scope.is_admin is True
    assert scope.department_id is None


def test_manager_scope_is_own_department_only():
    scope = hr_reset.resolve_scope(_employee(role=ROLE_AUP, department_id=7))
    assert scope.is_admin is False
    assert scope.department_id == 7


def test_manager_without_department_gets_only_own_tasks():
    """Иначе «управляющий вообще» одной кнопкой обнулил бы чужую работу."""
    scope = hr_reset.resolve_scope(_employee(role=ROLE_AUP, department_id=None))
    assert scope.is_admin is False
    assert scope.department_id is None
    assert "только свои" in scope.description


def test_employee_is_not_widened_to_department():
    """Даже если сервис вызван в обход `AupDep`, отдел не даёт прав на всё."""
    scope = hr_reset.resolve_scope(_employee(role=ROLE_EMPLOYEE, department_id=7))
    assert scope.is_admin is False
    assert scope.department_id == 7


# --------------------------------------------------------------------------
# Токен предпросмотра
# --------------------------------------------------------------------------


COUNTS = hr_reset.ResetCounts(tasks=3, issues=1, assignments=2, events=9)


def _scope() -> hr_reset.ResetScope:
    return hr_reset.resolve_scope(_employee(role=ROLE_AUP, department_id=7))


def test_fresh_token_is_valid():
    token = hr_reset.make_token(_scope(), COUNTS, now=1_000_000)
    assert hr_reset.verify_token(token, _scope(), COUNTS, now=1_000_010)


def test_expired_token_is_rejected():
    token = hr_reset.make_token(_scope(), COUNTS, now=1_000_000)
    expired = 1_000_000 + hr_reset.TOKEN_TTL_SECONDS + 1
    assert hr_reset.verify_token(token, _scope(), COUNTS, now=expired) is False


def test_token_is_bound_to_counts():
    """Показали 3 задачи — удалить 30 по этому токену нельзя."""
    token = hr_reset.make_token(_scope(), COUNTS, now=1_000_000)
    bigger = hr_reset.ResetCounts(tasks=30, issues=1)
    assert hr_reset.verify_token(token, _scope(), bigger, now=1_000_010) is False


def test_token_is_bound_to_person_and_scope():
    token = hr_reset.make_token(_scope(), COUNTS, now=1_000_000)
    other = hr_reset.resolve_scope(_employee(employee_id=2, role=ROLE_AUP, department_id=7))
    assert hr_reset.verify_token(token, other, COUNTS, now=1_000_010) is False


def test_garbage_token_is_rejected():
    assert hr_reset.verify_token("", _scope(), COUNTS) is False
    assert hr_reset.verify_token("no-dot", _scope(), COUNTS) is False
    assert hr_reset.verify_token("abc.def", _scope(), COUNTS) is False


# --------------------------------------------------------------------------
# Текст подтверждения
# --------------------------------------------------------------------------


def test_preview_text_shows_counts_and_irreversibility():
    preview = hr_reset.ResetPreview(
        scope=_scope(), counts=COUNTS, token="x"
    )
    text = hr_reset.preview_text(preview)
    assert "Поручений: <b>3</b>" in text
    assert "Проблем журнала: <b>1</b>" in text
    assert "необратимо" in text
    # Завершённое не трогаем — это важно проговорить до нажатия.
    assert "Завершённые поручения и история остаются" in text


def test_preview_text_says_when_nothing_to_do():
    empty = hr_reset.ResetPreview(
        scope=_scope(), counts=hr_reset.ResetCounts(), token="x"
    )
    assert "Сбрасывать нечего" in hr_reset.preview_text(empty)


def test_confirm_word_is_exact():
    assert hr_reset.CONFIRM_WORD == "СБРОС"
