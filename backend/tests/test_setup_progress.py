"""Сводка мастера настройки (B2B_PLATFORM_PLAN, фаза 3, шаг 3.4).

Зачем тесты. Мастер закрывается и кнопкой «Пропустить», поэтому флаг `done`
ничего не говорит о готовности: с ним организация может остаться без шаблона
недели и без единого человека, а руководитель будет уверен, что настроил.
Сводка отвечает числами — и ошибиться в ней легко ровно там, где больно:
демо-сотрудники не должны считаться командой, а чек-листы зала не должны
считаться вторым стартовым набором.

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
    """JSONB в тестовой sqlite: `hr_shift_templates.pattern` объявлен JSONB."""
    return "JSON"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):  # noqa: ARG001
    """BigInteger-ключи в sqlite: иначе вставка требует `id` явно."""
    return "INTEGER"


from app.api import routes_hr  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_EMPLOYEE,
    ChecklistItem,
    ChecklistTemplate,
    Department,
    Employee,
    HrShiftTemplate,
)
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    reset_org,
    set_org,
)
from app.services import org_progress  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "employees",
    "departments",
    "checklist_templates",
    "checklist_items",
    "hr_shift_templates",
    "org_invitations",
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


@pytest.fixture(autouse=True)
def clean_org_context():
    token = set_org(DEFAULT_ORG_ID)
    yield
    reset_org(token)


async def _owner(session) -> tuple[User, Employee]:
    session.add(Organization(id=DEFAULT_ORG_ID, slug="default", name="Салон"))
    user = User(id=1, telegram_id=None, email="owner@example.com", display_name="Владелец")
    session.add(user)
    employee = Employee(org_id=DEFAULT_ORG_ID, user_id=1, role=ROLE_ADMIN)
    session.add(employee)
    await session.commit()
    return user, employee


async def _department(session, name: str = "Парикмахеры") -> Department:
    department = Department(org_id=DEFAULT_ORG_ID, name=name, slug=name.lower())
    session.add(department)
    await session.commit()
    return department


async def test_demo_people_do_not_count_as_the_team(session) -> None:
    """Витрина «на ваших данных» — не команда: иначе приглашать «некого»."""
    await _owner(session)
    # `user_id` в бою NOT NULL: у сотрудника всегда есть учётная запись.
    session.add(User(id=2, telegram_id=None, display_name="Мастер"))
    session.add(User(id=3, telegram_id=None, display_name="[BOT] Мастер"))
    await session.commit()
    session.add(
        Employee(org_id=DEFAULT_ORG_ID, user_id=2, role=ROLE_EMPLOYEE)
    )
    session.add(
        Employee(
            org_id=DEFAULT_ORG_ID,
            user_id=3,
            role=ROLE_EMPLOYEE,
            is_simulation=True,
        )
    )
    await session.commit()

    progress = await org_progress.summary(session, org_id=DEFAULT_ORG_ID)

    # Владелец из `_owner` + приглашённый мастер; демо-профиль не в счёте,
    # иначе витрина «на ваших данных» выглядела бы как настоящая команда.
    assert progress.people == 2
    assert progress.departments == 0


async def test_checklists_and_templates_are_counted_per_department(session) -> None:
    await _owner(session)
    department = await _department(session)
    template = ChecklistTemplate(
        org_id=DEFAULT_ORG_ID,
        department_id=department.id,
        title="Открытие смены",
        kind="shift",
        sort_order=0,
    )
    session.add(template)
    await session.flush()
    for order, title in enumerate(("Проверить кабинет", "Сверить запись")):
        session.add(
            ChecklistItem(
                template_id=template.id,
                title=title,
                requires_photo=False,
                is_mandatory=True,
                sort_order=order,
            )
        )
    session.add(
        HrShiftTemplate(
            org_id=DEFAULT_ORG_ID,
            name="Смена 5/2",
            department_id=department.id,
            pattern=[],
        )
    )
    await session.commit()

    progress = await org_progress.summary(session, org_id=DEFAULT_ORG_ID)

    assert progress.shift_templates == 1
    assert progress.departments == 1
    assert [(item.title, item.department, item.items) for item in progress.checklists] == [
        ("Открытие смены", "Парикмахеры", 2)
    ]


async def test_staff_cannot_read_the_summary(session) -> None:
    """Сводка — для того, кто мастер проходит: число людей не для всего зала."""
    user, owner = await _owner(session)
    staff = Employee(org_id=DEFAULT_ORG_ID, user_id=user.id, role=ROLE_EMPLOYEE)

    with pytest.raises(HTTPException) as caught:
        await routes_hr.get_org_setup_progress(session, user, staff)

    assert caught.value.detail == "managers_only"
    # Владельцу сводка открыта: он и есть тот, кто проходит мастер.
    out = await routes_hr.get_org_setup_progress(session, user, owner)
    assert out.departments == 0
    assert out.checklists == []
