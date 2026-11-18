"""Счётчики «фича + действие»: приём и сводка."""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.api.routes_telemetry import (  # noqa: E402
    ProductEventIn,
    accept_product_event,
    feature_usage,
)
from app.db.base import Base  # noqa: E402
from app.db.hr_models import ROLE_ADMIN, Employee, ProductEvent  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)

TABLES = ("organizations", "users", "employees", "product_events")


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


async def _admin(session) -> Employee:
    session.add(Organization(id=DEFAULT_ORG_ID, slug="default", name="Моя"))
    session.add(User(id=1, telegram_id=900001, display_name="Анна"))
    await session.flush()
    admin = Employee(id=1, org_id=DEFAULT_ORG_ID, user_id=1, role=ROLE_ADMIN)
    session.add(admin)
    await session.commit()
    return admin


async def test_event_is_stored_with_org(session) -> None:
    admin = await _admin(session)

    response = await accept_product_event(
        ProductEventIn(feature="supplies", action="write_off", screen="supplies", device="mobile"),
        session,
        admin,
    )

    assert response.status_code == 204
    stored = (await session.scalars(select(ProductEvent))).all()
    assert len(stored) == 1
    assert stored[0].org_id == DEFAULT_ORG_ID
    assert stored[0].feature == "supplies"
    assert stored[0].device == "mobile"


async def test_usage_counts_by_action(session) -> None:
    admin = await _admin(session)
    for action in ("open", "open", "write_off"):
        await accept_product_event(
            ProductEventIn(feature="supplies", action=action), session, admin
        )
    await accept_product_event(
        ProductEventIn(feature="week_summary", action="open"), session, admin
    )

    rows = await feature_usage(session, admin, days=7)

    counts = {(row.feature, row.action): row.count for row in rows}
    assert counts[("supplies", "open")] == 2
    assert counts[("supplies", "write_off")] == 1
    assert counts[("week_summary", "open")] == 1
    # Самое частое — первым: руководитель читает сводку сверху.
    assert rows[0].count == 2


async def test_rejects_free_text(session) -> None:
    admin = await _admin(session)
    with pytest.raises(ValueError):
        ProductEventIn(feature="Склад: перчатки", action="open")
    assert (await session.scalars(select(ProductEvent))).all() == []
    assert admin.id == 1
