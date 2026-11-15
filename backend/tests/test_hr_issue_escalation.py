"""Эскалация проблем по времени (13.11.2026).

Что проверяем и почему:

* **через 4 часа тишины** — напоминание назначенному, а не всем сразу;
* **через 12 часов после напоминания** — руководителю отдела;
* **повторный тик молчит** — маркер в истории, иначе каждые 15 минут одно и то
  же сообщение;
* **закрытая проблема не попадает** — эскалация про открытые, остальное шум.

Env выставляем ДО импорта моделей: `Settings` требует BOT_TOKEN и т.п.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ROLE_AUP,
    ROLE_EMPLOYEE,
    ISSUE_OPEN,
    ISSUE_RESOLVED,
    Department,
    Employee,
    Issue,
    IssueEvent,
)
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.services import hr_issue_escalation, hr_notify  # noqa: E402

TABLES = (
    "organizations",
    "departments",
    "users",
    "employees",
    "tasks",
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
        yield db
    await engine.dispose()


@pytest.fixture(autouse=True)
def clean_org_context():
    token = set_org(DEFAULT_ORG_ID)
    yield
    reset_org(token)


@pytest.fixture(autouse=True)
def quiet_channels(monkeypatch):
    """Каналы наружу в тестах не трогаем: проверяем решения, а не доставку."""

    async def _noop(*_args, **_kwargs) -> int:
        return 0

    monkeypatch.setattr(hr_notify, "notify", _noop)
    monkeypatch.setattr(hr_notify, "push_event", _noop)


async def _staff(session):
    """Отдел, назначенный и руководитель — минимум для эскалации."""
    session.add(Organization(id=DEFAULT_ORG_ID, slug="default", name="Моя"))
    session.add(
        Department(id=7, org_id=DEFAULT_ORG_ID, name="Зал", slug="zal")
    )
    session.add_all(
        [
            User(id=1, telegram_id=900001, display_name="Пётр"),
            User(id=2, telegram_id=900002, display_name="Анна"),
        ]
    )
    await session.flush()
    worker = Employee(
        id=1,
        org_id=DEFAULT_ORG_ID,
        user_id=1,
        role=ROLE_EMPLOYEE,
        department_id=7,
        is_active=True,
    )
    manager = Employee(
        id=2,
        org_id=DEFAULT_ORG_ID,
        user_id=2,
        role=ROLE_AUP,
        department_id=7,
        is_active=True,
    )
    session.add_all([worker, manager])
    await session.commit()
    return worker, manager


async def _issue(session, *, age_hours: int, status: str = ISSUE_OPEN):
    moment = datetime.now(UTC) - timedelta(hours=age_hours)
    issue = Issue(
        # SQLite не автоинкрементит BIGINT-ключ: задаём явно, как в тестах меню.
        id=1,
        org_id=DEFAULT_ORG_ID,
        title="Течёт кран",
        status=status,
        department_id=7,
        assignee_employee_id=1,
        created_by_employee_id=1,
        shift_date=moment.date(),
        created_at=moment,
        updated_at=moment,
    )
    session.add(issue)
    await session.commit()
    return issue


async def test_reminder_goes_to_assignee_after_four_hours(session) -> None:
    worker, _manager = await _staff(session)
    issue = await _issue(session, age_hours=5)

    plans = await hr_issue_escalation.plan(session)

    assert [(p.issue.id, p.step) for p in plans] == [(issue.id, "reminder")]
    assert [e.id for e in plans[0].recipients] == [worker.id]


async def test_fresh_issue_is_not_touched(session) -> None:
    await _staff(session)
    await _issue(session, age_hours=1)

    assert await hr_issue_escalation.plan(session) == []


async def test_second_step_goes_to_manager(session) -> None:
    _worker, manager = await _staff(session)
    issue = await _issue(session, age_hours=17)

    moment = datetime.now(UTC)
    # Маркер напоминания двенадцать часов назад — созрела вторая ступень.
    session.add(
        IssueEvent(
            id=1,
            issue_id=issue.id,
            kind=hr_issue_escalation.EVENT_REMINDER,
            at=moment - timedelta(hours=12),
        )
    )
    await session.commit()

    plans = await hr_issue_escalation.plan(session, now=moment)

    assert [p.step for p in plans] == ["manager"]
    assert [e.id for e in plans[0].recipients] == [manager.id]


async def test_resolved_issue_is_skipped(session) -> None:
    await _staff(session)
    await _issue(session, age_hours=30, status=ISSUE_RESOLVED)

    assert await hr_issue_escalation.plan(session) == []


async def test_run_marks_history_and_does_not_repeat(session) -> None:
    await _staff(session)
    issue = await _issue(session, age_hours=5)

    assert await hr_issue_escalation.run(session) == 1
    await session.commit()

    kinds = list(
        (
            await session.scalars(
                select(IssueEvent.kind).where(IssueEvent.issue_id == issue.id)
            )
        ).all()
    )
    assert kinds == [hr_issue_escalation.EVENT_REMINDER]

    # Второй тик: маркер уже есть, до второй ступени ещё далеко.
    assert await hr_issue_escalation.run(session) == 0


async def test_marker_stops_repeat_after_escalation(session) -> None:
    await _staff(session)
    issue = await _issue(session, age_hours=30)
    session.add(
        IssueEvent(
            id=2,
            issue_id=issue.id,
            kind=hr_issue_escalation.EVENT_ESCALATED,
            at=datetime.now(UTC) - timedelta(minutes=5),
        )
    )
    await session.commit()

    assert await hr_issue_escalation.plan(session) == []
    assert await hr_issue_escalation.run(session) == 0
