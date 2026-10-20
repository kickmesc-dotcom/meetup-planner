"""SemiTaskBot: чистые правила HR-ядра + проверка, что ручки подключены.

Живого Postgres-стенда в проекте нет (см. `tests/test_game_core.py`), поэтому
тестируем то, что можно проверить без БД: правила переходов статусов, подсчёт
прогресса чек-листа, фильтр условных пунктов, валидацию ответов обратной связи и
факт регистрации роутов в приложении (`create_app`).

Env-переменные выставляем ДО импорта `app.main`: модуль создаёт приложение на
импорте, а `Settings` требует BOT_TOKEN/DATABASE_URL/…
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
    TASK_FAILED,
    TASK_IN_PROGRESS,
    TASK_NEW,
    TASK_OVERDUE,
    TEMPLATE_CLOSE,
    TEMPLATE_SHIFT,
    ChecklistItem,
    Employee,
    FeedbackQuestion,
    Task,
)
from app.services import (  # noqa: E402
    hr_access,
    hr_checklists,
    hr_departments,
    hr_feedback,
    hr_links,
    hr_tasks,  # noqa: E402
)

# --------------------------------------------------------------------------
# Роли и права
# --------------------------------------------------------------------------


def _employee(role: str) -> Employee:
    return Employee(id=1, user_id=1, role=role)


def test_role_ranks_are_ordered():
    assert hr_access.role_rank(ROLE_EMPLOYEE) < hr_access.role_rank(ROLE_AUP)
    assert hr_access.role_rank(ROLE_AUP) < hr_access.role_rank(ROLE_ADMIN)


def test_is_aup_and_is_admin():
    assert not hr_access.is_aup(_employee(ROLE_EMPLOYEE))
    assert hr_access.is_aup(_employee(ROLE_AUP))
    assert hr_access.is_aup(_employee(ROLE_ADMIN))
    assert not hr_access.is_admin(_employee(ROLE_AUP))
    assert hr_access.is_admin(_employee(ROLE_ADMIN))
    assert not hr_access.is_aup(None)


def test_default_role_uses_env_admin_list(monkeypatch):
    """Telegram-id из ADMIN_TG_IDS получает роль admin автоматически."""
    from app import config

    monkeypatch.setenv("ADMIN_TG_IDS", "555,777")
    config.get_settings.cache_clear()
    try:
        assert hr_access.default_role_for(555) == ROLE_ADMIN
        assert hr_access.default_role_for(777) == ROLE_ADMIN
        assert hr_access.default_role_for(1) == ROLE_EMPLOYEE
    finally:
        config.get_settings.cache_clear()


# --------------------------------------------------------------------------
# Чек-листы
# --------------------------------------------------------------------------


def _item(item_id: int, condition: str | None = None, photo: bool = False) -> ChecklistItem:
    return ChecklistItem(
        id=item_id, template_id=1, title=f"item-{item_id}",
        requires_photo=photo, is_mandatory=True, condition_position=condition,
    )


def test_applicable_items_filters_by_position():
    items = [_item(1), _item(2, condition="су-шеф"), _item(3, condition="Бармен")]
    for_position = [i.id for i in hr_checklists.applicable_items(items, "Су-шеф")]
    assert for_position == [1, 2]
    for_other = [i.id for i in hr_checklists.applicable_items(items, "официант")]
    assert for_other == [1]
    # Позиция не задана — условные пункты скрыты.
    assert [i.id for i in hr_checklists.applicable_items(items, None)] == [1]


def test_progress_counts_and_finishes():
    items = [_item(1), _item(2), _item(3)]
    progress = hr_checklists.progress(items, {1, 2})
    assert (progress.done, progress.total) == (2, 3)
    assert progress.text() == "Выполнено 2 из 3"
    assert not progress.finished
    assert hr_checklists.progress(items, {1, 2, 3}).finished
    # Пустой шаблон не считается «завершённым».
    assert not hr_checklists.progress([], set()).finished


def test_local_today_is_a_date():
    from datetime import date

    assert isinstance(hr_checklists.local_today("Europe/Moscow"), date)


def test_close_is_a_template_kind():
    """Закрытие смены — отдельный вид шаблона, а не «ещё одна смена»."""
    from app.db.hr_models import TEMPLATE_FIRST_DAY, TEMPLATE_KINDS

    assert TEMPLATE_CLOSE in TEMPLATE_KINDS
    assert TEMPLATE_SHIFT in TEMPLATE_KINDS
    assert TEMPLATE_FIRST_DAY in TEMPLATE_KINDS
    assert len(set(TEMPLATE_KINDS)) == len(TEMPLATE_KINDS)


# --------------------------------------------------------------------------
# Поручения
# --------------------------------------------------------------------------


def test_task_transitions_matrix():
    assert hr_tasks.can_transition(TASK_NEW, TASK_IN_PROGRESS)
    assert hr_tasks.can_transition(TASK_IN_PROGRESS, TASK_DONE)
    assert hr_tasks.can_transition(TASK_OVERDUE, TASK_DONE)
    # Из «выполнено» — никуда.
    assert not hr_tasks.can_transition(TASK_DONE, TASK_IN_PROGRESS)
    # Недопустимый статус не проходит.
    assert not hr_tasks.can_transition(TASK_NEW, "wat")
    assert not hr_tasks.can_transition(TASK_FAILED, TASK_NEW)


def _task(status: str, due_at: datetime | None) -> Task:
    return Task(id=1, title="t", scope="employee", status=status, due_at=due_at)


def test_is_overdue_only_for_open_tasks_with_past_due():
    past = datetime.now(UTC) - timedelta(hours=1)
    future = datetime.now(UTC) + timedelta(hours=1)
    assert hr_tasks.is_overdue(_task(TASK_NEW, past))
    assert not hr_tasks.is_overdue(_task(TASK_NEW, future))
    assert not hr_tasks.is_overdue(_task(TASK_NEW, None))
    # Закрытые не «просрочены», даже если срок прошёл.
    assert not hr_tasks.is_overdue(_task(TASK_DONE, past))
    # naive-дата не роняет сравнение.
    assert hr_tasks.is_overdue(_task(TASK_NEW, past.replace(tzinfo=None)))


# --------------------------------------------------------------------------
# Ссылки и обратная связь
# --------------------------------------------------------------------------


def test_slugify_transliterates_russian():
    assert hr_departments.slugify("Повар") == "povar"
    assert hr_departments.slugify("Бармен ") == "barmen"
    assert hr_departments.slugify("!!!") == "dept"


def test_looks_like_url():
    assert hr_links.looks_like_url("https://example.com/a")
    assert hr_links.looks_like_url("tg://resolve")
    assert not hr_links.looks_like_url("example.com")  # без схемы
    assert not hr_links.looks_like_url("https://example.com/has space")


def _question(kind: str, options: list[str] | None = None) -> FeedbackQuestion:
    return FeedbackQuestion(
        id=1, code="q", text="?", kind=kind, options=list(options or [])
    )


def test_validate_answer_per_kind():
    hr_feedback.validate_answer(
        _question("scale"), value_scale=4, value_choice=None, value_text=None
    )
    hr_feedback.validate_answer(
        _question("choice", ["Да", "Нет"]),
        value_scale=None,
        value_choice="Да",
        value_text=None,
    )
    hr_feedback.validate_answer(
        _question("text"), value_scale=None, value_choice=None, value_text="ок"
    )

    with pytest.raises(hr_feedback.FeedbackError):
        hr_feedback.validate_answer(
            _question("scale"), value_scale=7, value_choice=None, value_text=None
        )
    with pytest.raises(hr_feedback.FeedbackError):
        hr_feedback.validate_answer(
            _question("scale"), value_scale=None, value_choice=None, value_text=None
        )
    with pytest.raises(hr_feedback.FeedbackError):
        hr_feedback.validate_answer(
            _question("choice", ["Да"]),
            value_scale=None,
            value_choice="Нет",
            value_text=None,
        )
    with pytest.raises(hr_feedback.FeedbackError):
        hr_feedback.validate_answer(
            _question("text"), value_scale=None, value_choice=None, value_text="  "
        )


# --------------------------------------------------------------------------
# Подключение роутов
# --------------------------------------------------------------------------


def test_hr_routes_are_registered():
    from app.main import create_app

    app = create_app()
    paths = {
        (method, getattr(route, "path", ""))
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    }
    expected_employee = {
        ("GET", "/api/me/employee"),
        ("POST", "/api/me/onboarding"),
        ("GET", "/api/departments"),
        ("GET", "/api/checklist"),
        ("POST", "/api/checklist/complete"),
        ("GET", "/api/halls"),
        ("POST", "/api/checklist/hall"),
        ("GET", "/api/tasks"),
        ("GET", "/api/links"),
        ("GET", "/api/feedback/questions"),
        ("POST", "/api/feedback"),
    }
    expected_admin = {
        ("GET", "/api/admin/departments"),
        ("POST", "/api/admin/departments"),
        ("GET", "/api/admin/checklists"),
        ("POST", "/api/admin/checklists"),
        ("GET", "/api/admin/halls"),
        ("POST", "/api/admin/halls"),
        ("PATCH", "/api/admin/halls/{hall_id}"),
        ("GET", "/api/admin/links"),
        ("POST", "/api/admin/tasks"),
        ("PATCH", "/api/admin/tasks/{task_id}/status"),
        ("GET", "/api/admin/employees"),
        ("GET", "/api/admin/reports/overview"),
    }
    missing = (expected_employee | expected_admin) - paths
    assert not missing, f"не подключены ручки: {sorted(missing)}"
