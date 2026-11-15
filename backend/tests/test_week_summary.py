"""Недельная сводка «что мешало смене» (13.11.2026).

Проверяем границы периода и правила подсчёта: сводка, которая ошибается на
границе недели, хуже отсутствующей — по ней принимают решения.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from datetime import UTC, date, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ROLE_ADMIN,
    ISSUE_OPEN,
    ISSUE_RESOLVED,
    TASK_DONE,
    TASK_OVERDUE,
    Employee,
    Issue,
    Task,
)
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.services import hr_week_summary  # noqa: E402

TABLES = (
    "organizations",
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


async def _admin(session) -> Employee:
    session.add(Organization(id=DEFAULT_ORG_ID, slug="default", name="Моя"))
    session.add(User(id=1, telegram_id=900001, display_name="Анна"))
    await session.flush()
    admin = Employee(
        id=1,
        org_id=DEFAULT_ORG_ID,
        user_id=1,
        role=ROLE_ADMIN,
        is_active=True,
    )
    session.add(admin)
    await session.commit()
    return admin


def test_period_covers_seven_days_including_today() -> None:
    start, end = hr_week_summary.period(datetime(2026, 11, 13, 10, 0, tzinfo=UTC))
    assert (start, end) == (date(2026, 11, 7), date(2026, 11, 13))


def test_age_never_goes_negative() -> None:
    moment = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    assert hr_week_summary.age_hours(moment - timedelta(hours=5), moment) == 5
    # Часы базы и приложения разошлись — показываем ноль, а не «-1 ч».
    assert hr_week_summary.age_hours(moment + timedelta(hours=2), moment) == 0


async def test_counts_issues_and_tasks(session) -> None:
    admin = await _admin(session)
    moment = datetime.now(UTC)
    recent = moment - timedelta(days=1)

    session.add_all(
        [
            Issue(
                id=1,
                org_id=DEFAULT_ORG_ID,
                title="Течёт кран",
                status=ISSUE_OPEN,
                category="equipment",
                shift_date=recent.date(),
                created_at=recent,
                updated_at=recent,
            ),
            Issue(
                id=2,
                org_id=DEFAULT_ORG_ID,
                title="Гость ждал счёт",
                status=ISSUE_RESOLVED,
                category="guest",
                shift_date=recent.date(),
                created_at=recent,
                updated_at=recent,
                resolved_at=moment - timedelta(hours=2),
            ),
            Task(
                id=1,
                org_id=DEFAULT_ORG_ID,
                title="Закрыть кассу",
                scope="employee",
                mode="one_of",
                status=TASK_DONE,
                due_at=moment - timedelta(hours=3),
                done_at=moment - timedelta(hours=1),
                created_at=recent,
                updated_at=moment,
            ),
            Task(
                id=2,
                org_id=DEFAULT_ORG_ID,
                title="Проверить стоп-лист",
                scope="employee",
                mode="one_of",
                status=TASK_OVERDUE,
                due_at=moment - timedelta(hours=6),
                created_at=recent,
                updated_at=moment,
            ),
        ]
    )
    await session.commit()

    summary = await hr_week_summary.build(session, viewer=admin, now=moment)

    assert summary.issues_new == 2
    assert summary.issues_closed == 1
    assert summary.issues_open == 1
    assert summary.tasks_done == 1
    assert summary.tasks_done_late == 1
    assert summary.tasks_overdue_open == 1
    assert {(row.category, row.count) for row in summary.categories} == {
        ("equipment", 1),
        ("guest", 1),
    }
    assert {item.title for item in summary.blockers} == {"Течёт кран", "Гость ждал счёт"}
