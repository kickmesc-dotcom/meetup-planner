"""Тарифы, лимиты и триал (B2B_PLATFORM_PLAN, фаза 4, шаг 4.1).

Зачем тесты. Лимит — это обещание, которое проверяется только отказом. Легко
написать «не больше десяти человек» и не заметить, что приглашения считаются
отдельно (и двадцать ссылок обходят лимит), что демо-пул занимает места живых
людей, что истёкший триал блокирует вход вместо роста. Здесь проверяется
именно поведение на границе, а не наличие констант.

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
from app.db.hr_models import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_EMPLOYEE,
    Department,
    Employee,
)
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.services import billing, invitations  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "employees",
    "departments",
    "org_invitations",
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


async def _org(session, *, plan: str = "trial", days: int | None = 14) -> Organization:
    org = Organization(
        id=DEFAULT_ORG_ID,
        slug="default",
        name="Салон",
        plan=plan,
        trial_ends_at=None if days is None else datetime.now(UTC) + timedelta(days=days),
    )
    session.add(org)
    user = User(id=1, telegram_id=None, email="owner@example.com", display_name="Владелец")
    session.add(user)
    session.add(Employee(org_id=DEFAULT_ORG_ID, user_id=1, role=ROLE_ADMIN))
    await session.commit()
    await session.refresh(org)
    return org


async def _people(session, count: int) -> None:
    """Добавить `count` живых сотрудников (плюс владелец из `_org`)."""
    for index in range(count):
        user_id = 100 + index
        session.add(User(id=user_id, telegram_id=None, display_name=f"Мастер {index}"))
        session.add(
            Employee(org_id=DEFAULT_ORG_ID, user_id=user_id, role=ROLE_EMPLOYEE)
        )
    await session.commit()


async def test_state_counts_live_people_and_invites_but_not_demo(session) -> None:
    """Место занимает человек и обещанное ему приглашение, но не витрина."""
    org = await _org(session)
    await _people(session, 2)
    session.add(User(id=200, telegram_id=None, display_name="[BOT] Мастер"))
    session.add(
        Employee(
            org_id=DEFAULT_ORG_ID,
            user_id=200,
            role=ROLE_EMPLOYEE,
            is_demo=True,
        )
    )
    await session.commit()
    await invitations.create(session, org_id=DEFAULT_ORG_ID, created_by_id=1)

    state = await billing.state(session, org)

    # Владелец + двое мастеров, демо не в счёте.
    assert state.seats_used == 4  # 3 человека + 1 приглашение
    assert state.invites_active == 1
    assert state.seats_limit == billing.PLANS["trial"].seats
    assert state.code == "trial"


async def test_seats_limit_blocks_extra_people_with_clear_code(session) -> None:
    """На границе — отказ `seats_limit`, а не пятисотая и не тихое создание."""
    org = await _org(session)
    await _people(session, billing.PLANS["trial"].seats - 1)

    with pytest.raises(billing.PlanError) as exc:
        await billing.ensure_seats(session, org.id)
    assert str(exc.value) == "seats_limit"

    # Существующие люди продолжают работать: лимит закрывает рост, не работу.
    state = await billing.state(session, org)
    assert state.seats_used == state.seats_limit
    assert state.seats_left == 0
    assert state.can_add_people is False


async def test_invitation_cannot_bypass_seats_limit(session) -> None:
    """Двадцать ссылок при лимите десять — обход лимита, а не забота о людях."""
    await _org(session)
    limit = billing.PLANS["trial"].seats
    # Владелец уже занимает место, остальные — приглашения.
    for _ in range(limit - 1):
        await invitations.create(session, org_id=DEFAULT_ORG_ID, created_by_id=1)

    with pytest.raises(invitations.InvitationsError) as exc:
        await invitations.create(session, org_id=DEFAULT_ORG_ID, created_by_id=1)
    assert str(exc.value) == "seats_limit"


async def test_expired_trial_closes_growth_but_not_work(session) -> None:
    """Триал истёк: данные и вход на месте, новые люди и отделы — нет."""
    org = await _org(session, days=-1)

    state = await billing.state(session, org)
    assert state.trial_expired is True
    assert state.can_add_people is False
    assert state.trial_days_left is None

    with pytest.raises(billing.PlanError) as exc:
        await billing.ensure_seats(session, org.id)
    assert str(exc.value) == "trial_expired"

    with pytest.raises(billing.PlanError) as exc:
        await billing.ensure_branches(session, org.id)
    assert str(exc.value) == "trial_expired"


async def test_paid_plan_has_no_trial_deadline(session) -> None:
    """У платного тарифа срок не закрывает рост, даже если дата осталась старая."""
    org = await _org(session, plan="start", days=-5)

    state = await billing.state(session, org)
    assert state.trial_expired is False
    await billing.ensure_seats(session, org.id)


async def test_branches_limit_counts_active_departments(session) -> None:
    """Погашенное подразделение лимит не занимает: место освобождается."""
    org = await _org(session)
    limit = billing.PLANS["trial"].branches
    for index in range(limit):
        session.add(
            Department(
                org_id=DEFAULT_ORG_ID,
                name=f"Отдел {index}",
                slug=f"dept-{index}",
                is_active=index != 0,
            )
        )
    await session.commit()

    state = await billing.state(session, org)
    assert state.branches_used == limit - 1
    await billing.ensure_branches(session, org.id)

    session.add(
        Department(org_id=DEFAULT_ORG_ID, name="Новый", slug="novyy", is_active=True)
    )
    await session.commit()
    with pytest.raises(billing.PlanError) as exc:
        await billing.ensure_branches(session, org.id)
    assert str(exc.value) == "branches_limit"


async def test_unknown_plan_falls_back_to_trial(session) -> None:
    """Неизвестный код тарифа не должен ронять экран: считаем пробным."""
    org = await _org(session, plan="whatever")
    state = await billing.state(session, org)
    assert state.code == "trial"
    assert state.seats_limit == billing.PLANS["trial"].seats
