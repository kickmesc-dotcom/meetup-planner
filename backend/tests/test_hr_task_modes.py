"""Режимы групповых поручений: как отметки исполнителей складываются в статус.

Без базы: разница между «один за всех», «каждый сам» и «части работы» — это
одна чистая функция `aggregate_status`. Если она поедет, руководитель увидит
закрытое поручение там, где половина смены ничего не сделала.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from app.db.hr_models import (  # noqa: E402
    MODE_EACH,
    MODE_ONE_OF,
    MODE_PARTS,
    TASK_ACCEPTED,
    TASK_DONE,
    TASK_FAILED,
    TASK_IN_PROGRESS,
    TASK_NEW,
    TASK_OVERDUE,
)
from app.services import hr_tasks  # noqa: E402


def test_empty_assignments_is_new():
    assert hr_tasks.aggregate_status(MODE_ONE_OF, []) == TASK_NEW


def test_one_of_is_closed_by_first_done():
    assert (
        hr_tasks.aggregate_status(MODE_ONE_OF, [TASK_DONE, TASK_NEW]) == TASK_DONE
    )
    assert (
        hr_tasks.aggregate_status(MODE_ONE_OF, [TASK_NEW, TASK_IN_PROGRESS])
        == TASK_IN_PROGRESS
    )


def test_one_of_fails_only_when_everybody_failed():
    assert (
        hr_tasks.aggregate_status(MODE_ONE_OF, [TASK_FAILED, TASK_FAILED])
        == TASK_FAILED
    )
    assert (
        hr_tasks.aggregate_status(MODE_ONE_OF, [TASK_FAILED, TASK_NEW]) == TASK_NEW
    ), "пока второй не отметился, поручение ещё открыто"


def test_each_needs_everybody():
    assert (
        hr_tasks.aggregate_status(MODE_EACH, [TASK_DONE, TASK_IN_PROGRESS])
        == TASK_IN_PROGRESS
    )
    assert (
        hr_tasks.aggregate_status(MODE_EACH, [TASK_DONE, TASK_DONE]) == TASK_DONE
    )
    assert (
        hr_tasks.aggregate_status(MODE_EACH, [TASK_DONE, TASK_FAILED])
        == TASK_FAILED
    ), "кто-то не сделал свою часть — поручение не закрыто"


def test_parts_respects_each_part():
    assert (
        hr_tasks.aggregate_status(MODE_PARTS, [TASK_NEW, TASK_NEW]) == TASK_NEW
    )
    assert (
        hr_tasks.aggregate_status(MODE_PARTS, [TASK_DONE, TASK_NEW])
        == TASK_IN_PROGRESS
    ), "свою часть уже сделали — поручение в работе"
    assert (
        hr_tasks.aggregate_status(MODE_PARTS, [TASK_DONE, TASK_ACCEPTED])
        == TASK_IN_PROGRESS
    )
    assert (
        hr_tasks.aggregate_status(MODE_PARTS, [TASK_DONE, TASK_DONE]) == TASK_DONE
    )


def test_overdue_is_visible_but_does_not_close():
    assert (
        hr_tasks.aggregate_status(MODE_EACH, [TASK_OVERDUE, TASK_OVERDUE])
        == TASK_OVERDUE
    )
    assert (
        hr_tasks.aggregate_status(MODE_EACH, [TASK_OVERDUE, TASK_DONE])
        == TASK_IN_PROGRESS
    ), "задача просрочена не полностью — она в работе, а не закрыта"
