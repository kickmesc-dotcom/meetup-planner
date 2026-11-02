"""Демо-данные отрасли (B2B_PLATFORM_PLAN, фаза 3, шаг 3.3).

Зачем тесты. Витрина «покажем на ваших данных за 5 минут» ломается ровно тогда,
когда демо показывает чужой бизнес: руководитель салона видел поваров и решал
«это не про нас». Поэтому проверяем не «пул завёлся», а что состав следует
отрасли — люди, подразделения, поручения — и что повторный проход безопасен.

Env выставляем ДО импорта моделей — `Settings` требует BOT_TOKEN и т.п.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy import BigInteger, select  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw):  # noqa: ARG001
    """JSONB в тестовой sqlite: боевая схема остаётся постгресовой.

    `feedback_questions.options` объявлен JSONB, а sqlite такого типа не знает.
    Менять модель ради теста значило бы трогать боевую схему; регистрация
    компилятора живёт только в процессе тестов.
    """
    return "JSON"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):  # noqa: ARG001
    """BigInteger-ключи в тестовой sqlite: иначе вставка требует `id` явно.

    В PostgreSQL ключи растут identity-последовательностью, а sqlite такой
    записи не понимает — и любой `session.add(Task(...))` падает на NOT NULL.
    """
    return "INTEGER"

from app.db.base import Base  # noqa: E402
from app.db.hr_models import Department, Employee, Task  # noqa: E402
from app.services import hr_demo, org_packs  # noqa: E402

TABLES = [
    "users",
    "employees",
    "departments",
    "checklist_templates",
    "checklist_items",
    "checklist_runs",
    "checklist_completions",
    "tasks",
    "task_events",
    "task_photos",
    "task_issues",
    "feedback_questions",
    "feedback_answers",
    "admin_config",
]


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


# --------------------------------------------------------------------------
# Состав пула
# --------------------------------------------------------------------------


def test_salon_demo_has_no_restaurant_roles():
    people = hr_demo.demo_people("salon")
    positions = " ".join(row[2] for row in people).lower()
    assert "парикмахер" in positions
    assert "повар" not in positions
    assert "официант" not in positions


def test_autoservice_demo_has_mechanics():
    positions = " ".join(row[2] for row in hr_demo.demo_people("autoservice")).lower()
    assert "механик" in positions
    assert "бармен" not in positions


def test_unknown_industry_falls_back_to_restaurant():
    """`other` и мусор в настройке — не повод остаться без демо."""
    people = hr_demo.demo_people("starship")
    restaurant = hr_demo.demo_people("restaurant")
    assert people == restaurant
    assert len(people) == len(hr_demo._DEMO_NAMES)


def test_pool_size_matches_names():
    assert hr_demo.demo_pool_size() == len(hr_demo._DEMO_NAMES)


def test_every_industry_has_demo_tasks():
    for industry in ("restaurant", "salon", "autoservice", "retail"):
        assert org_packs.demo_tasks(industry), industry
    assert org_packs.demo_tasks("starship") == org_packs.demo_tasks("restaurant")


# --------------------------------------------------------------------------
# Заведение пула
# --------------------------------------------------------------------------


async def test_seed_uses_industry_roles_and_links_by_department_name(session):
    salon = Department(name="Парикмахеры", slug="parikmahery")
    session.add(salon)
    await session.commit()

    created = await hr_demo.seed_pool(session, industry="salon")
    await session.commit()

    assert created == len(hr_demo._DEMO_NAMES)
    employees = list(await session.scalars(select(Employee).order_by(Employee.id)))
    first = employees[0]
    assert first.is_demo is True
    assert first.position == "парикмахер"
    # Связь по имени пресета: в боевой организации slug — `slugify(имя)`.
    assert first.department_id == salon.id


async def test_reseed_after_industry_change_renames_roles(session):
    await hr_demo.seed_pool(session, industry="salon")
    await session.commit()
    employees = list(await session.scalars(select(Employee).order_by(Employee.id)))

    created = await hr_demo.seed_pool(session, industry="retail")
    await session.commit()

    # Повтор не заводит вторых людей: те же строки получают новые роли.
    assert created == 0
    await session.refresh(employees[0])
    assert employees[0].position == "продавец"
    assert employees[0].badge_emoji == "🛍"
    assert len((await session.scalars(select(Employee))).all()) == len(employees)


async def test_sole_department_is_used_even_with_other_name(session):
    """Клиент переименовал «Кухню» в «Цех» — демо не должно остаться без него."""
    only = Department(name="Цех", slug="tsekh")
    session.add(only)
    await session.commit()

    await hr_demo.seed_pool(session, industry="autoservice")
    await session.commit()

    employees = list(await session.scalars(select(Employee).order_by(Employee.id)))
    assert {e.department_id for e in employees} == {only.id}


# --------------------------------------------------------------------------
# Активность
# --------------------------------------------------------------------------


async def test_simulate_creates_tasks_from_industry_pack(session):
    await hr_demo.seed_pool(session, industry="salon")
    await session.commit()

    counters = await hr_demo.simulate(session, days=1, industry="salon")

    assert counters["tasks"] > 0
    titles = set(await session.scalars(select(Task.title)))
    allowed = {title for title, _ in org_packs.demo_tasks("salon")}
    assert titles <= allowed
    assert "Проверить сроки годности на раздаче" not in titles


async def test_overview_reports_industry(session):
    await hr_demo.seed_pool(session, industry="autoservice")
    await session.commit()

    data = await hr_demo.overview(session)
    # Настройки нет — отрасль по умолчанию ресторанная, и заголовок должен
    # говорить это словом, а не техническим ключом.
    assert data.industry == "restaurant"
    assert data.industry_title == org_packs.get("restaurant").title
    assert len(data.employees) == len(hr_demo._DEMO_NAMES)
