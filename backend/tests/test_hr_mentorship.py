"""Первая неделя новичка: кто в списке и как назначается наставник."""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from datetime import UTC, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.hr_models import ROLE_ADMIN, TASK_OVERDUE, Employee, Task  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.services import hr_mentorship, hr_settings  # noqa: E402

TABLES = ("organizations", "users", "employees", "tasks", "hr_shifts", "departments")


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


async def _seed(session, now: datetime):
    session.add(Organization(id=DEFAULT_ORG_ID, slug="default", name="Моя"))
    session.add_all(
        [
            User(id=1, telegram_id=900001, display_name="Анна"),
            User(id=2, telegram_id=900002, display_name="Борис"),
            User(id=3, telegram_id=900003, display_name="Вера"),
        ]
    )
    await session.flush()
    admin = Employee(id=1, org_id=DEFAULT_ORG_ID, user_id=1, role=ROLE_ADMIN)
    mentor = Employee(id=2, org_id=DEFAULT_ORG_ID, user_id=2)
    trainee = Employee(
        id=3,
        org_id=DEFAULT_ORG_ID,
        user_id=3,
        # Дата найма считается по поясу организации: иначе тест зависит от
        # того, успел ли UTC-день перевалить за полночь по Москве.
        hire_date=hr_settings.local_now(now).date() - timedelta(days=2),
        last_seen_at=None,
    )
    session.add_all([admin, mentor, trainee])
    await session.flush()
    session.add(
        Task(
            id=1,
            org_id=DEFAULT_ORG_ID,
            title="Пройти инструктаж",
            scope="employee",
            mode="one_of",
            status=TASK_OVERDUE,
            assignee_employee_id=3,
            due_at=now - timedelta(days=1),
            created_at=now - timedelta(days=2),
            updated_at=now,
        )
    )
    await session.commit()
    return admin, mentor, trainee


async def test_trainees_include_risk_and_mentor(session) -> None:
    now = datetime.now(UTC)
    admin, mentor, trainee = await _seed(session, now)

    items = await hr_mentorship.list_trainees(session, viewer=admin, now=now)

    assert [item.employee_id for item in items] == [trainee.id]
    item = items[0]
    assert item.name == "Вера"
    assert item.days_in_team == 2
    assert item.overdue_tasks == 1
    assert item.mentor_employee_id is None
    # Не заходил ни разу и есть просрочка — это как раз тот, кого надо спросить.
    assert item.at_risk is True

    assigned = await hr_mentorship.assign_mentor(
        session, viewer=admin, employee_id=trainee.id, mentor_id=mentor.id
    )
    assert assigned.mentor_employee_id == mentor.id
    assert assigned.mentor_name == "Борис"


async def test_mentor_cannot_be_self(session) -> None:
    now = datetime.now(UTC)
    admin, _mentor, trainee = await _seed(session, now)

    with pytest.raises(hr_mentorship.MentorshipError, match="mentor_is_trainee"):
        await hr_mentorship.assign_mentor(
            session, viewer=admin, employee_id=trainee.id, mentor_id=trainee.id
        )


async def test_unknown_employee_is_404_semantics(session) -> None:
    now = datetime.now(UTC)
    admin, _mentor, _trainee = await _seed(session, now)

    with pytest.raises(hr_mentorship.MentorshipError, match="employee_not_found"):
        await hr_mentorship.assign_mentor(
            session, viewer=admin, employee_id=999, mentor_id=None
        )
