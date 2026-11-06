"""Филиалы сети (06.11.2026).

Проверяем обещания, которые нельзя ломать: филиал — отдельная организация со
своей связью с головной, чужой в него не переключится, глубже одного уровня
дерево не растёт, а профиль сотрудника ищется по организации, а не «первый
попавшийся».
"""

from __future__ import annotations

import os

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
from app.db.hr_models import Employee  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.org_models import Organization  # noqa: E402
from app.services import branches, hr_access, orgs  # noqa: E402


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    names = ("users", "organizations", "departments", "employees", "organization_members")
    tables = [Base.metadata.tables[name] for name in names if name in Base.metadata.tables]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


async def _user(session, user_id: int = 1) -> User:
    user = User(id=user_id, telegram_id=1000 + user_id, display_name=f"Владелец {user_id}")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _org(session, slug: str, org_id: int) -> Organization:
    org = Organization(id=org_id, slug=slug, name=f"Салон {slug}")
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org


async def test_branch_keeps_link_to_root(session) -> None:
    user = await _user(session)
    root = await _org(session, "salon", 1)
    await orgs.add_member(session, org_id=root.id, user_id=user.id, role="owner")

    branch = await branches.create_branch(
        session, root=root, user=user, name="Салон Юг"
    )

    assert branch.parent_org_id == root.id
    assert branch.id != root.id
    assert (await branches.root_of(session, branch)).id == root.id
    member = await orgs.member(session, org_id=branch.id, user_id=user.id)
    assert member is not None and member.role == "owner"


async def test_owner_switches_into_branch_but_stranger_cannot(session) -> None:
    owner = await _user(session, 1)
    stranger = await _user(session, 2)
    root = await _org(session, "salon", 1)
    await orgs.add_member(session, org_id=root.id, user_id=owner.id, role="owner")
    branch = await branches.create_branch(
        session, root=root, user=owner, name="Салон Юг"
    )

    assert await branches.can_switch(session, user_id=owner.id, org_id=branch.id)
    assert not await branches.can_switch(
        session, user_id=stranger.id, org_id=branch.id
    )


async def test_employee_switches_only_into_own_org(session) -> None:
    employee = await _user(session, 3)
    root = await _org(session, "salon", 1)
    other = await _org(session, "other", 2)

    assert not await branches.can_switch(
        session, user_id=employee.id, org_id=other.id
    )
    session.add(Employee(user_id=employee.id, org_id=root.id, role="employee"))
    await session.commit()

    assert await branches.can_switch(session, user_id=employee.id, org_id=root.id)


async def test_network_does_not_include_foreign_orgs(session) -> None:
    user = await _user(session)
    root = await _org(session, "salon", 1)
    await orgs.add_member(session, org_id=root.id, user_id=user.id, role="owner")
    branch = await branches.create_branch(
        session, root=root, user=user, name="Салон Юг"
    )
    await _org(session, "other", 3)

    rows = await branches.network(session, root=root, user_id=user.id)

    assert {org.id for org, _role in rows} == {root.id, branch.id}


async def test_branch_cannot_have_its_own_branch(session) -> None:
    user = await _user(session)
    root = await _org(session, "salon", 1)
    await orgs.add_member(session, org_id=root.id, user_id=user.id, role="owner")
    branch = await branches.create_branch(
        session, root=root, user=user, name="Салон Юг"
    )

    with pytest.raises(branches.BranchesError) as caught:
        await branches.create_branch(
            session, root=branch, user=user, name="Салон Юг-2"
        )
    assert str(caught.value) == "branch_of_branch"


async def test_branch_limit_stops_growth(session, monkeypatch) -> None:
    user = await _user(session)
    root = await _org(session, "salon", 1)
    await orgs.add_member(session, org_id=root.id, user_id=user.id, role="owner")
    await branches.create_branch(session, root=root, user=user, name="Салон Юг")
    monkeypatch.setattr(branches, "MAX_BRANCHES", 1)

    with pytest.raises(branches.BranchesError) as caught:
        await branches.create_branch(session, root=root, user=user, name="Салон Север")
    assert str(caught.value) == "branch_limit"


async def test_employee_lookup_is_scoped_by_org(session) -> None:
    user = await _user(session)
    first_org = await _org(session, "salon", 1)
    second_org = await _org(session, "branch", 2)
    session.add_all(
        [
            Employee(user_id=user.id, org_id=first_org.id, role="employee"),
            Employee(user_id=user.id, org_id=second_org.id, role="admin"),
        ]
    )
    await session.commit()

    first = await hr_access.get_employee(session, user.id, org_id=first_org.id)
    second = await hr_access.get_employee(session, user.id, org_id=second_org.id)

    assert first is not None and first.org_id == first_org.id
    assert second is not None and second.org_id == second_org.id
    assert first.role == "employee" and second.role == "admin"
