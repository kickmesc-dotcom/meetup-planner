"""Входящий обмен по ключу организации (B2B_PLATFORM_PLAN, шаг 6.2).

Проверяем обещания контракта, а не «ручка отвечает 200»:

* без `people.write` / `schedule.write` данные не меняются (и отказ приходит
  ДО записи, а не после);
* повтор с тем же `Idempotency-Key` возвращает тот же ответ и не создаёт
  второго человека;
* тот же ключ с другим файлом — 409: это не повтор, а ошибка интегратора;
* предпросмотр по ключу ничего не пишет;
* журнал прогонов виден и интегратору, и владельцу в кабинете, и в нём есть
  числа ошибок, а не только «ок».
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from sqlalchemy import BigInteger, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402

import pytest  # noqa: E402


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):  # noqa: ARG001
    """В sqlite BIGINT-первичник не автоинкрементится (см. test_people_import)."""
    return "INTEGER"


from app.db.base import Base  # noqa: E402
from app.db.hr_models import Department, Employee, HrShift  # noqa: E402
from app.db.org_models import Organization  # noqa: E402
from app.services import api_ingest, api_keys, audit  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "employees",
    "departments",
    "hr_shifts",
    "api_keys",
    "api_import_runs",
    "audit_events",
)

PEOPLE_CSV = "имя;должность;подразделение\nАнна Смирнова;Официант;Зал\n"
SHIFT_CSV = "имя;дата;статус\nАнна Смирнова;21.10.2026;смена\n"


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


@pytest.fixture()
async def org(session):
    row = Organization(id=1, slug="salon-a", name="Салон А")
    session.add(row)
    await session.commit()
    return row


@pytest.fixture()
async def department(session, org):
    row = Department(name="Зал", slug="hall", is_active=True, sort_order=0)
    session.add(row)
    await session.commit()
    return row


async def _key(session, scopes: list[str]):
    key, _token = await api_keys.create(
        session, org_id=1, name="1С", scopes=scopes
    )
    await session.commit()
    return key


async def test_preview_needs_write_scope_and_writes_nothing(
    session, org, department
) -> None:
    key = await _key(session, ["people.read"])

    with pytest.raises(api_ingest.ApiIngestError) as caught:
        await api_ingest.preview(session, key=key, text=PEOPLE_CSV)
    assert str(caught.value) == "scope_required:people.write"
    assert (await session.scalars(select(Employee))).all() == []


async def test_apply_creates_people_and_logs_the_run(session, org, department) -> None:
    key = await _key(session, ["people.write"])

    data, replay = await api_ingest.apply(
        session,
        key=key,
        text=PEOPLE_CSV,
        filename="people.csv",
        idempotency_key="run-1",
    )

    assert (data["created"], replay) == (1, False)
    assert len((await session.scalars(select(Employee))).all()) == 1

    runs = await api_ingest.runs(session, org.id)
    assert len(runs) == 1
    assert (runs[0].filename, runs[0].errors, runs[0].status) == (
        "people.csv",
        0,
        "applied",
    )
    events = await audit.events(session, org.id)
    assert any(event.action == "import.api" for event in events)


async def test_repeat_with_same_idempotency_key_returns_saved_answer(
    session, org, department
) -> None:
    key = await _key(session, ["people.write"])

    first, replay_first = await api_ingest.apply(
        session, key=key, text=PEOPLE_CSV, idempotency_key="run-1"
    )
    second, replay_second = await api_ingest.apply(
        session, key=key, text=PEOPLE_CSV, idempotency_key="run-1"
    )

    assert replay_first is False and replay_second is True
    assert second == first
    # Повтор не создал второго человека и не добавил строку в журнал.
    assert len((await session.scalars(select(Employee))).all()) == 1
    assert len(await api_ingest.runs(session, org.id)) == 1


async def test_same_key_with_another_file_is_a_conflict(
    session, org, department
) -> None:
    key = await _key(session, ["people.write", "schedule.write"])
    await api_ingest.apply(session, key=key, text=PEOPLE_CSV, idempotency_key="run-1")

    with pytest.raises(api_ingest.ApiIngestError) as caught:
        await api_ingest.apply(
            session, key=key, text=SHIFT_CSV, idempotency_key="run-1"
        )
    assert str(caught.value) == "idempotency_key_reused"


async def test_shifts_need_schedule_scope_and_do_not_write_on_refusal(
    session, org, department
) -> None:
    people_key = await _key(session, ["people.write"])
    await api_ingest.apply(session, key=people_key, text=PEOPLE_CSV)

    with pytest.raises(api_ingest.ApiIngestError) as caught:
        await api_ingest.apply(session, key=people_key, text=SHIFT_CSV)
    assert str(caught.value) == "scope_required:schedule.write"
    assert (await session.scalars(select(HrShift))).all() == []

    shifts_key = await _key(session, ["schedule.write"])
    data, _replay = await api_ingest.apply(session, key=shifts_key, text=SHIFT_CSV)
    assert data["created"] == 1


async def test_runs_are_newest_first(session, org, department) -> None:
    key = await _key(session, ["people.write", "schedule.write"])
    await api_ingest.apply(session, key=key, text=PEOPLE_CSV)
    await api_ingest.apply(session, key=key, text=SHIFT_CSV)

    runs = await api_ingest.runs(session, org.id)
    assert [row.kind for row in runs] == ["shifts", "people"]


def test_ingest_routes_are_mounted() -> None:
    """Путь закреплён: `/api/v1/...` — контракт интегратора, а не внутренний."""
    from app.main import create_app
    from app.routing import iter_route_objects

    paths = {getattr(route, "path", "") for route in iter_route_objects(create_app())}
    assert "/api/v1/import/preview" in paths
    assert "/api/v1/import/apply" in paths
    assert "/api/v1/import/runs" in paths
    assert "/api/org/import-runs" in paths
