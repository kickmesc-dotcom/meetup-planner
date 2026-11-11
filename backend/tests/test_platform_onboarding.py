"""Замер онбординга (этап 8, AAA_ROADMAP).

Что проверяем, а не «ручка отвечает 200»:

* считается первое закрытие задачи, а не последнее;
* медиана не ломается от одного опоздавшего;
* демо-профили не попадают в знаменатель — их активность создаёт бот;
* два тенанта видны вместе, и цифры не смешиваются.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy import BigInteger  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw):  # noqa: ARG001
    return "JSON"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):  # noqa: ARG001
    return "INTEGER"


from app.db.base import Base  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ONBOARDING_DONE,
    ONBOARDING_NEW,
    TASK_DONE,
    Employee,
    Task,
    TaskEvent,
)
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.services import onboarding  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "employees",
    "departments",
    "tasks",
    "task_events",
    "checklist_templates",
    "checklist_runs",
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


async def _seed(session) -> None:
    start = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    session.add_all(
        [
            Organization(id=1, slug="salon-a", name="Салон А", plan="trial"),
            Organization(id=2, slug="salon-b", name="Салон Б", plan="business"),
            User(id=1, telegram_id=None, email="a@example.com", display_name="Аня"),
            User(id=2, telegram_id=None, email="b@example.com", display_name="Борис"),
            User(id=3, telegram_id=None, email="c@example.com", display_name="Вера"),
            User(id=4, telegram_id=900001, display_name="Демо"),
        ]
    )
    await session.flush()
    session.add_all(
        [
            Employee(
                id=1,
                org_id=1,
                user_id=1,
                onboarding_state=ONBOARDING_DONE,
                created_at=start,
                hire_date=start.date(),
            ),
            Employee(
                id=2,
                org_id=1,
                user_id=2,
                onboarding_state=ONBOARDING_NEW,
                created_at=start,
                hire_date=start.date(),
            ),
            # Демо-профиль: его «задачи» создаёт бот, в знаменатель он не идёт.
            Employee(
                id=3,
                org_id=1,
                user_id=4,
                is_demo=True,
                onboarding_state=ONBOARDING_DONE,
                created_at=start,
            ),
            # Второй тенант: человек заведён, но ничего не закрыл.
            Employee(
                id=4,
                org_id=2,
                user_id=3,
                onboarding_state=ONBOARDING_NEW,
                created_at=start,
            ),
        ]
    )
    await session.flush()
    session.add_all(
        [
            Task(id=1, org_id=1, title="Витрина", status=TASK_DONE),
            Task(id=2, org_id=1, title="Касса", status=TASK_DONE),
        ]
    )
    await session.flush()
    session.add_all(
        [
            # Первая задача — через 2 часа, вторая — через 10: считаться должна
            # первая, иначе медиана описывала бы «последнюю», а не «дошёл».
            TaskEvent(
                org_id=1,
                task_id=1,
                to_status=TASK_DONE,
                by_employee_id=1,
                at=start + timedelta(hours=2),
            ),
            TaskEvent(
                org_id=1,
                task_id=2,
                to_status=TASK_DONE,
                by_employee_id=1,
                at=start + timedelta(hours=10),
            ),
            # Событие демо-профиля не должно дать ему зачёт.
            TaskEvent(
                org_id=1,
                task_id=2,
                to_status=TASK_DONE,
                by_employee_id=3,
                at=start + timedelta(hours=1),
            ),
        ]
    )
    await session.commit()


async def test_onboarding_counts_first_task_and_skips_demo(session) -> None:
    await _seed(session)

    data = await onboarding.snapshot(session)

    org_a = next(item for item in data["orgs"] if item["org_id"] == 1)
    # Двое реальных людей: демо-профиль в знаменатель не попал.
    assert org_a["people"] == 2
    assert org_a["first_task_done"] == 1
    assert org_a["first_task_share"] == 0.5
    # Первое закрытие — 2 часа, а не 10 и не 1 (демо).
    assert org_a["median_hours_to_first_task"] == 2.0
    assert org_a["onboarding_done"] == 1

    org_b = next(item for item in data["orgs"] if item["org_id"] == 2)
    assert org_b["people"] == 1
    assert org_b["first_task_done"] == 0
    assert org_b["median_hours_to_first_task"] is None

    totals = data["totals"]
    assert totals["people"] == 3
    assert totals["first_task_done"] == 1
    assert totals["first_task_share"] == 0.333
    assert totals["median_hours_to_first_task"] == 2.0


async def test_negative_time_is_clamped_to_zero(session) -> None:
    """Импорт может дать событие раньше профиля — это шум, а не «−3 часа»."""
    start = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    session.add_all(
        [
            Organization(id=1, slug="salon-a", name="Салон А", plan="trial"),
            User(id=1, telegram_id=None, email="a@example.com", display_name="Аня"),
            Employee(id=1, org_id=1, user_id=1, created_at=start),
            Task(id=1, org_id=1, title="Витрина", status=TASK_DONE),
        ]
    )
    await session.flush()
    session.add(
        TaskEvent(
            org_id=1,
            task_id=1,
            to_status=TASK_DONE,
            by_employee_id=1,
            at=start - timedelta(hours=3),
        )
    )
    await session.commit()

    data = await onboarding.snapshot(session)
    assert data["totals"]["median_hours_to_first_task"] == 0.0
