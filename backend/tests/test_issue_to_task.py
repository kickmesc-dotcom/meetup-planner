"""Проблема → поручение: связь, исполнитель и повторная попытка."""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from datetime import date  # noqa: E402

import itertools  # noqa: E402

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import event, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.api.routes_issues import IssueTaskIn, task_from_issue  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_EMPLOYEE,
    Department,
    Employee,
    Issue,
    IssueEvent,
    Task,
)
from app.db.models import User  # noqa: E402
from app.services import hr_notify  # noqa: E402
from app.db.org_models import DEFAULT_ORG_ID, Organization, reset_org, set_org  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "departments",
    "employees",
    "tasks",
    "task_assignments",
    "task_events",
    "hr_issues",
    "hr_issue_events",
)


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    tables = [Base.metadata.tables[name] for name in TABLES]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        # sqlite не умеет BIGSERIAL: id выдаём перед вставкой (как в
        # test_admin_tasks_batch). Тип PK проверяет PG-прогон.
        counter = itertools.count(1)
        scoped = {"tasks", "task_assignments", "task_events"}

        @event.listens_for(db.sync_session, "before_flush")
        def _fill_ids(sess, _ctx, _instances):  # noqa: ANN001
            for obj in sess.new:
                if (
                    obj.__class__.__tablename__ in scoped
                    and getattr(obj, "id", None) is None
                ):
                    obj.id = next(counter)

        yield db
    await engine.dispose()


@pytest.fixture(autouse=True)
def clean_org_context():
    token = set_org(DEFAULT_ORG_ID)
    yield
    reset_org(token)


async def _seed(session) -> tuple[Employee, Employee, Issue]:
    session.add(Organization(id=DEFAULT_ORG_ID, slug="default", name="Моя"))
    session.add_all(
        [
            User(id=1, telegram_id=900001, display_name="Анна"),
            User(id=2, telegram_id=900002, display_name="Борис"),
        ]
    )
    await session.flush()
    session.add(Department(id=7, org_id=DEFAULT_ORG_ID, name="Зал", slug="hall"))
    await session.flush()
    boss = Employee(
        id=1, org_id=DEFAULT_ORG_ID, user_id=1, role=ROLE_ADMIN, department_id=7
    )
    worker = Employee(
        id=2, org_id=DEFAULT_ORG_ID, user_id=2, role=ROLE_EMPLOYEE, department_id=7
    )
    session.add_all([boss, worker])
    await session.flush()
    issue = Issue(
        id=5,
        org_id=DEFAULT_ORG_ID,
        title="Течёт кран",
        description="Под раковиной",
        category="other",
        severity="normal",
        status="open",
        department_id=7,
        created_by_employee_id=2,
        shift_date=date(2026, 11, 18),
    )
    session.add(issue)
    await session.commit()
    return boss, worker, issue


async def test_creates_linked_task_for_assignee(session, monkeypatch) -> None:
    # Уведомление — не предмет теста, а app_notifications несёт JSONB, который
    # sqlite не умеет; колокольчик покрыт отдельными тестами.
    async def _no_notify(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(hr_notify, "notify_task_assigned", _no_notify)
    boss, worker, issue = await _seed(session)

    out = await task_from_issue(
        5, IssueTaskIn(assignee_employee_id=2, comment="До пятницы"), session, boss
    )

    task = await session.get(Task, out.task_id)
    assert task is not None
    assert task.title == "Течёт кран"
    assert task.assignee_employee_id == 2
    assert task.comment == "До пятницы"

    refreshed = await session.get(Issue, 5)
    assert refreshed is not None and refreshed.task_id == out.task_id

    events = (await session.scalars(select(IssueEvent))).all()
    assert any("Создано поручение" in (e.comment or "") for e in events)


async def test_uses_issue_assignee_when_body_is_empty(session, monkeypatch) -> None:
    async def _no_notify(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(hr_notify, "notify_task_assigned", _no_notify)
    boss, worker, issue = await _seed(session)
    issue.assignee_employee_id = 2
    await session.commit()

    out = await task_from_issue(5, IssueTaskIn(), session, boss)
    task = await session.get(Task, out.task_id)

    assert task is not None and task.assignee_employee_id == 2


async def test_second_call_is_rejected(session, monkeypatch) -> None:
    async def _no_notify(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(hr_notify, "notify_task_assigned", _no_notify)
    boss, _worker, _issue = await _seed(session)
    await task_from_issue(5, IssueTaskIn(assignee_employee_id=2), session, boss)

    with pytest.raises(HTTPException) as caught:
        await task_from_issue(5, IssueTaskIn(assignee_employee_id=2), session, boss)
    assert caught.value.status_code == 409
