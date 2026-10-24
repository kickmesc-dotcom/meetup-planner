"""Приглашения в организацию (B2B_PLATFORM_PLAN, шаг 2.2).

Проверяем свойства, без которых ссылка-приглашение опасна или бесполезна:

* человек попадает в **пригласившую** организацию, а не в первую по id;
* поиск по токену работает вне тенантского фильтра (иначе ссылки всех
  организаций, кроме первой, «не находились» бы);
* ссылка одноразовая, со сроком и отзывом;
* именное приглашение (с почтой) не принимает чужой аккаунт;
* роль из приглашения становится HR-ролью нового профиля (manager → aup);
* список и отзыв видят только свою организацию.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.api import deps, routes_orgs  # noqa: E402
from app.db.auth_models import AuthSession  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import Department, Employee  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    OrgInvitation,
    current_org_id,
    reset_org,
    set_org,
)
from app.services import accounts, invitations, mail, orgs  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "departments",
    "employees",
    "organization_members",
    "auth_sessions",
    "org_invitations",
)

PASSWORD = "correct-horse-battery"
EMAIL = "worker@example.com"


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


async def _orgs(session) -> tuple[Organization, Organization]:
    first = Organization(id=DEFAULT_ORG_ID, slug="default", name="Моя организация")
    second = Organization(id=2, slug="salon", name="Салон «Красота»")
    session.add_all([first, second])
    await session.commit()
    return first, second


# --------------------------------------------------------------------------
# Создание
# --------------------------------------------------------------------------


async def test_create_returns_link_once_and_stores_only_hash(session) -> None:
    first, _ = await _orgs(session)
    row, token = await invitations.create(
        session, org_id=first.id, created_by_id=None, role="manager", email=" New@Example.COM "
    )

    assert row.org_id == first.id
    assert row.role == "manager"
    assert row.email == "new@example.com"
    assert token not in (row.token_hash or "")
    assert row.token_hash == accounts.token_hash(token)
    assert row.accepted_at is None and row.revoked_at is None
    assert await invitations.preview(session, token) is not None


async def test_create_validates_role_ttl_and_email(session) -> None:
    first, _ = await _orgs(session)
    with pytest.raises(invitations.InvitationsError, match="bad_role"):
        await invitations.create(
            session, org_id=first.id, created_by_id=None, role="god"
        )
    with pytest.raises(invitations.InvitationsError, match="bad_invite_ttl"):
        await invitations.create(
            session, org_id=first.id, created_by_id=None, days=0
        )
    with pytest.raises(invitations.InvitationsError, match="bad_invite_ttl"):
        await invitations.create(
            session, org_id=first.id, created_by_id=None, days=90
        )
    with pytest.raises(invitations.InvitationsError, match="bad_email"):
        await invitations.create(
            session, org_id=first.id, created_by_id=None, email="не-почта"
        )


async def test_active_links_are_limited(session, monkeypatch) -> None:
    first, _ = await _orgs(session)
    monkeypatch.setattr(invitations, "MAX_ACTIVE", 2)
    for _ in range(2):
        await invitations.create(session, org_id=first.id, created_by_id=None)
    with pytest.raises(invitations.InvitationsError, match="invite_limit"):
        await invitations.create(session, org_id=first.id, created_by_id=None)


async def test_link_points_to_the_public_app(monkeypatch) -> None:
    monkeypatch.setattr(
        invitations,
        "get_settings",
        lambda: SimpleNamespace(link_base="https://app.example.com"),
    )
    assert (
        invitations.invite_link("tok-123")
        == "https://app.example.com/invite?token=tok-123"
    )


# --------------------------------------------------------------------------
# Поиск и срок
# --------------------------------------------------------------------------


async def test_token_lookup_sees_every_tenant(session) -> None:
    """Приглашение второй организации находится при контексте первой.

    Это главный тест на `all_orgs()`: обычный тенантский фильтр искал бы
    ссылку только в первой организации, и приглашения остальных клиентов
    отвечали бы «ссылка не подходит».
    """
    _first, second = await _orgs(session)
    row, token = await invitations.create(
        session, org_id=second.id, created_by_id=None
    )
    assert current_org_id.get() == DEFAULT_ORG_ID

    found, org = await invitations.preview(session, token)
    assert found.id == row.id
    assert org.id == second.id


async def test_expired_link_is_rejected(session) -> None:
    first, _ = await _orgs(session)
    row, token = await invitations.create(
        session, org_id=first.id, created_by_id=None
    )
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()

    with pytest.raises(invitations.InvitationsError, match="invite_expired"):
        await invitations.preview(session, token)


async def test_unknown_and_empty_token_is_invalid(session) -> None:
    await _orgs(session)
    with pytest.raises(invitations.InvitationsError, match="invite_invalid"):
        await invitations.preview(session, "nope")
    with pytest.raises(invitations.InvitationsError, match="invite_invalid"):
        await invitations.preview(session, "x" * 200)


# --------------------------------------------------------------------------
# Принятие
# --------------------------------------------------------------------------


async def test_accept_puts_user_into_the_inviting_org(session) -> None:
    first, second = await _orgs(session)
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    # Сессия выдана до приглашения — организации в ней нет.
    session_row, _token = await accounts.create_session(session, user)
    assert session_row.org_id is None

    _row, token = await invitations.create(
        session, org_id=second.id, created_by_id=None, role="manager"
    )
    org, role = await invitations.accept(session, token=token, user=user)

    assert org.id == second.id
    assert role == "manager"
    member = await orgs.member(session, org_id=second.id, user_id=user.id)
    assert member is not None and member.role == "manager"
    # В первой организации его быть не должно.
    assert await orgs.member(session, org_id=first.id, user_id=user.id) is None
    assert current_org_id.get() == second.id

    # Живые входы переехали в новую организацию — иначе следующий запрос
    # подтянул бы первую (или никакую).
    sessions = list(await session.scalars(select(AuthSession)))
    assert [row.org_id for row in sessions] == [second.id]


async def test_accept_is_single_use_and_revocable(session) -> None:
    first, _ = await _orgs(session)
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    _row, token = await invitations.create(
        session, org_id=first.id, created_by_id=None
    )
    await invitations.accept(session, token=token, user=user)
    with pytest.raises(invitations.InvitationsError, match="invite_used"):
        await invitations.accept(session, token=token, user=user)

    _row2, token2 = await invitations.create(
        session, org_id=first.id, created_by_id=None
    )
    stored = await session.scalar(
        select(OrgInvitation).where(
            OrgInvitation.token_hash == accounts.token_hash(token2)
        )
    )
    await invitations.revoke(
        session, org_id=first.id, invitation_id=stored.id
    )
    with pytest.raises(invitations.InvitationsError, match="invite_revoked"):
        await invitations.preview(session, token2)
    with pytest.raises(invitations.InvitationsError, match="invite_revoked"):
        await invitations.accept(session, token=token2, user=user)


async def test_named_invite_rejects_another_account(session) -> None:
    first, _ = await _orgs(session)
    invited = await accounts.register(
        session, email="invited@example.com", password=PASSWORD
    )
    stranger = await accounts.register(
        session, email="stranger@example.com", password=PASSWORD
    )
    _row, token = await invitations.create(
        session, org_id=first.id, created_by_id=None, email="invited@example.com"
    )

    with pytest.raises(invitations.InvitationsError, match="invite_email_mismatch"):
        await invitations.accept(session, token=token, user=stranger)
    assert await orgs.member(session, org_id=first.id, user_id=stranger.id) is None

    _org, role = await invitations.accept(session, token=token, user=invited)
    assert role == "staff"


async def test_existing_membership_keeps_its_role(session) -> None:
    """Пересланная ссылка не должна менять уже выданную роль."""
    first, _ = await _orgs(session)
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    await orgs.ensure_member(session, org_id=first.id, user_id=user.id, role="owner")

    _row, token = await invitations.create(
        session, org_id=first.id, created_by_id=None, role="staff"
    )
    _org, role = await invitations.accept(session, token=token, user=user)
    assert role == "owner"


async def test_inactive_org_cannot_be_joined(session) -> None:
    _first, second = await _orgs(session)
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    _row, token = await invitations.create(
        session, org_id=second.id, created_by_id=None
    )
    second.is_active = False
    await session.commit()

    with pytest.raises(invitations.InvitationsError, match="org_inactive"):
        await invitations.accept(session, token=token, user=user)


# --------------------------------------------------------------------------
# Список и отзыв
# --------------------------------------------------------------------------


async def test_list_is_scoped_to_the_org_and_hides_dead_links(session) -> None:
    first, second = await _orgs(session)
    mine, _ = await invitations.create(
        session, org_id=first.id, created_by_id=None
    )
    await invitations.create(session, org_id=second.id, created_by_id=None)
    dead, _ = await invitations.create(
        session, org_id=first.id, created_by_id=None
    )
    dead.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()

    rows = await invitations.active(session, first.id)
    assert [row.id for row in rows] == [mine.id]


async def test_revoke_does_not_touch_another_org(session) -> None:
    first, second = await _orgs(session)
    foreign, _token = await invitations.create(
        session, org_id=second.id, created_by_id=None
    )
    with pytest.raises(invitations.InvitationsError, match="invite_not_found"):
        await invitations.revoke(
            session, org_id=first.id, invitation_id=foreign.id
        )
    # Ссылка чужой организации осталась живой.
    assert (await invitations.preview(session, _token))[1].id == second.id


# --------------------------------------------------------------------------
# Роли и права
# --------------------------------------------------------------------------


async def test_accepting_manager_invite_grants_manager_rights(session) -> None:
    """manager из приглашения = `aup` в HR-профиле нового сотрудника."""
    _first, second = await _orgs(session)
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    _row, token = await invitations.create(
        session, org_id=second.id, created_by_id=None, role="manager"
    )
    await invitations.accept(session, token=token, user=user)

    employee = await anext(deps.current_employee(session, user, None))
    assert employee.org_id == second.id
    assert employee.role == "aup"


async def test_invite_carries_position_and_department_to_new_profile(
    session,
) -> None:
    """Должность и отдел из ссылки попадают в профиль, созданный при входе."""
    _first, second = await _orgs(session)
    dept = Department(id=10, org_id=second.id, name="Бар", slug="bar")
    session.add(dept)
    await session.commit()
    await session.refresh(dept)

    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    _row, token = await invitations.create(
        session,
        org_id=second.id,
        created_by_id=None,
        role="staff",
        position="Бармен",
        department_id=dept.id,
    )
    await invitations.accept(session, token=token, user=user)

    employee = await anext(deps.current_employee(session, user, None))
    assert employee.org_id == second.id
    assert employee.position == "Бармен"
    assert employee.department_id == dept.id


async def test_invite_fields_update_an_existing_profile(session) -> None:
    """Если профиль уже был, ссылка всё равно меняет должность и отдел."""
    _first, second = await _orgs(session)
    dept = Department(id=11, org_id=second.id, name="Кухня", slug="kitchen")
    session.add(dept)
    await session.commit()
    await session.refresh(dept)

    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    employee = Employee(org_id=second.id, user_id=user.id, role="employee")
    session.add(employee)
    await session.commit()

    _row, token = await invitations.create(
        session,
        org_id=second.id,
        created_by_id=None,
        position="Повар",
        department_id=dept.id,
    )
    await invitations.accept(session, token=token, user=user)

    await session.refresh(employee)
    assert employee.position == "Повар"
    assert employee.department_id == dept.id


async def test_invite_rejects_department_of_another_org(session) -> None:
    """Чужой отдел в ссылку не попадёт: иначе человек получил бы доступ к
    структуре другой организации."""
    first, second = await _orgs(session)
    foreign = Department(id=12, org_id=first.id, name="Бар", slug="bar")
    session.add(foreign)
    await session.commit()
    await session.refresh(foreign)
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)

    with pytest.raises(HTTPException) as err:
        await routes_orgs.create_invitation(
            routes_orgs.InvitationIn(role="staff", department_id=foreign.id),
            session,
            user,
            second,
            None,
        )
    assert err.value.status_code == 400
    assert err.value.detail == "department_not_found"


async def test_accepting_owner_invite_grants_admin_rights(session) -> None:
    _first, second = await _orgs(session)
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    _row, token = await invitations.create(
        session, org_id=second.id, created_by_id=None, role="owner"
    )
    await invitations.accept(session, token=token, user=user)

    employee = await anext(deps.current_employee(session, user, None))
    assert employee.role == "admin"


# --------------------------------------------------------------------------
# Ручки
# --------------------------------------------------------------------------


async def test_preview_route_maps_errors_to_http_codes(session) -> None:
    first, _ = await _orgs(session)
    _row, token = await invitations.create(
        session, org_id=first.id, created_by_id=None
    )
    preview = await routes_orgs.preview_invitation(token, session)
    assert preview.org_name == first.name
    assert preview.role == "staff"

    with pytest.raises(HTTPException) as missing:
        await routes_orgs.preview_invitation("nope", session)
    assert missing.value.status_code == 404
    assert missing.value.detail == "invite_invalid"


async def test_create_route_sends_mail_only_when_transport_works(session, monkeypatch) -> None:
    first, _ = await _orgs(session)
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)

    # Режим «лог»: письмо не ушло, и интерфейс не должен это обещать.
    monkeypatch.setattr(routes_orgs.mail, "send", AsyncMock(return_value="log"))
    created = await routes_orgs.create_invitation(
        routes_orgs.InvitationIn(email="invited@example.com", role="manager"),
        session,
        user,
        first,
        None,
    )
    assert created.link and "/invite?token=" in created.link
    assert created.email == "invited@example.com"
    assert created.mail_sent is False

    # Настроенный транспорт — письмо ушло.
    monkeypatch.setattr(routes_orgs.mail, "send", AsyncMock(return_value="smtp"))
    sent = await routes_orgs.create_invitation(
        routes_orgs.InvitationIn(email="second@example.com"),
        session,
        user,
        first,
        None,
    )
    assert sent.mail_sent is True

    # Без адреса письмо не отправляется вовсе — ссылку кидают вручную.
    link_only = await routes_orgs.create_invitation(
        routes_orgs.InvitationIn(), session, user, first, None
    )
    assert link_only.email is None
    assert link_only.mail_sent is False


async def test_accept_route_returns_the_org(session) -> None:
    _first, second = await _orgs(session)
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    _row, token = await invitations.create(
        session, org_id=second.id, created_by_id=None
    )
    result = await routes_orgs.accept_invitation(token, session, user)
    assert result.ok is True
    assert result.org_id == second.id
    assert result.org_name == second.name


async def test_session_without_org_falls_back_to_membership(session) -> None:
    """Сессия, выданная до приглашения, всё равно попадает в нужную организацию."""
    _first, second = await _orgs(session)
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    _row, token = await accounts.create_session(session, user)
    await orgs.ensure_member(session, org_id=second.id, user_id=user.id)

    settings = SimpleNamespace(bot_token="1:test", initdata_max_age_seconds=86400)
    await deps.current_user(session, settings, f"Bearer {token}", None)
    assert current_org_id.get() == second.id


def test_mail_template_mentions_the_link() -> None:
    message = mail.invite_email(
        to="worker@example.com", org_name="Салон", link="https://app/invite?token=t"
    )
    assert message.to == "worker@example.com"
    assert "https://app/invite?token=t" in message.text
    assert "Салон" in message.subject
