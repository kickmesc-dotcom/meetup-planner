"""«Смена началась, чек-лист не открыт» — push, который ведёт в смену.

Проверяем свойства, без которых напоминание вредное:

* будим только того, у кого смена по графику уже идёт;
* не будим того, кто открыл чек-лист, и тестовый/теневой пул;
* повторный тик в тот же день не присылает второе сообщение — иначе напоминание
  каждые 15 минут;
* тап по push ведёт в чек-лист, а не в корень приложения.

Env выставляем до импорта настроек: `Settings` требует BOT_TOKEN и прочее.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from datetime import UTC, datetime, time  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy import BigInteger  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN202
    """JSONB в тестовой sqlite: `app_notifications.payload` боевой схемы."""
    return "JSON"


@compiles(BigInteger, "sqlite")
def _bigint_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN202
    """BigInteger → INTEGER: иначе sqlite не делает автоинкремент для id."""
    return "INTEGER"

from app.db import models as _models  # noqa: E402,F401 — регистрирует `users`
from app.db.base import Base  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ROLE_EMPLOYEE,
    RUN_IN_PROGRESS,
    SHIFT_PLANNED,
    ChecklistRun,
    Employee,
    HrShift,
)
from app.db.models import AppNotification, User  # noqa: E402
from app.services import hr_notify, hr_reminders, web_push  # noqa: E402
from app.config import get_settings  # noqa: E402

TABLES = [
    # organizations/users — не для проверок, а для FK у `employees` и уведомлений.
    "organizations",
    "users",
    "departments",
    "halls",
    "employees",
    "hr_shifts",
    "checklist_templates",
    "checklist_runs",
    "app_notifications",
    "admin_config",
    "notify_prefs",
    "push_subscriptions",
]

TZ = ZoneInfo(get_settings().scheduler_tz)
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
DAY = NOW.astimezone(TZ).date()


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
def no_push(monkeypatch):
    """По умолчанию устройств нет: проверяем записи в приложении, а не канал."""
    monkeypatch.setattr(
        web_push, "subscriptions_for", AsyncMock(return_value=[])
    )


async def _employee(session, *, employee_id: int, is_simulation: bool = False) -> Employee:
    session.add(
        User(id=employee_id, telegram_id=900000 + employee_id, display_name="Тест")
    )
    employee = Employee(
        id=employee_id,
        user_id=employee_id,
        role=ROLE_EMPLOYEE,
        is_active=True,
        is_simulation=is_simulation,
    )
    session.add(employee)
    await session.flush()
    return employee


async def _shift(session, employee, *, starts_at: time = time(0, 0)) -> None:
    session.add(
        HrShift(
            employee_id=employee.id,
            day=DAY,
            status=SHIFT_PLANNED,
            starts_at=starts_at,
        )
    )


async def _notified(session) -> list[AppNotification]:
    return list(
        (
            await session.scalars(
                select(AppNotification).where(
                    AppNotification.kind == hr_notify.KIND_SHIFT_START
                )
            )
        ).all()
    )


async def test_reminds_employee_with_running_shift(session) -> None:
    employee = await _employee(session, employee_id=1)
    await _shift(session, employee)
    await session.commit()

    sent = await hr_reminders.send_shift_start_reminders(session, now=NOW)

    assert sent == [int(employee.id)]
    rows = await _notified(session)
    assert len(rows) == 1
    assert rows[0].user_id == employee.user_id
    # Текст говорит, что делать, а не констатирует факт.
    assert "чек-лист" in rows[0].text


async def test_second_tick_same_day_is_silent(session) -> None:
    employee = await _employee(session, employee_id=1)
    await _shift(session, employee)
    await session.commit()

    assert await hr_reminders.send_shift_start_reminders(session, now=NOW) == [1]

    again = await hr_reminders.send_shift_start_reminders(
        session, now=NOW.replace(hour=13)
    )

    assert again == []
    assert len(await _notified(session)) == 1


async def test_started_checklist_is_not_reminded(session) -> None:
    employee = await _employee(session, employee_id=1)
    await _shift(session, employee)
    session.add(
        ChecklistRun(
            employee_id=employee.id,
            template_id=1,
            shift_date=DAY,
            status=RUN_IN_PROGRESS,
        )
    )
    await session.commit()

    assert await hr_reminders.send_shift_start_reminders(session, now=NOW) == []
    assert await _notified(session) == []


async def test_shift_that_has_not_started_is_not_reminded(session) -> None:
    employee = await _employee(session, employee_id=1)
    await _shift(session, employee, starts_at=time(23, 30))
    await session.commit()

    assert await hr_reminders.send_shift_start_reminders(session, now=NOW) == []


async def test_simulation_pool_is_not_reminded(session) -> None:
    demo = await _employee(session, employee_id=2, is_simulation=True)
    await _shift(session, demo)
    await session.commit()

    assert await hr_reminders.send_shift_start_reminders(session, now=NOW) == []


async def test_push_leads_to_checklist(monkeypatch) -> None:
    """Тап по уведомлению открывает смену, а не ленту событий."""
    monkeypatch.setattr(
        web_push, "subscriptions_for", AsyncMock(return_value=[object()])
    )
    send = AsyncMock(return_value=1)
    monkeypatch.setattr(web_push, "send", send)
    employee = Employee(
        id=1, user_id=1, role=ROLE_EMPLOYEE, is_active=True, is_simulation=False
    )

    await hr_reminders.deliver_external(
        None,
        recipients=[employee],
        kind=hr_notify.KIND_SHIFT_START,
        text="Смена не начата",
    )

    assert send.await_count == 1
    assert send.await_args.kwargs["url"] == "/?open=checklist"
