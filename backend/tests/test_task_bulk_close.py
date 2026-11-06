"""Массовое закрытие поручений: числа в ответе вместо «готово».

Почему числа важны. Одиночное закрытие можно подтвердить словом «готово», а
пачку — нет: из четырнадцати поручений два могли не закрыться (уже закрыто,
нет перехода, чужое в сеансе проверки). Руководитель должен увидеть это сразу,
а не искать глазами по списку.

Тест зовёт обработчик напрямую с подменённым сервисом: маршрут не делает
собственных проверок статусов, он только считает успехи и отказы.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.api import routes_hr_admin as ra
from app.services import hr_tasks


class FakeSession:
    """Сессия без базы: проверяем подсчёт, а не SQL."""

    def __init__(self) -> None:
        self.committed = 0

    async def commit(self) -> None:
        self.committed += 1


def _task(task_id: int) -> Any:
    return SimpleNamespace(
        id=task_id, assignee_employee_id=None, created_by_employee_id=None
    )


async def test_bulk_close_counts_successes_and_drops_duplicates(monkeypatch) -> None:
    tasks = {1: _task(1), 2: _task(2)}
    calls: list[int] = []

    async def fake_get(_session: Any, task_id: int) -> Any:
        return tasks.get(task_id)

    async def fake_change(_session: Any, task: Any, status: str, **_kw: Any) -> Any:
        calls.append(task.id)
        assert status == "done"
        return task

    monkeypatch.setattr(hr_tasks, "get_task", fake_get)
    monkeypatch.setattr(hr_tasks, "change_status", fake_change)
    session = FakeSession()

    out = await ra.bulk_close_tasks(
        ra.TaskBulkCloseIn(task_ids=[1, 2, 2]),
        session,
        SimpleNamespace(id=9),
    )

    assert out.requested == 2, "повтор id не удваивает счёт"
    assert out.closed == 2
    assert out.failed == []
    assert calls == [1, 2]
    assert session.committed == 1


async def test_bulk_close_reports_failures_without_stopping(monkeypatch) -> None:
    async def fake_get(_session: Any, task_id: int) -> Any:
        return None if task_id == 3 else _task(task_id)

    async def fake_change(_session: Any, task: Any, _status: str, **_kw: Any) -> Any:
        if task.id == 2:
            raise hr_tasks.TaskError("bad_transition:done->done")
        return task

    monkeypatch.setattr(hr_tasks, "get_task", fake_get)
    monkeypatch.setattr(hr_tasks, "change_status", fake_change)
    session = FakeSession()

    out = await ra.bulk_close_tasks(
        ra.TaskBulkCloseIn(task_ids=[1, 2, 3]),
        session,
        SimpleNamespace(id=9),
    )

    assert out.requested == 3
    assert out.closed == 1, "отказ по одному поручению не отменяет остальные"
    assert [(item.task_id, item.reason) for item in out.failed] == [
        (2, "bad_transition:done->done"),
        (3, "task_not_found"),
    ]
    assert session.committed == 1


def test_bulk_close_rejects_empty_and_oversized_batches() -> None:
    """Пустая пачка и 101 поручение — ошибка валидации, а не тихий «ноль»."""
    import pydantic

    for bad in ([], list(range(1, 102))):
        try:
            ra.TaskBulkCloseIn(task_ids=bad)
        except pydantic.ValidationError:
            continue
        raise AssertionError(f"пачка {len(bad)} не отвергнута")
