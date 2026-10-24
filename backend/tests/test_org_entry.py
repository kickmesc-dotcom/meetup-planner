"""Первый запуск: вход в организацию и создание своей.

Проверяем ровно то, что делает этот вход безопасным и рабочим:

* код или точное название ведут в **свою** организацию, а не в первую по id;
* ошибка не отличается для «нет такой» и «не то название» — иначе по коду
  ответа можно перебирать клиентов платформы;
* роль при входе — `staff`: код не даёт прав управления;
* владелец новой организации получает `owner`, а не `staff`;
* живые сессии переезжают в новую организацию, иначе следующее устройство
  продолжало бы смотреть в прежний тенант.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.api import routes_orgs  # noqa: E402
from app.db.auth_models import AuthSession  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import Employee  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    OrganizationMember,
    reset_org,
    set_org,
)
from app.services import orgs  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "employees",
    "organization_members",
    "auth_sessions",
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


async def _setup(session) -> User:
    session.add_all(
        [
            Organization(id=DEFAULT_ORG_ID, slug="default", name="Моя организация"),
            Organization(id=2, slug="kofeynya", name="Кофейня на углу"),
        ]
    )
    # Цвет пользователя выводится из Telegram ID, поэтому он нужен и здесь.
    user = User(
        id=1, telegram_id=999001, email="new@example.com", display_name="Новичок"
    )
    session.add(user)
    session.add(
        AuthSession(
            id=1,
            token_hash="hash",
            user_id=1,
            org_id=DEFAULT_ORG_ID,
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
    )
    await session.commit()
    return user


async def test_join_by_slug_lands_in_that_org_as_staff(session) -> None:
    user = await _setup(session)

    org, role = await orgs.join_by_code(session, user=user, code="kofeynya")

    assert org.id == 2
    assert role == "staff"
    row = await orgs.member(session, org_id=2, user_id=user.id)
    assert row is not None and row.role == "staff"
    # Живой вход переехал: иначе следующее устройство осталось бы в прежнем
    # тенанте и увидело бы чужие данные.
    auth_row = await session.get(AuthSession, 1)
    assert auth_row is not None and auth_row.org_id == 2


async def test_join_by_exact_name_ignores_case(session) -> None:
    user = await _setup(session)

    org, _ = await orgs.join_by_code(session, user=user, code="  кофейня на углу ")

    assert org.id == 2


async def test_unknown_name_and_unknown_code_look_the_same(session) -> None:
    user = await _setup(session)

    with pytest.raises(orgs.OrgsError) as by_name:
        await orgs.join_by_code(session, user=user, code="Кофейня")
    with pytest.raises(orgs.OrgsError) as by_slug:
        await orgs.join_by_code(session, user=user, code="kofe")

    # Один код ошибки: разница позволила бы угадывать названия клиентов.
    assert str(by_name.value) == str(by_slug.value) == "org_not_found"


async def test_inactive_org_does_not_let_people_in(session) -> None:
    user = await _setup(session)
    org = await session.get(Organization, 2)
    assert org is not None
    org.is_active = False
    await session.commit()

    with pytest.raises(orgs.OrgsError) as err:
        await orgs.join_by_code(session, user=user, code="kofeynya")
    assert str(err.value) == "org_inactive"


async def test_create_makes_owner_and_unique_slug(session) -> None:
    user = await _setup(session)

    org = await orgs.create_with_owner(
        session, user=user, name="Kofeynya", industry="cafe"
    )

    # Совпадение с существующим кодом не должно падать 500: получаем суффикс.
    assert org.slug == "kofeynya-2"
    row = await orgs.member(session, org_id=org.id, user_id=user.id)
    assert row is not None and row.role == "owner"
    auth_row = await session.get(AuthSession, 1)
    assert auth_row is not None and auth_row.org_id == org.id


async def test_create_rejects_short_name(session) -> None:
    user = await _setup(session)

    with pytest.raises(orgs.OrgsError) as err:
        await orgs.create_with_owner(session, user=user, name=" ")
    assert str(err.value) == "bad_name"


async def _team(session):
    """Организация с владельцем, сотрудником и админом-наблюдателем.

    Роль меняет один, права проверяются у него же: `AdminDep` уже гарантирует,
    что запрос пришёл от администратора.
    """
    owner = await _setup(session)
    session.add_all(
        [
            OrganizationMember(
                org_id=DEFAULT_ORG_ID, user_id=owner.id, role="owner"
            ),
            User(
                id=2,
                telegram_id=999002,
                email="staff@example.com",
                display_name="Сотрудник",
            ),
            OrganizationMember(
                org_id=DEFAULT_ORG_ID, user_id=2, role="staff"
            ),
            Employee(
                org_id=DEFAULT_ORG_ID, user_id=2, role="employee"
            ),
            User(
                id=3,
                telegram_id=999003,
                email="watcher@example.com",
                display_name="Наблюдатель",
            ),
            OrganizationMember(
                org_id=DEFAULT_ORG_ID, user_id=3, role="staff"
            ),
            Employee(org_id=DEFAULT_ORG_ID, user_id=3, role="admin"),
        ]
    )
    await session.commit()
    org = await session.get(Organization, DEFAULT_ORG_ID)
    assert org is not None
    return owner, org


async def test_member_role_updates_membership_and_hr_role(session) -> None:
    owner, org = await _team(session)

    out = await routes_orgs.set_member_role(
        2,
        routes_orgs.OrgMemberRoleIn(role="manager"),
        session,
        owner,
        org,
        None,
    )

    assert out.role == "manager"
    assert out.hr_role == "aup"
    employee = await session.scalar(
        select(Employee).where(Employee.user_id == 2)
    )
    assert employee is not None
    assert employee.role == "aup"
    # Ручной выбор должен пережить `ensure_employee`.
    assert employee.role_locked is True


async def test_member_cannot_change_own_role(session) -> None:
    owner, org = await _team(session)

    with pytest.raises(HTTPException) as err:
        await routes_orgs.set_member_role(
            1,
            routes_orgs.OrgMemberRoleIn(role="staff"),
            session,
            owner,
            org,
            None,
        )
    assert err.value.status_code == 400
    assert err.value.detail == "self_role_change"


async def test_last_owner_cannot_be_demoted(session) -> None:
    _, org = await _team(session)
    watcher = await session.get(User, 3)
    assert watcher is not None

    with pytest.raises(HTTPException) as err:
        await routes_orgs.set_member_role(
            1,
            routes_orgs.OrgMemberRoleIn(role="manager"),
            session,
            watcher,
            org,
            None,
        )
    assert err.value.status_code == 409
    assert err.value.detail == "last_owner"


async def test_unknown_member_and_role_are_rejected(session) -> None:
    owner, org = await _team(session)

    with pytest.raises(HTTPException) as no_member:
        await routes_orgs.set_member_role(
            999,
            routes_orgs.OrgMemberRoleIn(role="staff"),
            session,
            owner,
            org,
            None,
        )
    assert no_member.value.status_code == 404

    with pytest.raises(HTTPException) as bad_role:
        await routes_orgs.set_member_role(
            2,
            routes_orgs.OrgMemberRoleIn(role="boss"),
            session,
            owner,
            org,
            None,
        )
    assert bad_role.value.status_code == 400


async def test_members_list_shows_roles_and_marks_self(session) -> None:
    owner, org = await _team(session)

    rows = await routes_orgs.list_members(session, owner, org, None)

    # Владелец — первым, остальные по имени внутри своего уровня.
    assert rows[0].user_id == 1
    assert rows[0].role == "owner" and rows[0].is_self is True
    by_id = {row.user_id: row for row in rows}
    assert set(by_id) == {1, 2, 3}
    assert by_id[2].hr_role == "employee"
    assert by_id[2].is_self is False


async def test_membership_rows_are_not_duplicated(session) -> None:
    user = await _setup(session)

    await orgs.join_by_code(session, user=user, code="kofeynya")
    await orgs.join_by_code(session, user=user, code="Кофейня на углу")

    all_rows = (await session.execute(OrganizationMember.__table__.select())).all()
    assert len(all_rows) == 1
