"""Лимиты частоты и квоты организации (B2B_PLATFORM_PLAN, шаг 5.3).

Зачем тесты. Здесь два обещания, которые легко сломать незаметно: лимит считает
ОРГАНИЗАЦИЮ (а не адрес и не весь контур), и квота хранилища считается по своей
организации. Ещё три вещи ломаются тихо: двойное списание в одном запросе,
старый тариф из кэша после оплаты и «лимит сам стал отказом» при недоступной
базе.

Env выставляем ДО импорта моделей — `Settings` требует BOT_TOKEN и т.п.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
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


from app.api import routes_media  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import MediaBlob  # noqa: E402
from app.db.org_models import (  # noqa: E402
    ALL_ORGS,
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.services import billing, hr_media, org_limits  # noqa: E402

TABLES = ("organizations", "media_blobs")


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
def clean_context():
    """Пустые счётчики и первый тенант в контексте — как в остальных тестах."""
    org_limits.reset_org_limits()
    token = set_org(DEFAULT_ORG_ID)
    yield
    reset_org(token)
    org_limits.reset_org_limits()


async def _org(session, *, org_id: int = DEFAULT_ORG_ID, plan: str = "trial") -> Organization:
    org = Organization(id=org_id, slug=f"org-{org_id}", name=f"Клиент {org_id}", plan=plan)
    session.add(org)
    await session.commit()
    return org


# --- каталог ---------------------------------------------------------------


def test_plans_carry_rate_and_storage_limits() -> None:
    """Потолки живут в тарифе и растут вместе с ним — это обещание витрины."""
    limits = [(p.api_rpm, p.storage_mb) for p in billing.payable_plans()]
    assert limits == sorted(limits)
    assert billing.PLANS["trial"].api_rpm == org_limits.FALLBACK_RPM
    assert billing.PLANS["trial"].storage_mb < billing.PLANS["business"].storage_mb


# --- частота ---------------------------------------------------------------


async def test_rate_limit_counts_per_org(session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Одна организация упёрлась — вторая работает: изоляция и есть цель шага."""
    monkeypatch.setitem(
        billing.PLANS, "trial", billing.Plan("trial", "Пробный", seats=10, branches=5, api_rpm=3, trial=True)
    )
    await _org(session, org_id=1, plan="trial")
    await _org(session, org_id=2, plan="business")

    for _ in range(3):
        org_limits.begin_request()
        await org_limits.enforce_rate(session, 1)

    org_limits.begin_request()
    with pytest.raises(HTTPException) as caught:
        await org_limits.enforce_rate(session, 1)
    assert caught.value.status_code == 429
    assert caught.value.detail.startswith("org_rate_limited:")

    # Второму клиенту отказ первого не передаётся.
    org_limits.begin_request()
    await org_limits.enforce_rate(session, 2)


async def test_429_carries_retry_and_limit_headers(session) -> None:
    await _org(session, plan="trial")
    limit = billing.PLANS["trial"].api_rpm
    for _ in range(limit):
        org_limits.begin_request()
        await org_limits.enforce_rate(session, DEFAULT_ORG_ID)

    org_limits.begin_request()
    with pytest.raises(HTTPException) as caught:
        await org_limits.enforce_rate(session, DEFAULT_ORG_ID)
    headers = caught.value.headers or {}
    assert int(headers["Retry-After"]) >= 1
    assert headers["X-RateLimit-Limit"] == str(limit)
    assert headers["X-RateLimit-Remaining"] == "0"


async def test_one_request_is_charged_once(session) -> None:
    """Пользователь и сотрудник резолвятся в одном запросе — счёт один."""
    await _org(session, plan="trial")
    limit = billing.PLANS["trial"].api_rpm
    # Каждый «запрос» — это begin_request и ДВА вызова enforce_rate
    # (сначала пользователь, затем сотрудник). Двойное списание упёрлось
    # бы в потолок уже на 151-м запросе; одинарное — ровно на 301-м.
    for _ in range(limit):
        org_limits.begin_request()
        await org_limits.enforce_rate(session, DEFAULT_ORG_ID)
        await org_limits.enforce_rate(session, DEFAULT_ORG_ID)

    org_limits.begin_request()
    with pytest.raises(HTTPException):
        await org_limits.enforce_rate(session, DEFAULT_ORG_ID)


