"""Приватность организации (B2B_PLATFORM_PLAN, фаза 5, шаг 5.5).

Что проверяем, а не «ручка отвечает 200»:

* выгрузка содержит людей только своей организации и не содержит токенов;
* выгрузка пишет событие в журнал — «кто забрал данные» не теряется;
* удаление требует точный код организации, иначе опечатка стирает клиента;
* после запроса команда теряет доступ, а владелец может отменить — иначе
  необратимое действие нельзя было бы исправить;
* по истечении срока организация удаляется физически, а не помечается;
* журнал одной организации не виден другой.

Env выставляем ДО импорта моделей — `Settings` требует BOT_TOKEN и т.п.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

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


from app.api import deps, routes_orgs  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import Employee  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    AuditEvent,
    Organization,
    OrganizationMember,
)
from app.services import privacy  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "employees",
    "departments",
    "organization_members",
    "org_invitations",
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


async def _org(session, *, org_id: int = 1, slug: str = "salon-a", name: str = "Салон А"):
    org = Organization(id=org_id, slug=slug, name=name)
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org


async def _user(session, *, user_id: int = 1, tg: int = 1001, name: str = "Анна"):
    user = User(id=user_id, telegram_id=tg, display_name=name)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _member(session, org, user, role: str = "owner"):
    row = OrganizationMember(org_id=org.id, user_id=user.id, role=role)
    session.add(row)
    await session.commit()
    return row


async def _employee(session, org, user, role: str = "employee"):
    row = Employee(org_id=org.id, user_id=user.id, role=role)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def test_export_contains_only_own_org_and_no_tokens(session) -> None:
    """В файле — свои люди; токенов приглашений и чужих строк там нет."""
    first = await _org(session, org_id=1, slug="salon-a", name="Салон А")
    owner = await _user(session, user_id=1, tg=1001, name="Анна")
    await _member(session, first, owner)
    await _employee(session, first, owner, role="admin")

    second = await _org(session, org_id=2, slug="salon-b", name="Салон Б")
    stranger = await _user(session, user_id=2, tg=2002, name="Чужой")
    await _employee(session, second, stranger, role="admin")

    data = await privacy.export_org(session, first)

    assert data["organization"]["slug"] == "salon-a"
    assert [row["user_id"] for row in data["employees"]] == [1]
    assert [row["user_id"] for row in data["members"]] == [1]
    assert "token_hash" not in json.dumps(data, ensure_ascii=False)


async def test_export_route_is_attachment_and_writes_audit(session) -> None:
    """Скачивание — файл, а не страница; факт выгрузки остаётся в журнале."""
    org = await _org(session)
    owner = await _user(session)
    await _member(session, org, owner)

    response = await routes_orgs.export_organization(session, owner, org, None)  # type: ignore[arg-type]

    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert "salon-a" in disposition
    assert response.headers["cache-control"] == "no-store"

    rows = await session.scalars(select(AuditEvent))
    events = list(rows)
    assert [row.action for row in events] == ["data.exported"]
    assert events[0].actor_name == "Анна"


async def test_deletion_requires_exact_code_and_sets_grace(session) -> None:
    """`bad_confirm` — не формальность: удаление необратимо."""
    org = await _org(session)
    owner = await _user(session)
    await _member(session, org, owner)

    with pytest.raises(HTTPException) as bad:
        await routes_orgs.delete_organization(
            routes_orgs.DeleteOrgIn(confirm="salon"), session, owner, org, None  # type: ignore[arg-type]
        )
    assert bad.value.detail == "bad_confirm"
    await session.refresh(org)
    assert org.deleted_at is None

    out = await routes_orgs.delete_organization(
        routes_orgs.DeleteOrgIn(confirm=" SALON-A "), session, owner, org, None  # type: ignore[arg-type]
    )
    assert out.deleted is True
    assert out.days_left == privacy.GRACE_DAYS

    with pytest.raises(HTTPException) as second:
        await routes_orgs.delete_organization(
            routes_orgs.DeleteOrgIn(confirm="salon-a"), session, owner, org, None  # type: ignore[arg-type]
        )
    assert second.value.detail == "already_deleting"


async def test_manager_cannot_delete_or_export(session) -> None:
    """Выгрузка и удаление — только владельцу: это люди и необратимость."""
    org = await _org(session)
    manager = await _user(session, user_id=2, tg=2002, name="Менеджер")
    await _member(session, org, manager, role="manager")

    with pytest.raises(HTTPException) as export:
        await routes_orgs.export_organization(session, manager, org, None)  # type: ignore[arg-type]
    assert export.value.detail == "owner_required"
    assert export.value.status_code == 403

    with pytest.raises(HTTPException) as delete:
        await routes_orgs.delete_organization(
            routes_orgs.DeleteOrgIn(confirm=org.slug), session, manager, org, None  # type: ignore[arg-type]
        )
    assert delete.value.detail == "owner_required"


async def test_restore_cancels_deletion(session) -> None:
    """Владелец может передумать, пока срок не вышел."""
    org = await _org(session)
    owner = await _user(session)
    await _member(session, org, owner)
    await routes_orgs.delete_organization(
        routes_orgs.DeleteOrgIn(confirm=org.slug), session, owner, org, None  # type: ignore[arg-type]
    )

    out = await routes_orgs.restore_organization(session, owner, org, None)  # type: ignore[arg-type]

    assert out.deleted is False
    assert out.purge_after is None
    await session.refresh(org)
    assert org.deleted_at is None

    with pytest.raises(HTTPException) as again:
        await routes_orgs.restore_organization(session, owner, org, None)  # type: ignore[arg-type]
    assert again.value.detail == "not_deleting"


async def test_deleting_org_is_closed_for_staff_but_open_for_owner(session) -> None:
    """Команда уже не работает, владелец видит состояние и может отменить."""
    org = await _org(session)
    owner = await _user(session, user_id=1, tg=1001, name="Анна")
    staff = await _user(session, user_id=2, tg=2002, name="Пётр")
    await _member(session, org, owner, role="owner")
    await _member(session, org, staff, role="staff")
    owner_employee = await _employee(session, org, owner, role="admin")
    staff_employee = await _employee(session, org, staff)
    await privacy.request_deletion(
        session, org, confirm=org.slug, user=owner
    )

    with pytest.raises(HTTPException) as closed:
        await deps.current_org(session, staff_employee, staff)
    assert closed.value.status_code == 403
    assert closed.value.detail == "org_deleting"

    assert (await deps.current_org(session, owner_employee, owner)).id == org.id


async def test_purge_due_deletes_only_expired_orgs(session) -> None:
    """Срок вышел — строки организации удаляются, а не помечаются."""
    due = await _org(session, org_id=1, slug="salon-a", name="Салон А")
    fresh = await _org(session, org_id=2, slug="salon-b", name="Салон Б")
    moment = datetime.now(timezone.utc)
    due.purge_after = moment - timedelta(days=1)
    fresh.purge_after = moment + timedelta(days=10)
    await session.commit()

    removed = await privacy.purge_due_orgs(session, now=moment)

    assert removed == [1]
    remaining = [row.id for row in (await session.scalars(select(Organization))).all()]
    assert remaining == [2]


async def test_audit_is_isolated_between_orgs(session) -> None:
    """Журнал одного клиента не виден другому."""
    first = await _org(session, org_id=1, slug="salon-a", name="Салон А")
    second = await _org(session, org_id=2, slug="salon-b", name="Салон Б")
    owner = await _user(session)
    await _member(session, first, owner)
    await routes_orgs.export_organization(session, owner, first, None)  # type: ignore[arg-type]

    assert len(await routes_orgs.organization_audit(session, first, None, 50)) == 1  # type: ignore[arg-type]
    assert await routes_orgs.organization_audit(session, second, None, 50) == []  # type: ignore[arg-type]


def test_retention_numbers_are_promised_and_finite() -> None:
    """Сроки — числа, а не «разумно»: их обещают клиенту в кабинете."""
    values = privacy.retention()
    assert values["audit_days"] == 180
    assert values["deletion_grace_days"] == 30
    assert values["fired_trash_days"] == 30
    assert values["backup_artifact_days"] == 14
