"""Админка платформы (B2B_PLATFORM_PLAN, фаза 4, шаг 4.3).

Что здесь важно проверить, а не «что ручки отвечают 200»:

* клиентский админ организации НЕ попадает в платформу — иначе владелец салона
  увидел бы список конкурентов;
* платформа видит несколько тенантов сразу (иначе список всегда из одной
  строки — той, в которую попал фильтр);
* смена тарифа снимает триал, а блокировка выключает клиента;
* подтверждение оплаты продлевает подписку — это единственный путь, которым
  тариф становится платным.

Ручки вызываем напрямую (как `test_org_setup_route`): HTTP-слой здесь ничего
не решает, а зависимости подставлять не нужно.
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


from app.api import routes_platform  # noqa: E402
from app.config import BUILTIN_ADMIN_TG_IDS  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import ROLE_ADMIN, Employee  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.services import billing  # noqa: E402

# Владелец продукта: встроенный id всегда в наборе, env для теста не нужен.
ADMIN_TG = BUILTIN_ADMIN_TG_IDS[0]
CLIENT_TG = 555001

TABLES = (
    "organizations",
    "users",
    "employees",
    "departments",
    "org_invitations",
    "org_invoices",
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


async def _two_orgs(session) -> tuple[User, User]:
    """Две организации разных клиентов и по владельцу в каждой.

    Вторая нужна именно для проверки обхода тенантов: с фильтром платформа
    увидела бы только первую и тест прошёл бы, ничего не проверив.
    """
    now = datetime.now(UTC)
    session.add_all(
        [
            Organization(
                id=1,
                slug="salon-a",
                name="Салон А",
                plan="trial",
                trial_ends_at=now + timedelta(days=10),
            ),
            Organization(
                id=2,
                slug="salon-b",
                name="Салон Б",
                plan="business",
                plan_ends_at=now + timedelta(days=20),
            ),
            User(id=1, telegram_id=None, email="a@example.com", display_name="А"),
            User(id=2, telegram_id=None, email="b@example.com", display_name="Б"),
            User(id=3, telegram_id=ADMIN_TG, display_name="Платформа"),
            User(id=4, telegram_id=CLIENT_TG, display_name="Клиент"),
        ]
    )
    session.add_all(
        [
            Employee(org_id=1, user_id=1, role=ROLE_ADMIN),
            Employee(org_id=2, user_id=2, role=ROLE_ADMIN),
            Employee(org_id=1, user_id=4, role=ROLE_ADMIN),
        ]
    )
    await session.commit()
    admin = await session.get(User, 3)
    client = await session.get(User, 4)
    assert admin is not None and client is not None
    return admin, client


async def test_client_admin_does_not_get_platform_access(session) -> None:
    """Роль `admin` в организации — не пропуск в платформу."""
    admin, client = await _two_orgs(session)

    assert (await routes_platform.platform_me(admin)).is_platform_admin is True
    assert (await routes_platform.platform_me(client)).is_platform_admin is False

    with pytest.raises(HTTPException) as exc:
        await routes_platform.require_platform_admin(client)
    assert exc.value.status_code == 403
    assert exc.value.detail == "platform_admin_required"


async def test_org_list_sees_every_tenant(session) -> None:
    """Без `all_orgs()` список был бы из одной организации — той, что в фильтре."""
    admin, _ = await _two_orgs(session)

    page = await routes_platform.platform_orgs(session, admin, q="", limit=50, offset=0)

    assert page.total == 2
    assert {row.name for row in page.items} == {"Салон А", "Салон Б"}
    # Лимит и занятое место считаются по своей организации, а не общим числом.
    first = next(row for row in page.items if row.slug == "salon-a")
    assert first.seats_used == 2
    assert first.seats_limit == billing.PLANS["trial"].seats

    # Ищем по коду: `ilike` регистронезависим для кириллицы только в Postgres,
    # а в sqlite-тесте «салон» не совпал бы с «Салон» — и тест врал бы.
    found = await routes_platform.platform_orgs(session, admin, q="salon-b", limit=50, offset=0)
    assert [row.slug for row in found.items] == ["salon-b"]


async def test_plan_change_clears_trial_and_blocking_is_saved(session) -> None:
    admin, _ = await _two_orgs(session)

    updated = await routes_platform.platform_patch_org(
        1,
        routes_platform.PlatformOrgPatch(plan="network"),
        session,
        admin,
    )
    assert updated.plan == "network"
    assert updated.trial_ends_at is None

    blocked = await routes_platform.platform_patch_org(
        2,
        routes_platform.PlatformOrgPatch(is_active=False),
        session,
        admin,
    )
    assert blocked.is_active is False

    with pytest.raises(HTTPException) as exc:
        await routes_platform.platform_patch_org(
            2,
            routes_platform.PlatformOrgPatch(plan="enterprise"),
            session,
            admin,
        )
    assert exc.value.detail == "bad_plan"


async def test_confirmed_payment_extends_subscription_and_cancel_works(session) -> None:
    """Единственный путь к платному тарифу: платформа подтвердила счёт."""
    admin, _ = await _two_orgs(session)
    org = await session.get(Organization, 1)
    assert org is not None
    invoice = await billing.create_invoice(
        session, org, plan_code="start", period="month", created_by_id=1
    )

    confirmed = await routes_platform.platform_confirm_invoice(invoice.id, session, admin)

    await session.refresh(org)
    assert confirmed.status == billing.INVOICE_PAID
    assert org.plan == "start"
    assert org.plan_ends_at is not None
    assert org.trial_ends_at is None

    other = await billing.create_invoice(
        session, org, plan_code="business", period="year", created_by_id=1
    )
    canceled = await routes_platform.platform_cancel_invoice(other.id, session, admin)
    assert canceled.status == billing.INVOICE_CANCELED

    with pytest.raises(HTTPException) as exc:
        await routes_platform.platform_cancel_invoice(other.id, session, admin)
    assert exc.value.detail == "invoice_not_cancelable"


async def test_summary_counts_trial_and_waiting_money(session) -> None:
    admin, _ = await _two_orgs(session)
    org = await session.get(Organization, 1)
    assert org is not None
    await billing.create_invoice(session, org, plan_code="start", period="month", created_by_id=1)

    summary = await routes_platform.platform_summary(session, admin)

    assert summary.organizations == 2
    assert summary.active == 2
    assert summary.on_trial == 1
    assert summary.awaiting_invoices == 1
    assert summary.unpaid_amount == billing.PLANS["start"].price_month
