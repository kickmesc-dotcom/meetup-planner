"""Web push: подписка устройства и доставка без Telegram (шаг 2.4).

Проверяем свойства, без которых канал бесполезен или опасен:

* подписка одна на браузер: повторная не плодит дубли, а обновляет ключи;
* общий браузер перепривязывается к новому аккаунту, а не шлёт чужое;
* отписка удаляет только свою подписку;
* мёртвая подписка (410) удаляется сразу — иначе каждая отправка тратила бы
  время на устройство, которого больше нет;
* письмо уходит только по важным событиям и только тем, у кого нет push:
  дубль в два канала человек отключает целиком.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.api import routes_push  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import Employee  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.db.push_models import PushSubscription  # noqa: E402
from app.services import hr_notify, hr_reminders, mail, web_push  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "employees",
    "push_subscriptions",
)

ENDPOINT = "https://push.example.com/send/abcdef123456"


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


@pytest.fixture(autouse=True)
def push_keys(monkeypatch):
    """Ключи «настроены»: иначе сервис честно молчит и ничего не проверить."""
    monkeypatch.setattr(web_push, "enabled", lambda: True)


async def _person(session, *, user_id: int = 1, email: str | None = None):
    if await session.get(Organization, DEFAULT_ORG_ID) is None:
        session.add(Organization(id=DEFAULT_ORG_ID, slug="default", name="Моя"))
    user = User(
        id=user_id,
        telegram_id=900_000 + user_id,
        display_name=f"Человек {user_id}",
        email=email,
    )
    employee = Employee(id=user_id, user_id=user_id, org_id=DEFAULT_ORG_ID)
    session.add_all([user, employee])
    await session.commit()
    return user, employee


def _sub(user_id: int = 1, endpoint: str = ENDPOINT) -> PushSubscription:
    return PushSubscription(
        org_id=DEFAULT_ORG_ID,
        user_id=user_id,
        endpoint=endpoint,
        endpoint_hash=web_push.endpoint_hash(endpoint),
        p256dh="key",
        auth="auth",
    )


# --------------------------------------------------------------------------
# Подписка
# --------------------------------------------------------------------------


def test_endpoint_hash_is_stable_and_hides_url() -> None:
    digest = web_push.endpoint_hash(ENDPOINT)
    assert digest == web_push.endpoint_hash(ENDPOINT)
    assert len(digest) == 64
    assert "push.example.com" not in digest


async def test_subscribe_is_idempotent_and_rebinds_device(session) -> None:
    _, first = await _person(session, user_id=1)
    _, second = await _person(session, user_id=2)
    body = routes_push.PushSubscribeIn(
        endpoint=ENDPOINT,
        keys={"p256dh": "k1", "auth": "a1"},
        user_agent="Chrome",
    )

    await routes_push.subscribe_push(body, session, first)
    await routes_push.subscribe_push(body, session, first)
    rows = (await session.scalars(select(PushSubscription))).all()
    assert len(rows) == 1
    assert rows[0].user_id == 1

    # Тот же браузер, другой аккаунт: прежний владелец не должен получать
    # уведомления чужой смены.
    await routes_push.subscribe_push(body, session, second)
    rows = (await session.scalars(select(PushSubscription))).all()
    assert len(rows) == 1
    assert rows[0].user_id == 2


async def test_unsubscribe_removes_only_own_device(session) -> None:
    _, first = await _person(session, user_id=1)
    _, second = await _person(session, user_id=2)
    session.add_all([_sub(1, ENDPOINT), _sub(2, ENDPOINT + "x")])
    await session.commit()

    await routes_push.unsubscribe_push(
        routes_push.PushUnsubscribeIn(endpoint=ENDPOINT), session, first
    )
    rows = (await session.scalars(select(PushSubscription))).all()
    assert [row.user_id for row in rows] == [2]
    # Повторная отписка ошибкой не считается: кнопка может нажаться дважды.
    await routes_push.unsubscribe_push(
        routes_push.PushUnsubscribeIn(endpoint=ENDPOINT), session, first
    )


# --------------------------------------------------------------------------
# Отправка
# --------------------------------------------------------------------------


async def test_send_deletes_gone_subscription(session, monkeypatch) -> None:
    await _person(session)
    alive = _sub(1, ENDPOINT)
    dead = _sub(1, ENDPOINT + "dead")
    session.add_all([alive, dead])
    await session.commit()

    def fake_send(sub, payload):  # noqa: ANN001
        return 410 if sub.endpoint.endswith("dead") else None

    monkeypatch.setattr(web_push, "_send_one", fake_send)
    subs = (await session.scalars(select(PushSubscription))).all()
    sent = await web_push.send(
        session, subscriptions=list(subs), title="T", body="B"
    )
    await session.commit()

    assert sent == 1
    left = (await session.scalars(select(PushSubscription))).all()
    assert [row.endpoint for row in left] == [ENDPOINT]
    assert left[0].last_seen_at is not None


async def test_send_is_noop_without_keys(session, monkeypatch) -> None:
    await _person(session)
    session.add(_sub())
    await session.commit()
    monkeypatch.setattr(web_push, "enabled", lambda: False)
    assert await web_push.send(
        session,
        subscriptions=(await session.scalars(select(PushSubscription))).all(),
        title="T",
        body="B",
    ) == 0


# --------------------------------------------------------------------------
# Канал доставки: push или письмо, но не оба
# --------------------------------------------------------------------------


async def test_deliver_external_emails_only_uncovered(session, monkeypatch) -> None:
    user_a, _ = await _person(session, user_id=1, email="a@example.com")
    user_b, employee_b = await _person(session, user_id=2, email="b@example.com")
    employee_a = await session.get(Employee, 1)
    session.add(_sub(1))
    await session.commit()

    push = AsyncMock(return_value=1)
    monkeypatch.setattr(web_push, "send", push)
    send_mail = AsyncMock()
    monkeypatch.setattr(mail, "send", send_mail)

    await hr_reminders.deliver_external(
        session,
        recipients=[employee_a, employee_b],
        kind=hr_notify.KIND_TASK_DEADLINE,
        text="Срок через час",
        payload={"task_id": 5},
    )

    assert push.await_count == 1
    assert send_mail.await_count == 1
    assert send_mail.await_args.args[0].to == "b@example.com"
    assert user_a.email == "a@example.com" and user_b.email == "b@example.com"


async def test_deliver_external_skips_email_for_unimportant(session, monkeypatch) -> None:
    await _person(session)
    employee = await session.get(Employee, 1)
    monkeypatch.setattr(web_push, "send", AsyncMock(return_value=0))
    send_mail = AsyncMock()
    monkeypatch.setattr(mail, "send", send_mail)

    await hr_reminders.deliver_external(
        session,
        recipients=[employee],
        kind=hr_notify.KIND_TASK_ASSIGNED,
        text="Новое поручение",
    )
    assert send_mail.await_count == 0


async def test_push_body_is_single_line_and_bounded() -> None:
    body = hr_reminders._push_body("строка\n\nвторая " + "х" * 300)
    assert "\n" not in body
    assert len(body) <= 180
    assert body.endswith("…")
