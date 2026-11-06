"""Свой домен организации (06.11.2026).

Проверяем ровно те обещания, которые легко сломать следующей правкой:
домен нормализуется, платформенный адрес и IP занять нельзя, чужой домен
не отобрать, а без файла с токеном контроль не подтверждается.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import httpx  # noqa: E402
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
from app.db.org_models import Organization  # noqa: E402
from app.services import domains  # noqa: E402


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    tables = [Base.metadata.tables["organizations"]]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


async def _org(session, slug: str = "salon-a", org_id: int = 1) -> Organization:
    org = Organization(id=org_id, slug=slug, name=f"Салон {slug}")
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org


def test_normalizes_what_owner_pastes() -> None:
    assert domains.normalize("  Salon.RU.  ") == "salon.ru"
    assert domains.normalize("https://cabinet.salon.ru/login?x=1") == "cabinet.salon.ru"
    # IDN: человек вводит кириллицей, в базу уходит punycode.
    puny = domains.normalize("салон.рф")
    assert puny.endswith(".xn--p1ai") and puny.isascii()


@pytest.mark.parametrize(
    "value",
    ["", "localhost", "192.168.1.1", "salon", "-salon.ru", "salon..ru", "salon.ru:8080"],
)
def test_rejects_non_domains(value: str) -> None:
    with pytest.raises(domains.DomainError):
        domains.normalize(value)


def test_platform_addresses_are_reserved() -> None:
    for value in ["semitaskbot.pages.dev", "app.amvera.tech"]:
        with pytest.raises(domains.DomainError) as caught:
            domains.normalize(value)
        assert str(caught.value) == "domain_reserved"


async def test_set_keeps_domain_and_issues_token(session) -> None:
    org = await _org(session)

    row = await domains.set_domain(session, org, "https://Cabinet.Salon.RU/")

    assert row.domain == "cabinet.salon.ru"
    assert row.token and row.verified is False
    assert row.verify_path == "/.well-known/semitask-domain.txt"


async def test_foreign_domain_cannot_be_taken(session) -> None:
    first = await _org(session, "a", 1)
    second = await _org(session, "b", 2)
    await domains.set_domain(session, first, "cabinet.salon.ru")

    with pytest.raises(domains.DomainError) as caught:
        await domains.set_domain(session, second, "cabinet.salon.ru")
    assert str(caught.value) == "domain_taken"


async def test_verify_accepts_file_with_token(session) -> None:
    org = await _org(session)
    row = await domains.set_domain(session, org, "cabinet.salon.ru")

    async def fetch(url: str) -> str:
        assert url == "https://cabinet.salon.ru/.well-known/semitask-domain.txt"
        return f"# proof\nsemitask-domain={row.token}\n"

    checked = await domains.verify_domain(session, org, fetch=fetch)

    assert checked.verified is True
    assert checked.checked_at is not None


async def test_verify_rejects_other_token(session) -> None:
    org = await _org(session)
    await domains.set_domain(session, org, "cabinet.salon.ru")

    async def fetch(_url: str) -> str:
        return "semitask-domain=чужой-токен"

    with pytest.raises(domains.DomainError) as caught:
        await domains.verify_domain(session, org, fetch=fetch)
    assert str(caught.value) == "verify_mismatch"


async def test_verify_reports_unreachable_domain(session) -> None:
    org = await _org(session)
    await domains.set_domain(session, org, "cabinet.salon.ru")

    async def fetch(_url: str) -> str:
        raise httpx.ConnectError("no route")

    with pytest.raises(domains.DomainError) as caught:
        await domains.verify_domain(session, org, fetch=fetch)
    assert str(caught.value) == "verify_failed"


async def test_changing_domain_resets_proof(session) -> None:
    org = await _org(session)
    row = await domains.set_domain(session, org, "cabinet.salon.ru")

    async def fetch(_url: str) -> str:
        return f"semitask-domain={row.token}"

    await domains.verify_domain(session, org, fetch=fetch)
    changed = await domains.set_domain(session, org, "new.salon.ru")

    assert changed.verified is False
    assert changed.token != row.token


async def test_clear_removes_domain(session) -> None:
    org = await _org(session)
    await domains.set_domain(session, org, "cabinet.salon.ru")

    row = await domains.clear(session, org)

    assert row.domain is None
    assert row.token is None
