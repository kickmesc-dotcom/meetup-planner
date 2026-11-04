"""Личные подписки на уведомления (жалоба владельца 04.11.2026).

Проверяем главное обещание: автоматическое сообщение в личку уходит только
тем, кто явно его включил, а у самого сообщения есть кнопка «Отключить» и
кнопка в настройки.

Без этих проверок «выключено по умолчанию» — это строчка в коде, которую
следующая правка рассылки случайно обойдёт.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone

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


from app.bot import notify_buttons  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import Employee  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.org_models import Organization  # noqa: E402
from app.services import hr_digest, hr_reminders, notify_prefs  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "employees",
    "notify_prefs",
    "admin_config",
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


async def _org(session, org_id: int = 1):
    org = Organization(id=org_id, slug="salon-a", name="Салон А")
    session.add(org)
    await session.commit()
    return org


async def _manager(session, org, *, user_id: int = 1, tg: int = 1001):
    user = User(id=user_id, telegram_id=tg, display_name="Анна")
    session.add(user)
    await session.commit()
    employee = Employee(org_id=org.id, user_id=user.id, role="aup")
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    return user, employee


async def test_all_kinds_are_off_by_default(session) -> None:
    org = await _org(session)
    user, _ = await _manager(session, org)

    for kind in notify_prefs.KINDS:
        assert (
            await notify_prefs.get(
                session, org_id=org.id, user_id=user.id, kind=kind
            )
            is False
        )
    assert await notify_prefs.snapshot(
        session, org_id=org.id, user_id=user.id
    ) == {"digest": False}


async def test_enable_is_idempotent_and_reversible(session) -> None:
    org = await _org(session)
    user, _ = await _manager(session, org)

    for _ in range(2):
        assert (
            await notify_prefs.set_enabled(
                session, org_id=org.id, user_id=user.id, kind="digest", enabled=True
            )
            is True
        )
    await session.commit()
    assert await notify_prefs.subscribers(
        session, org_id=org.id, kind="digest"
    ) == {user.id}

    await notify_prefs.set_enabled(
        session, org_id=org.id, user_id=user.id, kind="digest", enabled=False
    )
    await session.commit()
    assert await notify_prefs.subscribers(session, org_id=org.id, kind="digest") == set()


async def test_unknown_kind_is_rejected(session) -> None:
    org = await _org(session)
    user, _ = await _manager(session, org)
    with pytest.raises(notify_prefs.NotifyPrefError):
        await notify_prefs.set_enabled(
            session, org_id=org.id, user_id=user.id, kind="news", enabled=True
        )


async def test_subscriptions_are_per_org(session) -> None:
    first = await _org(session, 1)
    second = Organization(id=2, slug="salon-b", name="Салон Б")
    session.add(second)
    await session.commit()
    user, _ = await _manager(session, first)

    await notify_prefs.set_enabled(
        session, org_id=first.id, user_id=user.id, kind="digest", enabled=True
    )
    await session.commit()

    assert await notify_prefs.get(
        session, org_id=second.id, user_id=user.id, kind="digest"
    ) is False


async def test_message_has_off_and_settings_buttons() -> None:
    enabled = notify_buttons.keyboard("digest", enabled=True).inline_keyboard[0]
    assert enabled[0].callback_data == "np:digest:off"
    assert enabled[1].web_app is not None

    disabled = notify_buttons.keyboard("digest", enabled=False).inline_keyboard[0]
    assert disabled[0].callback_data == "np:digest:on"


async def test_digest_skips_unsubscribed_and_sends_to_subscribed(session, monkeypatch) -> None:
    org = await _org(session)
    user, employee = await _manager(session, org)

    async def fake_managers(_session):
        return [employee]

    async def fake_tg(_session, _managers):
        return {int(user.id): 777}

    async def fake_build(_session, _employee, today=None):
        return hr_digest.Digest(
            day=today or date(2026, 11, 4),
            overdue_tasks=0,
            overdue_titles=(),
            planned_today=0,
            not_started=0,
            open_runs=0,
            problems_open=0,
            problems_attention=0,
        )

    class FakeBot:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def send_message(self, **kwargs):
            self.calls.append(kwargs)

    monkeypatch.setattr(hr_reminders, "managers", fake_managers)
    monkeypatch.setattr(hr_digest, "_manager_tg_ids", fake_tg)
    monkeypatch.setattr(hr_digest, "build", fake_build)

    bot = FakeBot()
    quiet = await hr_digest.send_morning(
        session,
        bot=bot,
        now=datetime(2026, 11, 4, 8, 30, tzinfo=timezone.utc),
        app_url="https://example.com",
        force=True,
    )
    assert quiet == 0
    assert bot.calls == []

    await notify_prefs.set_enabled(
        session, org_id=org.id, user_id=user.id, kind="digest", enabled=True
    )
    await session.commit()

    sent = await hr_digest.send_morning(
        session,
        bot=bot,
        now=datetime(2026, 11, 4, 8, 30, tzinfo=timezone.utc),
        app_url="https://example.com",
        force=True,
    )
    assert sent == 1
    assert bot.calls[0]["chat_id"] == 777
    markup = bot.calls[0]["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == "np:digest:off"
