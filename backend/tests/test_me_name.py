"""Имя в приложении (настройки профиля, 06.11.2026).

Имя из Telegram у половины людей — «мама», «Аня 🍓» или ник. В списке команды
и в ленте это читается как чужой человек, поэтому рабочее имя хранится
отдельно и меняется без переименования аккаунта в мессенджере.

Здесь проверяются ровно те обещания, которые легко сломать следующей правкой:
пробелы не попадают в базу, чужой профиль не переименовать, демо-профиль
сохраняет метку `[BOT]`, а смена попадает в журнал доступа.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import BigInteger, select  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw):  # noqa: ARG001
    return "JSON"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):  # noqa: ARG001
    return "INTEGER"


from app.api import routes_hr  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import Employee  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.org_models import AuditEvent, Organization  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "employees",
    "admin_config",
    "audit_events",
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


async def _org(session):
    org = Organization(id=1, slug="salon-a", name="Салон А")
    session.add(org)
    await session.commit()
    return org


async def _employee(session, org, *, user_id: int = 1, tg: int = 1001, demo: bool = False):
    user = User(id=user_id, telegram_id=tg, display_name="Аня 🍓")
    session.add(user)
    await session.commit()
    employee = Employee(
        org_id=org.id, user_id=user.id, role="employee", is_demo=demo
    )
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    return user, employee


async def _call(session, user, employee, name: str):
    return await routes_hr.set_my_name(
        routes_hr.MyNameIn(display_name=name), session, user, employee
    )


async def test_name_is_saved_and_spaces_collapse(session) -> None:
    org = await _org(session)
    user, employee = await _employee(session, org)

    out = await _call(session, user, employee, "  Анна   Петрова ")

    assert out.display_name == "Анна Петрова"
    await session.refresh(user)
    assert user.display_name == "Анна Петрова"


async def test_rename_is_logged_with_before_and_after(session) -> None:
    org = await _org(session)
    user, employee = await _employee(session, org)

    await _call(session, user, employee, "Анна Петрова")

    event = await session.scalar(
        select(AuditEvent).where(AuditEvent.action == "profile.name")
    )
    assert event is not None
    assert event.org_id == org.id
    assert event.actor_user_id == user.id
    assert "Аня" in (event.details or "") and "Анна Петрова" in (event.details or "")


async def test_empty_name_is_rejected(session) -> None:
    org = await _org(session)
    user, employee = await _employee(session, org)

    with pytest.raises(HTTPException) as caught:
        await _call(session, user, employee, "   ")
    assert caught.value.status_code == 400


async def test_demo_profile_keeps_its_mark(session) -> None:
    org = await _org(session)
    user, employee = await _employee(session, org, demo=True)

    with pytest.raises(HTTPException) as caught:
        await _call(session, user, employee, "Другой человек")
    assert caught.value.status_code == 409
    await session.refresh(user)
    assert user.display_name == "Аня 🍓"


async def test_foreign_profile_cannot_be_renamed(session) -> None:
    """В режиме проверки сессия админа, а профиль — чужой."""
    org = await _org(session)
    owner, employee = await _employee(session, org, user_id=1, tg=1001)
    # Админ без своего HR-профиля: у него есть право войти, но `employee`
    # принадлежит другому человеку. Раньше тест случайно делал админа
    # владельцем профиля и проверял не то.
    admin = User(id=2, telegram_id=1002, display_name="Админ")
    session.add(admin)
    await session.commit()

    with pytest.raises(HTTPException) as caught:
        await _call(session, admin, employee, "Подмена")
    assert caught.value.status_code == 409
    await session.refresh(owner)
    assert owner.display_name == "Аня 🍓"
