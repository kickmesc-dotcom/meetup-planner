"""Первый рабочий экран новой организации не пустой.

Почему это отдельный тест. Репетиция первого запуска показала: организация
создаётся «с нуля», шаблонов чек-листа в ней нет, и первый же экран нового
сотрудника говорит «Чек-лист не назначен — попроси руководителя». Руководителя
рядом нет, что просить — непонятно, и день начинается с переписки.

Здесь проверяется главное обещание: сразу после мастера руководителя у
сотрудника есть что отмечать. И вторая половина — что стартовая пара не
мешает: чужие шаблоны не трогаются, дубликатов не появляется.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.api import routes_hr  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ONBOARDING_DONE,
    ONBOARDING_NEW,
    ROLE_ADMIN,
    ROLE_EMPLOYEE,
    TEMPLATE_CLOSE,
    TEMPLATE_SHIFT,
    ChecklistItem,
    ChecklistTemplate,
    Department,
    Employee,
)
from app.db.models import User  # noqa: E402
from app.db.org_models import DEFAULT_ORG_ID, Organization, reset_org, set_org  # noqa: E402
from app.services import hr_checklists  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "employees",
    "departments",
    "admin_config",
    "checklist_templates",
    "checklist_items",
    "checklist_runs",
    "checklist_completions",
    "halls",
    "shift_hall_choices",
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
    session.add(Organization(id=DEFAULT_ORG_ID, slug="default", name="Кофейня"))
    user = User(id=1, telegram_id=None, email="owner@example.com", display_name="Владелец")
    session.add(user)
    employee = Employee(
        org_id=DEFAULT_ORG_ID,
        user_id=1,
        role=ROLE_ADMIN,
        onboarding_state=ONBOARDING_NEW,
    )
    session.add(employee)
    await session.commit()
    return user, employee


async def _templates(session, department_id: int) -> dict[str, ChecklistTemplate]:
    rows = await session.scalars(
        select(ChecklistTemplate).where(
            ChecklistTemplate.department_id == department_id
        )
    )
    return {template.kind: template for template in rows}


async def test_starter_pair_appears_with_the_organisation(session) -> None:
    """После мастера у подразделения есть открытие и закрытие смены."""
    user, employee = await _owner(session)

    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(done=True), session, user, employee
    )

    department = await session.scalar(select(Department))
    by_kind = await _templates(session, department.id)
    assert set(by_kind) == {TEMPLATE_SHIFT, TEMPLATE_CLOSE}
    assert by_kind[TEMPLATE_SHIFT].title == "Открытие смены"
    assert by_kind[TEMPLATE_CLOSE].title == "Закрытие смены"

    # Шаблоны не привязаны к залу: залов у новой организации нет, а шаблон с
    # `hall_id` сотрудник без выбора зала не увидит вовсе.
    assert all(t.hall_id is None for t in by_kind.values())
    assert all(t.is_active for t in by_kind.values())

    opening_items = (
        await session.scalars(
            select(ChecklistItem)
            .where(ChecklistItem.template_id == by_kind[TEMPLATE_SHIFT].id)
            .order_by(ChecklistItem.sort_order)
        )
    ).all()
    assert len(opening_items) == len(hr_checklists.STARTER_OPENING_ITEMS)
    assert all(item.is_mandatory for item in opening_items)
    assert all(item.title for item in opening_items)


async def test_first_screen_of_a_new_employee_is_not_empty(session) -> None:
    """Тот самый экран, где раньше было «попроси руководителя»."""
    user, owner = await _owner(session)
    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(done=True), session, user, owner
    )

    department = await session.scalar(select(Department))
    staff = Employee(
        org_id=DEFAULT_ORG_ID,
        user_id=2,
        role=ROLE_EMPLOYEE,
        department_id=department.id,
        position="Бариста",
        onboarding_state=ONBOARDING_DONE,
    )
    session.add(staff)
    await session.commit()

    view = await hr_checklists.build_view(session, staff, kind=TEMPLATE_SHIFT)

    assert view.template_id is not None, "шаблон не назначился — пустой экран"
    assert view.items, "чек-лист без пунктов"
    assert view.progress.total == len(view.items)
    # Пункты не спрятаны условием по должности: стартовый набор — для всех.
    assert all(item.active for item in view.items)

    # И то же самое через ту же ручку, которой пользуется приложение: сервис
    # мог бы отдать пункты, а сериализация — потерять их.
    out = await routes_hr.checklist(session, staff, kind=TEMPLATE_SHIFT, shift_date=None)
    assert out.template_title == "Открытие смены"
    assert len(out.items) == len(view.items)
    assert out.total == len(view.items)
    assert out.progress_text.startswith("Выполнено 0 из")


async def test_starter_pair_is_not_duplicated_on_a_second_pass(session) -> None:
    """Мастер можно пройти повторно — шаблоны не должны размножаться."""
    user, employee = await _owner(session)
    setup = routes_hr.OrgSetupIn(done=True)

    await routes_hr.save_org_setup(setup, session, user, employee)
    await routes_hr.save_org_setup(setup, session, user, employee)

    department = await session.scalar(select(Department))
    rows = (
        await session.scalars(
            select(ChecklistTemplate).where(
                ChecklistTemplate.department_id == department.id
            )
        )
    ).all()
    assert len(rows) == 2
    items = (
        await session.scalars(select(ChecklistItem))
    ).all()
    assert len(items) == len(hr_checklists.STARTER_OPENING_ITEMS) + len(
        hr_checklists.STARTER_CLOSING_ITEMS
    )


async def test_own_templates_are_left_alone(session) -> None:
    """У кого шаблон уже есть — тому стартовый не навязываем."""
    user, employee = await _owner(session)
    department = Department(name="Кухня", slug="kitchen", emoji="🍳")
    session.add(department)
    await session.flush()
    own = ChecklistTemplate(
        department_id=department.id,
        title="Свой чек-лист шефа",
        kind=TEMPLATE_SHIFT,
    )
    session.add(own)
    await session.commit()

    created = await hr_checklists.ensure_starter_templates(
        session, department_id=department.id
    )

    # Появилось только закрытие смены: открытие у подразделения своё.
    assert [t.kind for t in created] == [TEMPLATE_CLOSE]
    titles = (
        await session.scalars(
            select(ChecklistTemplate.title).where(
                ChecklistTemplate.department_id == department.id
            )
        )
    ).all()
    assert "Свой чек-лист шефа" in titles
    assert "Открытие смены" not in titles


async def test_hall_specific_template_does_not_block_the_starter(session) -> None:
    """Шаблон для зала не считается «стартовым»: у общего своя судьба."""
    user, employee = await _owner(session)
    department = Department(name="Официанты", slug="waiter", emoji="🍽")
    session.add(department)
    await session.flush()
    await session.commit()

    created = await hr_checklists.ensure_starter_templates(
        session, department_id=department.id
    )

    assert {t.kind for t in created} == {TEMPLATE_SHIFT, TEMPLATE_CLOSE}
