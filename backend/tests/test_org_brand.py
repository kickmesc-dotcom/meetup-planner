"""Бренд организации (B2B_PLATFORM_PLAN, фаза 4, шаг 4.4).

Что проверяем, а не «ручка отвечает 200»:

* без настроек клиент видит имя организации, а не бренд платформы;
* цвет нормализуется (`#ABC` → `#aabbcc`), иначе сравнение «изменился ли
  бренд» врёт, а в базе копятся разные написания одного цвета;
* логотип только `https`: `javascript:` в поле — это не картинка, а дыра;
* сброс возвращает имя организации, а не пустой заголовок;
* бренд одной организации не протекает во вторую.

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


from app.api import routes_orgs  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.services import brand  # noqa: E402

TABLES = ("organizations", "users", "employees", "departments", "org_invitations")


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


async def _org(session, *, name: str = "Салон А", slug: str = "salon-a") -> Organization:
    org = Organization(id=DEFAULT_ORG_ID, slug=slug, name=name)
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org


async def test_plain_org_shows_its_own_name_not_the_platform(session) -> None:
    """Пока бренд не настроен, клиент видит имя своей организации."""
    org = await _org(session)

    out = await routes_orgs.current_brand(org)

    assert out.name == "Салон А"
    assert out.color == brand.DEFAULT_COLOR
    assert out.logo_url is None
    assert out.is_custom is False


async def test_color_is_normalized_and_brand_marked_custom(session) -> None:
    """`#ABC` и `#aabbcc` — один цвет; в базе должен остаться один вид."""
    org = await _org(session)

    out = await routes_orgs.update_brand(
        routes_orgs.BrandPatch(
            name="  Студия   Ножницы ",
            color="#ABC",
            logo_url="https://cdn.example.com/logo.png",
        ),
        session,
        org,
        None,  # type: ignore[arg-type]  # зависимость проверяется отдельно
    )

    # Двойные пробелы схлопнуты: имя показывается в заголовке, и «Студия
    # Ножницы» с лишними пробелами читается как опечатка.
    assert out.name == "Студия Ножницы"
    assert out.color == "#aabbcc"
    assert out.logo_url == "https://cdn.example.com/logo.png"
    assert out.is_custom is True

    await session.refresh(org)
    assert org.brand_color == "#aabbcc"


@pytest.mark.parametrize(
    ("color", "logo"),
    [
        ("красный", None),
        ("#12", None),
        ("#1c6fb8", "javascript:alert(1)"),
        ("#1c6fb8", "http://cdn.example.com/logo.png"),
        ("#1c6fb8", "https://"),
        ("#1c6fb8", "data:image/png;base64,AAAA"),
    ],
)
async def test_bad_color_and_logo_are_rejected(session, color, logo) -> None:
    """Цвет — CSS-цвет, логотип — https-адрес. Иначе это не бренд, а дыра."""
    org = await _org(session)

    with pytest.raises(HTTPException) as exc:
        await routes_orgs.update_brand(
            routes_orgs.BrandPatch(name="Салон", color=color, logo_url=logo),
            session,
            org,
            None,  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 400
    assert exc.value.detail in {"bad_color", "bad_logo"}


async def test_empty_name_is_rejected_but_logo_can_be_cleared(session) -> None:
    """Пустое имя — забытое поле; пустой логотип — осознанный сброс."""
    org = await _org(session)
    await routes_orgs.update_brand(
        routes_orgs.BrandPatch(name="Студия", logo_url="https://cdn.example.com/a.png"),
        session,
        org,
        None,  # type: ignore[arg-type]
    )

    with pytest.raises(HTTPException) as exc:
        await routes_orgs.update_brand(
            routes_orgs.BrandPatch(name="   "), session, org, None  # type: ignore[arg-type]
        )
    assert exc.value.detail == "bad_name"

    cleared = await routes_orgs.update_brand(
        routes_orgs.BrandPatch(logo_url=""), session, org, None  # type: ignore[arg-type]
    )
    assert cleared.logo_url is None
    assert cleared.name == "Студия"


async def test_reset_returns_the_organization_name(session) -> None:
    """Сброс бренда не оставляет клиента с пустым заголовком."""
    org = await _org(session)
    await routes_orgs.update_brand(
        routes_orgs.BrandPatch(name="Студия", color="#112233"),
        session,
        org,
        None,  # type: ignore[arg-type]
    )

    out = await routes_orgs.reset_brand(session, org, None)  # type: ignore[arg-type]

    assert out.name == "Салон А"
    assert out.color == brand.DEFAULT_COLOR
    assert out.is_custom is False


async def test_brand_of_one_org_does_not_leak_into_another(session) -> None:
    """Две организации — два бренда: ручка берёт `org` из запроса, не из id."""
    first = await _org(session, name="Салон А", slug="salon-a")
    second = Organization(id=2, slug="salon-b", name="Салон Б")
    session.add(second)
    await session.commit()
    await session.refresh(second)
    await routes_orgs.update_brand(
        routes_orgs.BrandPatch(name="Ножницы"), session, first, None  # type: ignore[arg-type]
    )

    assert (await routes_orgs.current_brand(first)).name == "Ножницы"
    assert (await routes_orgs.current_brand(second)).name == "Салон Б"
