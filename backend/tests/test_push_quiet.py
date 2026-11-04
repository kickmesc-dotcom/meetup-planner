"""Push вне Telegram: тихие часы, частота и ссылка (MOBILE_PARALLEL, M3).

Проверяем не «отправка вызвана», а правила, без которых канал выключают:

* в ночном окне push не уходит, уведомление в приложении остаётся;
* проверочный push человек запросил сам — тихие часы его не держат;
* одинаковый `tag` одному человеку не чаще раза в полчаса (иначе пять
  напоминаний об одной задаче читаются как спам);
* ссылка в payload ведёт на задачи, а не в корень.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy import BigInteger  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):  # noqa: ARG001
    return "INTEGER"


from app.db.base import Base  # noqa: E402
from app.db.push_models import PushSubscription  # noqa: E402
from app.services import web_push  # noqa: E402

TABLES = ("organizations", "users", "push_subscriptions")
ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"


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
async def sub(session):
    row = PushSubscription(
        org_id=1,
        user_id=1,
        endpoint=ENDPOINT,
        endpoint_hash=web_push.endpoint_hash(ENDPOINT),
        p256dh="key",
        auth="auth",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@pytest.fixture(autouse=True)
def _push_on(monkeypatch):
    web_push.reset_state()
    monkeypatch.setattr(web_push, "enabled", lambda: True)
    sent: list[str] = []

    def fake_send_one(_sub, payload):
        sent.append(payload)
        return None

    monkeypatch.setattr(web_push, "_send_one", fake_send_one)
    yield sent
    web_push.reset_state()


NIGHT = datetime(2026, 11, 4, 2, 30, tzinfo=UTC)
DAY = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


async def test_quiet_hours_hold_push_until_morning(session, sub, _push_on) -> None:
    sent = await web_push.send(
        session,
        subscriptions=[sub],
        title="Напоминание",
        body="Срок сегодня",
        tag="deadline:1",
        now=NIGHT,
    )

    assert sent == 0
    assert _push_on == []


async def test_test_push_ignores_quiet_hours(session, sub, _push_on) -> None:
    sent = await web_push.send(
        session,
        subscriptions=[sub],
        title="Проверка",
        body="Уведомления включены",
        tag="push-test",
        respect_quiet=False,
        now=NIGHT,
    )

    assert sent == 1
    assert len(_push_on) == 1


async def test_same_tag_is_not_repeated_within_half_an_hour(
    session, sub, _push_on
) -> None:
    first = await web_push.send(
        session,
        subscriptions=[sub],
        title="Просрочено",
        body="Задача 1",
        tag="overdue:1",
        now=DAY,
    )
    again = await web_push.send(
        session,
        subscriptions=[sub],
        title="Просрочено",
        body="Задача 1",
        tag="overdue:1",
        now=DAY.replace(minute=10),
    )

    assert (first, again) == (1, 0)
    assert len(_push_on) == 1


async def test_other_tag_still_delivers(session, sub, _push_on) -> None:
    await web_push.send(
        session,
        subscriptions=[sub],
        title="Просрочено",
        body="Задача 1",
        tag="overdue:1",
        now=DAY,
    )
    other = await web_push.send(
        session,
        subscriptions=[sub],
        title="Просрочено",
        body="Задача 2",
        tag="overdue:2",
        now=DAY.replace(minute=5),
    )

    assert other == 1
    assert len(_push_on) == 2


def test_payload_url_is_checked() -> None:
    """Ссылка-диплинк попадает в payload как есть: её разбирает клиент."""
    payload = web_push.PushPayload(
        title="Напоминание", body="Срок", url="/?task=42", tag="deadline:42"
    ).as_json()
    assert '"/?task=42"' in payload