async def test_quota_can_be_switched_off(session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Нагрузочная проба: лимит не должен мешать мерить."""
    await _org(session, plan="trial")
    monkeypatch.setenv("ORG_QUOTA_OFF", "1")
    for _ in range(billing.PLANS["trial"].api_rpm * 3):
        org_limits.begin_request()
        await org_limits.enforce_rate(session, DEFAULT_ORG_ID)


async def test_unknown_org_and_all_orgs_are_skipped(session) -> None:
    """Без организации считать нечего; платформенный обход — не клиентский трафик."""
    org_limits.begin_request()
    await org_limits.enforce_rate(session, None)
    org_limits.begin_request()
    await org_limits.enforce_rate(session, ALL_ORGS)


async def test_plan_cache_and_forget(session) -> None:
    """После оплаты новый потолок применяется сразу, а не через минуту."""
    org = await _org(session, plan="trial")
    assert await org_limits.plan_code(session, org.id) == "trial"
    org.plan = "network"
    await session.commit()
    # Минутный кэш ещё держит старый тариф — это осознанная плата за отсутствие
    # SELECT на каждом запросе.
    assert await org_limits.plan_code(session, org.id) == "trial"
    org_limits.forget_plan(org.id)
    assert await org_limits.plan_code(session, org.id) == "network"
    assert org_limits.rpm_for("network") > org_limits.rpm_for("trial")


async def test_unreadable_plan_falls_back_instead_of_refusing(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Лимит не должен сам становиться отказом при недоступной базе."""
    await _org(session, plan="trial")

    async def boom(_org_id: int):  # noqa: ANN202 - подмена метода
        raise RuntimeError("db down")

    monkeypatch.setattr(session, "get", boom)
    assert await org_limits.plan_code(session, DEFAULT_ORG_ID) is None
    org_limits.begin_request()
    await org_limits.enforce_rate(session, DEFAULT_ORG_ID)


# --- квота хранилища -------------------------------------------------------


async def _blob(session, *, org_id: int, size: int, tag: str) -> MediaBlob:
    blob = MediaBlob(org_id=org_id, sha256=tag * 64, size=size, data=b"x", mime="image/jpeg")
    session.add(blob)
    await session.commit()
    return blob


async def test_storage_counts_only_own_org(session) -> None:
    await _org(session, org_id=1, plan="trial")
    await _org(session, org_id=2, plan="trial")
    await _blob(session, org_id=1, size=1000, tag="a")
    await _blob(session, org_id=2, size=5000, tag="b")

    assert await org_limits.storage_used(session, 1) == 1000
    assert await org_limits.storage_used(session, 2) == 5000


async def test_storage_full_raises_before_write(session) -> None:
    await _org(session, plan="trial")
    limit = billing.PLANS["trial"].storage_mb * 1024 * 1024
    await _blob(session, org_id=DEFAULT_ORG_ID, size=limit, tag="a")

    with pytest.raises(org_limits.QuotaExceeded) as caught:
        await org_limits.ensure_storage(session, DEFAULT_ORG_ID, 1)
    assert caught.value.used_bytes == limit


async def test_upload_maps_storage_full_to_413(session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Клиент должен увидеть «место кончилось», а не «битый файл»."""
    async def full(_session, _upload):  # noqa: ANN001, ANN202 - подмена
        raise hr_media.MediaError("storage_full")

    monkeypatch.setattr(hr_media, "store_upload", full)
    with pytest.raises(HTTPException) as caught:
        await routes_media.upload_media(session=session, employee=None, file=None)
    assert caught.value.status_code == 413
    assert caught.value.detail == "storage_full"
