"""Просрочка группового поручения: планировщик должен дотянуться до каждого.

Живёт отдельно от правил режимов, потому что проверяется не чистая функция, а
связка `sweep_overdue` → строки исполнителей → агрегат задачи. Сессия —
заглушка с очередью ответов (тот же приём, что в `test_game_social.py`): БД в
проекте нет, а регрессия здесь дорогая — иначе у людей висели бы свежие отметки
в поручении, которое уже считается просроченным.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from collections import deque  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app.db.hr_models import (  # noqa: E402
    MODE_EACH,
    TASK_DONE,
    TASK_IN_PROGRESS,
    TASK_NEW,
    TASK_OVERDUE,
)
from app.services import hr_tasks  # noqa: E402


class _Rows:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return list(self._items)


class _Session:
    """Минимальная сессия: очередь ответов на `scalars` + запись `add`."""

    def __init__(self, answers: list[list]) -> None:
        self._answers = deque(answers)
        self.added: list = []
        self.flushed = 0

    async def scalars(self, _stmt) -> _Rows:  # noqa: ANN001
        if not self._answers:
            return _Rows([])
        return _Rows(self._answers.popleft())

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1


def _task(task_id: int, status: str = TASK_IN_PROGRESS):
    return SimpleNamespace(
        id=task_id,
        status=status,
        mode=MODE_EACH,
        due_at=datetime.now(UTC) - timedelta(hours=2),
    )


def _assignment(employee_id: int, status: str):
    return SimpleNamespace(
        employee_id=employee_id, status=status, done_at=None, task_id=1
    )


async def test_overdue_spreads_to_assignments_and_task():
    task = _task(1, TASK_IN_PROGRESS)
    session = _Session(
        [
            [task],  # выборка открытых задач с прошедшим сроком
            [_assignment(1, TASK_DONE), _assignment(2, TASK_IN_PROGRESS)],
            # повторное чтение строк внутри sync_task_status
            [_assignment(1, TASK_DONE), _assignment(2, TASK_OVERDUE)],
        ]
    )

    changed = await hr_tasks.sweep_overdue(session)

    assert [t.id for t in changed] == [1]
    assert task.status == TASK_OVERDUE, "задача помечена просроченной"
    assignments = [a for a in session.added if hasattr(a, "employee_id")]
    assert assignments == [], "строки менялись на месте, дублей не создаём"


async def test_fully_done_group_task_is_not_overdue():
    """Все отметились — поручение закрыто, просрочка его не касается."""
    task = _task(2, TASK_IN_PROGRESS)
    session = _Session(
        [
            [task],
            [_assignment(1, TASK_DONE), _assignment(2, TASK_DONE)],
            [_assignment(1, TASK_DONE), _assignment(2, TASK_DONE)],
        ]
    )

    changed = await hr_tasks.sweep_overdue(session)

    assert changed == []
    assert task.status == TASK_DONE


async def test_untouched_assignments_go_overdue_too():
    """Никто не открывал поручение — строки всё равно должны стать просрочкой."""
    task = _task(3, TASK_NEW)
    session = _Session(
        [
            [task],
            [_assignment(1, TASK_NEW), _assignment(2, TASK_NEW)],
            [_assignment(1, TASK_OVERDUE), _assignment(2, TASK_OVERDUE)],
        ]
    )

    changed = await hr_tasks.sweep_overdue(session)

    assert [t.id for t in changed] == [3]
    assert task.status == TASK_OVERDUE
