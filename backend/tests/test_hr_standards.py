"""SemiTaskBot: база стандартов и проверка работы руководителем.

Тестируем чистые правила — подсчёт результата теста и агрегат статусов
поручения. Оба правила решают «сдал / не сдал» и «закрыто / на проверке»,
поэтому ошибка здесь дороже всего: она либо допускает новичка к смене, либо
закрывает работу, которую никто не смотрел.

Env выставляем ДО импорта `app.main` — `Settings` требует BOT_TOKEN и т.п.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402

from app.db.hr_models import (  # noqa: E402
    MODE_EACH,
    TASK_ACCEPTED,
    TASK_DONE,
    TASK_FAILED,
    TASK_IN_PROGRESS,
    TASK_NEW,
    TASK_ON_REVIEW,
    TASK_REWORK,
)
from app.services import hr_standards, hr_tasks  # noqa: E402

# --------------------------------------------------------------------------
# Сдача теста
# --------------------------------------------------------------------------


def test_grade_counts_percent_and_passes_threshold():
    result = hr_standards.grade([1, 2, 0, 3], [1, 2, 0, 3], 80)
    assert (result.total, result.correct, result.percent) == (4, 4, 100)
    assert result.passed


def test_grade_allows_partial_but_not_below_threshold():
    # 3 из 4 = 75% < 80 — не сдал.
    failed = hr_standards.grade([0, 0, 0, 0], [0, 0, 0, 1], 80)
    assert (failed.correct, failed.percent, failed.passed) == (3, 75, False)
    # Тот же результат при пороге 75 — сдал (граница включительная).
    assert hr_standards.grade([0, 0, 0, 0], [0, 0, 0, 1], 75).passed


def test_grade_clamps_absurd_threshold():
    # Порог ниже 50% сервер не принимает: тест, который сдают «наугад», не тест.
    assert hr_standards.grade([0], [1], 0).passed is False
    assert hr_standards.grade([0], [0], 0).passed is True
    # Порог выше 100% не делает тест невыполнимым.
    assert hr_standards.grade([0], [0], 500).passed is True


def test_grade_rejects_empty_test():
    with pytest.raises(hr_standards.StandardError):
        hr_standards.grade([], [], 80)


def test_grade_ignores_extra_answers():
    """Лишние ответы не портят результат: считаем только по вопросам."""
    assert hr_standards.grade([0, 1], [0, 1, 1, 1], 80).correct == 2


def test_grade_treats_missing_answer_as_wrong():
    assert hr_standards.grade([0, 1], [0], 50).correct == 1


# --------------------------------------------------------------------------
# Проверка руководителем: агрегат и переходы
# --------------------------------------------------------------------------


def test_review_status_appears_in_aggregate_for_each_mode():
    # Один сдал, другой ещё не начинал: руководителю надо принять работу,
    # поэтому агрегат — «на проверке», а не «в работе».
    assert (
        hr_tasks.aggregate_status(MODE_EACH, [TASK_ON_REVIEW, TASK_NEW])
        == TASK_ON_REVIEW
    )
    assert (
        hr_tasks.aggregate_status(MODE_EACH, [TASK_ON_REVIEW, TASK_DONE])
        == TASK_ON_REVIEW
    )


def test_in_progress_wins_over_review_in_same_task():
    # Кто-то ещё работает — показываем «в работе»: приёмка всей задачи
    # преждевременна.
    assert (
        hr_tasks.aggregate_status(
            MODE_EACH, [TASK_ON_REVIEW, TASK_IN_PROGRESS]
        )
        == TASK_IN_PROGRESS
    )


def test_rework_keeps_task_open_as_rework():
    assert (
        hr_tasks.aggregate_status(MODE_EACH, [TASK_REWORK, TASK_REWORK])
        == TASK_REWORK
    )
    # Вернули одному, второй сдал — работа всё равно идёт.
    assert (
        hr_tasks.aggregate_status(MODE_EACH, [TASK_REWORK, TASK_DONE])
        == TASK_IN_PROGRESS
    )


def test_all_accepted_is_accepted():
    assert (
        hr_tasks.aggregate_status(MODE_EACH, [TASK_ACCEPTED, TASK_ACCEPTED])
        == TASK_ACCEPTED
    )


def test_review_transitions():
    assert hr_tasks.can_transition(TASK_ON_REVIEW, TASK_DONE)
    assert hr_tasks.can_transition(TASK_ON_REVIEW, TASK_REWORK)
    assert hr_tasks.can_transition(TASK_REWORK, TASK_ON_REVIEW)
    # Принятую работу заново на проверку не отправить.
    assert not hr_tasks.can_transition(TASK_DONE, TASK_ON_REVIEW)
    # Сотрудник не может «перескочить» приёмку.
    assert not hr_tasks.can_transition(TASK_ON_REVIEW, TASK_NEW)


def test_failed_can_be_returned_to_review_or_done():
    assert hr_tasks.can_transition(TASK_FAILED, TASK_IN_PROGRESS)
    assert hr_tasks.can_transition(TASK_FAILED, TASK_DONE)


# --------------------------------------------------------------------------
# Ручки подключены
# --------------------------------------------------------------------------


def test_standards_and_review_routes_are_registered():
    from app.main import create_app

    app = create_app()
    paths = {
        (method, getattr(route, "path", ""))
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    }
    expected = {
        ("GET", "/api/standards"),
        ("GET", "/api/standards/{standard_id}"),
        ("POST", "/api/standards/{standard_id}/check"),
        ("POST", "/api/admin/standards"),
        ("GET", "/api/tasks/review-queue"),
        ("POST", "/api/tasks/{task_id}/review"),
    }
    missing = expected - paths
    assert not missing, f"не подключены ручки: {sorted(missing)}"
