"""Список поручений АУП: число запросов не растёт с числом задач.

Зачем тест. N+1 не виден по ответу ручки: данные те же, просто за каждым
поручением отдельный поход в базу. Поэтому считаем сами SQL-запросы: один и
тот же вызов на 1 и на 5 поручениях обязан стоить одинаково. Тест поймает и
возврат к циклу `assignees`/`assignments_of`, и случайное добавление запроса
внутрь сборки ответа.

База — sqlite в памяти, как в `test_quick_task.py`: проверяется форма запросов,
а настоящую схему и FK покрывает PG-прогон.
"""

from __future__ import annotations

import itertools
import os
from typing import Any

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.api import routes_hr_admin  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ROLE_AUP,
    TASK_SCOPE_EMPLOYEE,
    Employee,
    Task,
)
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.services import hr_tasks  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "employees",
    "departments",
    "tasks",
    "task_assignments",
    "task_events",
    "task_photos",
    "media_blobs",
)


class Queries:
    """Счётчик выполненных SQL: слушаем движок, а не сессию."""

    def __init__(self) -> None:
        self.count = 0
        self.statements: list[str] = []


@pytest.fixture()
async def db() -> Any:
    engine = create_async_engine("sqlite+aiosqlite://")
    tables = [Base.metadata.tables[name] for name in TABLES]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    queries = Queries()

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        queries.count += 1
        queries.statements.append(statement)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        # sqlite не умеет BIGSERIAL: id выдаём перед вставкой, как в
        # `test_quick_task.py`. Тип PK проверяет PG-прогон.
        counter = itertools.count(1)
        scoped = {"tasks", "task_assignments", "task_events", "task_photos"}

        @event.listens_for(session.sync_session, "before_flush")
        def _fill_ids(sess, _ctx, _instances):  # noqa: ANN001
            for obj in sess.new:
                if (
                    obj.__class__.__tablename__ in scoped
                    and getattr(obj, "id", None) is None
                ):
                    obj.id = next(counter)

        yield session, queries
    await engine.dispose()


@pytest.fixture(autouse=True)
def clean_org_context() -> Any:
    token = set_org(DEFAULT_ORG_ID)
    yield
    reset_org(token)


async def _people(session) -> tuple[Employee, Employee]:  # noqa: ANN001
    session.add(Organization(id=DEFAULT_ORG_ID, slug="default", name="Кофейня"))
    session.add(User(id=1, telegram_id=111, display_name="Руководитель"))
    session.add(User(id=2, telegram_id=222, display_name="Аня Петрова"))
    manager = Employee(
        id=1,
        org_id=DEFAULT_ORG_ID,
        user_id=1,
        role=ROLE_AUP,
        department_id=1,
        is_active=True,
    )
    worker = Employee(
        id=2, org_id=DEFAULT_ORG_ID, user_id=2, department_id=1, is_active=True
    )
    session.add_all([manager, worker])
    await session.commit()
    return manager, worker


async def _add_tasks(session, manager: Employee, worker: Employee, count: int) -> None:  # noqa: ANN001
    for index in range(count):
        await hr_tasks.create_task(
            session,
            creator=manager,
            title=f"Задача {index}",
            scope=TASK_SCOPE_EMPLOYEE,
            assignee_employee_id=worker.id,
        )
    await session.commit()


async def test_query_count_does_not_grow_with_the_list(db) -> None:  # noqa: ANN001
    session, queries = db
    manager, worker = await _people(session)

    await _add_tasks(session, manager, worker, 1)
    one_task = await hr_tasks.list_all(session)
    queries.count = 0
    single = await routes_hr_admin._task_admin_outs(session, one_task)
    for_one = queries.count
    assert len(single) == 1

    await _add_tasks(session, manager, worker, 4)
    five_tasks = await hr_tasks.list_all(session)
    assert len(five_tasks) == 5
    queries.count = 0
    many = await routes_hr_admin._task_admin_outs(session, five_tasks)
    for_five = queries.count
    assert len(many) == 5

    # Главное утверждение: список вырос впятеро, а запросов столько же.
    assert for_five == for_one, (
        f"на 5 поручений {for_five} запросов, на 1 — {for_one}: "
        f"вернулся N+1: {queries.statements}"
    )


async def test_list_still_carries_assignees_names_and_progress(db) -> None:  # noqa: ANN001
    session, _queries = db
    manager, worker = await _people(session)
    await _add_tasks(session, manager, worker, 2)

    tasks = await hr_tasks.list_all(session)
    out = await routes_hr_admin._task_admin_outs(session, tasks)

    assert {item.title for item in out} == {"Задача 0", "Задача 1"}
    for item in out:
        assert item.assignee_ids == [worker.id]
        assert item.assignee_employee_id == worker.id
        assert item.progress_total == 1
        assert item.progress_done == 0
        # Имя берётся из `users`, а не остаётся заглушкой.
        assert [row.display_name for row in item.assignments] == ["Аня Петрова"]
        assert item.photos == []


async def test_empty_list_costs_nothing(db) -> None:  # noqa: ANN001
    session, queries = db
    queries.count = 0
    assert await routes_hr_admin._task_admin_outs(session, []) == []
    assert queries.count == 0


async def test_single_task_helper_matches_the_batch(db) -> None:  # noqa: ANN001
    session, _queries = db
    manager, worker = await _people(session)
    await _add_tasks(session, manager, worker, 1)
    task: Task = (await hr_tasks.list_all(session))[0]

    single = await routes_hr_admin._task_admin_out(session, task)
    batch = (await routes_hr_admin._task_admin_outs(session, [task]))[0]

    assert single.model_dump() == batch.model_dump()
