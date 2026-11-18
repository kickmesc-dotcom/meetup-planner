"""Склад расходников: остаток, движения и границы прав."""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.hr_models import ROLE_ADMIN, ROLE_EMPLOYEE, Employee  # noqa: E402

from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.services import hr_supplies  # noqa: E402

TABLES = ("organizations", "users", "employees", "departments", "supplies", "supply_movements")


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


async def _people(session):
    session.add(Organization(id=DEFAULT_ORG_ID, slug="default", name="Моя"))
    session.add_all(
        [
            User(id=1, telegram_id=900001, display_name="Анна"),
            User(id=2, telegram_id=900002, display_name="Борис"),
        ]
    )
    await session.flush()
    admin = Employee(id=1, org_id=DEFAULT_ORG_ID, user_id=1, role=ROLE_ADMIN)
    worker = Employee(id=2, org_id=DEFAULT_ORG_ID, user_id=2, role=ROLE_EMPLOYEE)
    session.add_all([admin, worker])
    await session.commit()
    return admin, worker


async def test_create_and_withdraw(session) -> None:
    admin, worker = await _people(session)

    item = await hr_supplies.create_supply(
        session, viewer=admin, name="Перчатки", unit="пар", quantity=10, min_quantity=2
    )
    assert item.quantity == 10
    assert item.low is False

    result = await hr_supplies.move(
        session, viewer=worker, supply_id=item.id, kind="out", quantity=10, comment="Смена"
    )
    assert result.supply.quantity == 0
    assert result.supply.low is True
    assert result.movement.employee_name is None  # имя подтягивается в истории
    # Первое движение через порог — повод для push, повторные — нет.
    assert result.crossed_low is True

    history = await hr_supplies.history(session, viewer=worker, supply_id=item.id)
    assert [row.kind for row in history] == ["out", "in"]
    assert history[0].employee_name == "Борис"


async def test_cannot_withdraw_more_than_left(session) -> None:
    admin, worker = await _people(session)
    item = await hr_supplies.create_supply(
        session, viewer=admin, name="Салфетки", quantity=3
    )

    with pytest.raises(hr_supplies.SupplyError, match="not_enough"):
        await hr_supplies.move(
            session, viewer=worker, supply_id=item.id, kind="out", quantity=4
        )

    # Отказ не меняет остаток и не оставляет движения.
    rows = await hr_supplies.list_supplies(session, viewer=admin)
    assert rows[0].quantity == 3
    assert len(await hr_supplies.history(session, viewer=admin, supply_id=item.id)) == 1


async def test_quantity_must_be_positive(session) -> None:
    admin, worker = await _people(session)
    item = await hr_supplies.create_supply(session, viewer=admin, name="Мешки", quantity=5)

    for bad in (0, -1, "abc"):
        with pytest.raises(hr_supplies.SupplyError):
            await hr_supplies.move(
                session, viewer=worker, supply_id=item.id, kind="out", quantity=bad
            )


async def test_fractional_quantities_keep_two_decimals(session) -> None:
    admin, _worker = await _people(session)
    item = await hr_supplies.create_supply(
        session, viewer=admin, name="Средство", unit="л", quantity="1.5"
    )
    result = await hr_supplies.move(
        session, viewer=admin, supply_id=item.id, kind="out", quantity="0.75"
    )
    assert result.supply.quantity == 0.75


async def test_limit_blocks_extra_withdrawals(session) -> None:
    admin, worker = await _people(session)
    item = await hr_supplies.create_supply(
        session, viewer=admin, name="Химия", quantity=10, max_out_per_shift=2
    )

    await hr_supplies.move(
        session, viewer=worker, supply_id=item.id, kind="out", quantity=1.5
    )
    with pytest.raises(hr_supplies.SupplyError, match="limit_exceeded"):
        await hr_supplies.move(
            session, viewer=worker, supply_id=item.id, kind="out", quantity=1
        )
    # Инвентаризация — не списание: лимит не должен мешать сверке.
    counted = await hr_supplies.count_supply(
        session, viewer=admin, supply_id=item.id, quantity=6
    )
    assert counted.delta == -2.5


async def test_inventory_records_discrepancy(session) -> None:
    admin, _worker = await _people(session)
    item = await hr_supplies.create_supply(session, viewer=admin, name="Мешки", quantity=10)

    result = await hr_supplies.count_supply(
        session, viewer=admin, supply_id=item.id, quantity=7, comment="порвались"
    )
    assert result.delta == -3
    assert result.supply.quantity == 7
    assert result.movement is not None and result.movement.is_inventory is True

    rows = await hr_supplies.discrepancies(session, viewer=admin, days=30)
    assert len(rows) == 1
    assert rows[0].delta == -3
    assert "порвались" in (rows[0].comment or "")


async def test_employee_without_department_sees_only_shared(session) -> None:
    admin, worker = await _people(session)
    await hr_supplies.create_supply(session, viewer=admin, name="Общее", quantity=1)

    from app.db.hr_models import Department

    dept = Department(org_id=DEFAULT_ORG_ID, name="Кухня", slug="kitchen")
    session.add(dept)
    await session.flush()
    await hr_supplies.create_supply(
        session, viewer=admin, name="Кухонное", quantity=1, department_id=dept.id
    )
    await session.commit()

    visible = await hr_supplies.list_supplies(session, viewer=worker)
    assert [row.name for row in visible] == ["Общее"]
