"""Мастер настройки организации: что реально доходит до базы.

Здесь проверяется не разбор ответов (он в `test_org_setup_privacy.py`), а два
следа, на которых ломался первый запуск:

* владелец, закрывший мастер, больше не попадает в анкету сотрудника —
  «где ты работаешь» ему задавать нечего, он только что назвал отделы сам;
* организация не остаётся без единого подразделения. Мастер можно пропустить,
  а профиль без отдела невозможно закрыть — получался тупик без выхода.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.api import routes_hr  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ONBOARDING_DONE,
    ONBOARDING_NEW,
    ROLE_ADMIN,
    Department,
    Employee,
)
from app.db.models import User  # noqa: E402
from app.db.org_models import DEFAULT_ORG_ID, Organization, reset_org, set_org  # noqa: E402

TABLES = ("organizations", "users", "employees", "departments", "admin_config")


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


async def _owner(session) -> tuple[User, Employee]:
    """Владелец, заведённый по почте: у него нет Telegram ID (B2B-путь)."""
    session.add(Organization(id=DEFAULT_ORG_ID, slug="default", name="Кофейня"))
    user = User(id=1, telegram_id=None, email="owner@example.com", display_name="Владелец")
    session.add(user)
    employee = Employee(
        org_id=DEFAULT_ORG_ID,
        user_id=1,
        role=ROLE_ADMIN,
        onboarding_state=ONBOARDING_NEW,
    )
    session.add(employee)
    await session.commit()
    return user, employee


async def test_finished_setup_creates_a_department_instead_of_a_dead_end(session) -> None:
    user, employee = await _owner(session)

    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(done=True), session, user, employee
    )

    departments = (await session.scalars(select(Department))).all()
    assert [dep.name for dep in departments] == ["Общее"]
    await session.refresh(employee)
    assert employee.onboarding_state == ONBOARDING_DONE


async def test_second_visit_does_not_duplicate_the_fallback_department(session) -> None:
    user, employee = await _owner(session)

    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(done=True), session, user, employee
    )
    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(done=True), session, user, employee
    )

    departments = (await session.scalars(select(Department))).all()
    assert len(departments) == 1


async def test_chosen_departments_win_over_the_fallback(session) -> None:
    user, employee = await _owner(session)

    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(
            departments=["Кухня", "Бариста"], create_departments=True
        ),
        session,
        user,
        employee,
    )
    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(done=True), session, user, employee
    )

    departments = (await session.scalars(select(Department))).all()
    assert sorted(dep.name for dep in departments) == ["Бариста", "Кухня"]


async def test_unfinished_setup_keeps_the_wizard_open(session) -> None:
    user, employee = await _owner(session)

    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(industry="cafe"), session, user, employee
    )

    await session.refresh(employee)
    assert employee.onboarding_state == ONBOARDING_NEW
    assert (await session.scalars(select(Department))).all() == []
