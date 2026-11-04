"""Публичный API и вебхуки организации (B2B_PLATFORM_PLAN, шаг 6.1).

Что проверяем, а не «ручка отвечает 200»:

* ключ в базе — хеш: утечка дампа не даёт доступа к API;
* отозванный ключ перестаёт работать сразу;
* ключ одной организации не видит людей другой;
* контакты не уезжают без отдельного права `contacts.read`;
* событие уходит только подписанным приёмникам и только своей организации;
* успешная доставка закрывает очередь, неудачная — планирует повтор, а после
  пятой попытки помечается проваленной, а не висит вечно;
* подпись совпадает с HMAC от тела — интегратор может проверить, что запрос
  действительно от нас;
* http и приватные адреса не принимаются: по http имена людей идут открытым
  текстом.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import date, datetime, timedelta, timezone

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import BigInteger, select  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw):  # noqa: ARG001
    return "JSON"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):  # noqa: ARG001
    return "INTEGER"


from app.api import routes_integrations, routes_v1  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import Employee, HrShift  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    ApiKey,
    Organization,
    OrganizationMember,
    WebhookDelivery,
    WebhookEndpoint,
    reset_org,
    set_org,
)
from app.services import api_keys, audit, webhooks  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "employees",
    "departments",
    "organization_members",
    "api_keys",
    "webhook_endpoints",
    "webhook_deliveries",
    "audit_events",
    "hr_shifts",
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


async def _org(session, *, org_id: int = 1, slug: str = "salon-a", name: str = "Салон А"):
    org = Organization(id=org_id, slug=slug, name=name)
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org


async def _user(session, *, user_id: int = 1, tg: int = 1001, name: str = "Анна"):
    user = User(id=user_id, telegram_id=tg, display_name=name)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _member(session, org, user, role: str = "owner"):
    row = OrganizationMember(org_id=org.id, user_id=user.id, role=role)
    session.add(row)
    await session.commit()
    return row


async def _employee(session, org, user, *, role: str = "employee", name: str | None = None):
    if name is not None:
        user.display_name = name
    token = set_org(org.id)
    try:
        row = Employee(org_id=org.id, user_id=user.id, role=role)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    finally:
        reset_org(token)
    return row


# ---------------------------------------------------------------------------
# Ключи
# ---------------------------------------------------------------------------


async def test_key_is_stored_hashed_and_resolves(session) -> None:
    org = await _org(session)
    user = await _user(session)
    key, token = await api_keys.create(
        session, org_id=org.id, name="CRM", user=user
    )
    await session.commit()

    assert token.startswith(api_keys.TOKEN_PREFIX)
    assert key.token_hash != token
    assert len(key.token_hash) == 64
    assert key.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token[:16] == key.prefix

    found = await api_keys.resolve(session, token)
    assert found is not None and found.id == key.id


async def test_revoked_key_stops_working(session) -> None:
    org = await _org(session)
    key, token = await api_keys.create(session, org_id=org.id, name="CRM")
    await session.commit()

    await api_keys.revoke(session, org.id, key.id)
    await session.commit()

    assert await api_keys.resolve(session, token) is None


async def test_scopes_are_validated_not_silently_dropped(session) -> None:
    org = await _org(session)
    with pytest.raises(api_keys.ApiKeyError):
        await api_keys.create(
            session, org_id=org.id, name="CRM", scopes=["people.read", "crm.write"]
        )
    key, _ = await api_keys.create(session, org_id=org.id, name="CRM")
    assert "people.read" in api_keys.scopes_of(key)
    # Контакты не выдаются по умолчанию: почта — персональные данные.
    assert "contacts.read" not in api_keys.scopes_of(key)


async def test_public_employees_are_scoped_and_hide_contacts(session) -> None:
    org = await _org(session)
    other = await _org(session, org_id=2, slug="salon-b", name="Салон Б")
    user = await _user(session)
    user.email = "anna@example.com"
    stranger = await _user(session, user_id=2, tg=2002, name="Борис")
    await _employee(session, org, user, name="Анна")
    await _employee(session, other, stranger, name="Борис")

    plain, _ = await api_keys.create(session, org_id=org.id, name="CRM")
    with_contacts, _ = await api_keys.create(
        session, org_id=org.id, name="CRM+", scopes=["people.read", "contacts.read"]
    )
    await session.commit()

    token = set_org(org.id)
    try:
        rows = await routes_v1.employees(
            session, plain, include_inactive=False, limit=100, offset=0
        )
        contacts = await routes_v1.employees(
            session, with_contacts, include_inactive=False, limit=100, offset=0
        )
    finally:
        reset_org(token)

    assert [row.name for row in rows] == ["Анна"]
    assert rows[0].email is None
    assert contacts[0].email == "anna@example.com"


async def test_only_owner_manages_keys(session) -> None:
    org = await _org(session)
    owner = await _user(session)
    manager = await _user(session, user_id=2, tg=2002, name="Пётр")
    await _member(session, org, owner, "owner")
    await _member(session, org, manager, "manager")

    with pytest.raises(HTTPException) as exc:
        await routes_integrations.list_api_keys(session, org, manager)
    assert exc.value.status_code == 403
    assert exc.value.detail == "owner_required"


async def test_created_key_is_audited_and_returned_once(session) -> None:
    org = await _org(session)
    owner = await _user(session)
    await _member(session, org, owner, "owner")

    created = await routes_integrations.create_api_key(
        routes_integrations.ApiKeyIn(name="CRM"), session, org, owner
    )
    assert created.token.startswith(api_keys.TOKEN_PREFIX)
    assert created.key.name == "CRM"

    stored = await session.scalar(select(ApiKey).where(ApiKey.id == created.key.id))
    assert stored is not None and stored.token_hash != created.token

    events = await audit.events(session, org.id)
    assert any(event.action == "api_key.created" for event in events)


# ---------------------------------------------------------------------------
# Вебхуки
# ---------------------------------------------------------------------------


async def test_emit_queues_only_subscribed_endpoints_of_own_org(session) -> None:
    org = await _org(session)
    other = await _org(session, org_id=2, slug="b", name="Б")
    allowed, _ = await webhooks.add_endpoint(
        session,
        org_id=org.id,
        url="https://crm.example.com/hook",
        events=["employee.created"],
    )
    await webhooks.add_endpoint(
        session,
        org_id=org.id,
        url="https://other.example.com/hook",
        events=["employee.updated"],
    )
    foreign, _ = await webhooks.add_endpoint(
        session, org_id=other.id, url="https://foreign.example.com/hook"
    )
    await session.commit()

    queued = await webhooks.emit(
        session,
        org_id=org.id,
        event="employee.created",
        data={"employee_id": 1, "name": "Анна"},
    )
    await session.commit()

    assert queued == 1
    rows = list(await session.scalars(select(WebhookDelivery)))
    assert [row.endpoint_id for row in rows] == [allowed.id]
    assert foreign.id not in {row.endpoint_id for row in rows}
    assert "Анна" in rows[0].payload


async def test_flush_marks_success_and_resets_failures(session, monkeypatch) -> None:
    org = await _org(session)
    hook, _ = await webhooks.add_endpoint(
        session, org_id=org.id, url="https://crm.example.com/hook"
    )
    hook.failures = 3
    await webhooks.emit(
        session, org_id=org.id, event="employee.created", data={"employee_id": 1}
    )
    await session.commit()

    sent: list[tuple[str, bytes, dict[str, str]]] = []

    async def ok_post(url, body, headers):
        sent.append((url, body, headers))
        return 200, None

    monkeypatch.setattr(webhooks, "_post", ok_post)
    result = await webhooks.flush(session)
    await session.commit()

    assert result == {"sent": 1, "retried": 0, "failed": 0}
    delivery = await session.scalar(select(WebhookDelivery))
    assert delivery is not None and delivery.status == "sent"
    assert delivery.response_code == 200
    assert hook.failures == 0

    url, body, headers = sent[0]
    assert url == "https://crm.example.com/hook"
    expected = "sha256=" + hmac.new(
        hook.secret.encode(), body, hashlib.sha256
    ).hexdigest()
    assert headers["X-SemiTask-Signature"] == expected
    assert headers["X-SemiTask-Event"] == "employee.created"


async def test_failed_delivery_retries_then_fails(session, monkeypatch) -> None:
    org = await _org(session)
    await webhooks.add_endpoint(
        session, org_id=org.id, url="https://crm.example.com/hook"
    )
    await webhooks.emit(
        session, org_id=org.id, event="employee.updated", data={"employee_id": 1}
    )
    await session.commit()

    async def bad_post(url, body, headers):
        return 500, None

    monkeypatch.setattr(webhooks, "_post", bad_post)
    now = datetime.now(timezone.utc)
    first = await webhooks.flush(session, now=now)
    await session.commit()
    assert first["retried"] == 1

    delivery = await session.scalar(select(WebhookDelivery))
    assert delivery is not None
    assert delivery.status == "pending" and delivery.attempts == 1
    due = delivery.next_attempt_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    assert due > now

    # Досылаем до последней попытки: повтор не может быть вечным.
    delivery.attempts = webhooks.MAX_ATTEMPTS - 1
    delivery.next_attempt_at = now
    await session.commit()
    last = await webhooks.flush(session, now=now + timedelta(minutes=1))
    await session.commit()
    assert last["failed"] == 1
    await session.refresh(delivery)
    assert delivery.status == "failed"


async def test_webhook_url_must_be_https_and_not_private(monkeypatch) -> None:
    monkeypatch.delenv("WEBHOOK_ALLOW_HTTP", raising=False)
    with pytest.raises(webhooks.WebhookError):
        webhooks.validate_url("http://crm.example.com/hook")
    with pytest.raises(webhooks.WebhookError):
        webhooks.validate_url("https://10.0.0.5/hook")
    with pytest.raises(webhooks.WebhookError):
        webhooks.validate_url("https://user:pass@crm.example.com/hook")
    assert webhooks.validate_url("https://crm.example.com/hook") == (
        "https://crm.example.com/hook"
    )

    monkeypatch.setenv("WEBHOOK_ALLOW_HTTP", "1")
    assert webhooks.validate_url("http://localhost:9000/hook") == (
        "http://localhost:9000/hook"
    )


async def test_shift_range_is_validated(session) -> None:
    org = await _org(session)
    user = await _user(session)
    employee = await _employee(session, org, user)
    key, _ = await api_keys.create(session, org_id=org.id, name="CRM")
    await session.commit()
    session.add(
        HrShift(org_id=org.id, employee_id=employee.id, day=date(2026, 11, 5))
    )
    await session.commit()

    token = set_org(org.id)
    try:
        rows = await routes_v1.shifts(
            session, key, date_from=date(2026, 11, 1), date_to=date(2026, 11, 7)
        )
        with pytest.raises(HTTPException) as exc:
            await routes_v1.shifts(
                session,
                key,
                date_from=date(2026, 1, 1),
                date_to=date(2026, 12, 31),
            )
    finally:
        reset_org(token)

    assert len(rows) == 1 and rows[0].employee_name == "Анна"
    assert exc.value.detail == "range_too_long"
