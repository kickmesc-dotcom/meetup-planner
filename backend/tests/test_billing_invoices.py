"""Счета и продление подписки (B2B_PLATFORM_PLAN, фаза 4, шаг 4.2).

Зачем тесты. Счёт — это документ, а не кнопка: важно, чтобы сумма бралась из
каталога, а не из тела запроса; чтобы повторный клик не выписывал второй счёт;
чтобы «я оплатил» НЕ продлевало подписку (иначе это бесплатный безлимит); и
чтобы оплата складывалась, а не перезаписывала уже оплаченные дни.

Env выставляем ДО импорта моделей — `Settings` требует BOT_TOKEN и т.п.
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
from app.db.hr_models import ROLE_ADMIN, Employee  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.services import billing  # noqa: E402

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


async def _org(
    session,
    *,
    plan: str = "trial",
    trial_days: int | None = 14,
    paid_until: datetime | None = None,
) -> Organization:
    org = Organization(
        id=DEFAULT_ORG_ID,
        slug="default",
        name="Салон",
        plan=plan,
        trial_ends_at=None
        if trial_days is None
        else datetime.now(UTC) + timedelta(days=trial_days),
        plan_ends_at=paid_until,
    )
    session.add(org)
    session.add(
        User(id=1, telegram_id=None, email="owner@example.com", display_name="Владелец")
    )
    session.add(Employee(org_id=DEFAULT_ORG_ID, user_id=1, role=ROLE_ADMIN))
    await session.commit()
    await session.refresh(org)
    return org


async def test_invoice_amount_comes_from_catalog_not_request(session) -> None:
    """Сумма — из каталога: клиент не выбирает, сколько заплатить."""
    org = await _org(session)

    invoice = await billing.create_invoice(session, org, plan_code="business", period="month")

    assert invoice.amount == billing.PLANS["business"].price_month
    assert invoice.currency == "RUB"
    assert invoice.status == billing.INVOICE_PENDING
    assert invoice.number.startswith("INV-")
    # Счёт не меняет тариф: до денег это обещание, а не подписка.
    assert org.plan == "trial"
    assert org.plan_ends_at is None


async def test_trial_is_not_for_sale_and_period_is_checked(session) -> None:
    org = await _org(session)

    with pytest.raises(billing.InvoiceError) as trial:
        await billing.create_invoice(session, org, plan_code="trial", period="month")
    assert str(trial.value) == "plan_not_payable"

    with pytest.raises(billing.InvoiceError) as period:
        await billing.create_invoice(session, org, plan_code="start", period="week")
    assert str(period.value) == "bad_period"

    with pytest.raises(billing.InvoiceError) as unknown:
        await billing.create_invoice(session, org, plan_code="enterprise", period="month")
    assert str(unknown.value) == "bad_plan"


async def test_second_click_returns_the_same_invoice(session) -> None:
    """Два одинаковых счёта в бухгалтерии клиента — как двойное списание."""
    org = await _org(session)

    first = await billing.create_invoice(session, org, plan_code="start", period="year")
    second = await billing.create_invoice(session, org, plan_code="start", period="year")

    assert first.id == second.id
    rows = await billing.list_invoices(session, org.id)
    assert len(rows) == 1


async def test_owner_cannot_extend_subscription_by_pressing_paid(session) -> None:
    """«Я оплатил» переводит в ожидание, но не продлевает тариф."""
    org = await _org(session)
    invoice = await billing.create_invoice(session, org, plan_code="business", period="month")

    updated = await billing.request_payment(session, org.id, invoice.id)

    assert updated.status == billing.INVOICE_AWAITING
    await session.refresh(org)
    assert org.plan == "trial"
    assert org.plan_ends_at is None


async def test_confirmed_payment_extends_and_stacks_periods(session) -> None:
    """Оплата ставит тариф, снимает триал и складывается с уже оплаченным."""
    org = await _org(session)
    month = await billing.create_invoice(session, org, plan_code="business", period="month")
    await billing.mark_paid(session, org, month)

    assert org.plan == "business"
    assert org.trial_ends_at is None
    first_end = org.plan_ends_at
    assert first_end is not None
    # sqlite отдаёт naive-время: сравниваем в UTC, как это делает сервис.
    assert first_end.replace(tzinfo=UTC) > datetime.now(UTC) + timedelta(days=29)

    year = await billing.create_invoice(session, org, plan_code="network", period="year")
    await billing.mark_paid(session, org, year)

    # Второй платёж добавляет год к уже оплаченному месяцу, а не затирает его.
    assert org.plan == "network"
    assert org.plan_ends_at == first_end + timedelta(days=365)


async def test_expired_subscription_blocks_growth_but_not_work(session) -> None:
    """Просроченная оплата закрывает рост, людей и данные оставляет на месте."""
    org = await _org(
        session,
        plan="business",
        trial_days=None,
        paid_until=datetime.now(UTC) - timedelta(days=1),
    )

    with pytest.raises(billing.PlanError) as exc:
        await billing.ensure_seats(session, org.id)
    assert str(exc.value) == "subscription_expired"

    state = await billing.state(session, org)
    assert state.subscription_expired is True
    assert state.can_add_people is False
    assert state.seats_used == 1  # владелец по-прежнему в организации


async def test_foreign_and_paid_invoices_are_not_editable(session) -> None:
    """Чужой счёт неотличим от несуществующего, оплаченный не отменяется."""
    org = await _org(session)
    invoice = await billing.create_invoice(session, org, plan_code="start", period="month")
    await billing.mark_paid(session, org, invoice)

    with pytest.raises(billing.InvoiceError) as paid:
        await billing.cancel_invoice(session, org.id, invoice.id)
    # Оплаченный счёт не отменяется: это уже деньги, а не обещание.
    assert str(paid.value) == "invoice_not_cancelable"

    with pytest.raises(billing.InvoiceError) as foreign:
        await billing.cancel_invoice(session, org.id + 1, invoice.id)
    assert str(foreign.value) == "invoice_not_found"

    other = await billing.create_invoice(session, org, plan_code="network", period="month")
    canceled = await billing.cancel_invoice(session, org.id, other.id)
    assert canceled.status == billing.INVOICE_CANCELED

    with pytest.raises(billing.InvoiceError) as again:
        await billing.cancel_invoice(session, org.id, other.id)
    # Отменённый счёт — уже не «ждёт оплаты», и код это различает.
    assert str(again.value) == "invoice_not_cancelable"
