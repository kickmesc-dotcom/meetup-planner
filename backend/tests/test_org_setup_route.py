"""Мастер настройки организации: что реально доходит до базы.

Здесь проверяется не разбор ответов (он в `test_org_setup_privacy.py`), а два
следа, на которых ломался первый запуск:

* владелец, закрывший мастер, больше не попадает в анкету сотрудника —
  «где ты работаешь» ему задавать нечего, он только что назвал отделы сам;
* организация не остаётся без единого подразделения. Мастер можно пропустить,
  а профиль без отдела невозможно закрыть — получался тупик без выхода.
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
    Department,
    Employee,
)
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    OrganizationMember,
    reset_org,
    set_org,
)

# Чек-листы в списке не для галочки: мастер заводит вместе с подразделениями
# стартовую пару шаблонов (открытие и закрытие смены), и без этих таблиц
# проверять ему пришлось бы не то, что делает он, а то, что смогло записаться.
TABLES = (
    "organizations",
    # Членство в организации: по нему решается право на языковой пакет
    # (`organization_members.role`), а не по HR-роли. Без таблицы чтение
    # настроек падало бы целиком — вместе с мастером и политикой приватности.
    "organization_members",
    "users",
    "employees",
    "departments",
    "admin_config",
    "checklist_templates",
    "checklist_items",
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
    """Владелец, заведённый по почте: у него нет Telegram ID (B2B-путь)."""
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


async def test_finished_setup_creates_a_department_instead_of_a_dead_end(session) -> None:
    user, employee = await _owner(session)

    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(done=True), session, user, employee
    )

    departments = (await session.scalars(select(Department))).all()
    assert [dep.name for dep in departments] == ["Общее"]
    await session.refresh(employee)
    assert employee.onboarding_state == ONBOARDING_DONE


async def test_second_visit_does_not_duplicate_the_fallback_department(session) -> None:
    user, employee = await _owner(session)

    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(done=True), session, user, employee
    )
    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(done=True), session, user, employee
    )

    departments = (await session.scalars(select(Department))).all()
    assert len(departments) == 1


async def test_chosen_departments_win_over_the_fallback(session) -> None:
    user, employee = await _owner(session)

    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(
            departments=["Кухня", "Бариста"], create_departments=True
        ),
        session,
        user,
        employee,
    )
    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(done=True), session, user, employee
    )

    departments = (await session.scalars(select(Department))).all()
    assert sorted(dep.name for dep in departments) == ["Бариста", "Кухня"]


async def test_unfinished_setup_keeps_the_wizard_open(session) -> None:
    user, employee = await _owner(session)

    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(industry="cafe"), session, user, employee
    )

    await session.refresh(employee)
    assert employee.onboarding_state == ONBOARDING_NEW
    assert (await session.scalars(select(Department))).all() == []


# --------------------------------------------------------------------------
# Языковой пакет (план, 8.3)
# --------------------------------------------------------------------------


async def _add_member(session, *, role: str) -> None:
    """Строка членства в организации с нужной ролью.

    Отдельно от `_owner`: HR-роль (`admin`) и роль в организации (`owner`) —
    разные вещи, и пакет решается именно второй.
    """
    session.add(
        OrganizationMember(
            org_id=DEFAULT_ORG_ID, user_id=1, role=role
        )
    )
    await session.commit()


async def test_uz_pack_is_on_by_default_and_visible_to_everyone(session) -> None:
    """По умолчанию перевод включён, и его видит любой сотрудник.

    По умолчанию именно включён: часть команды — узбеки, и если пакет надо
    сначала найти в настройках, им никто не воспользуется.
    """
    user, employee = await _owner(session)

    out = await routes_hr.get_org_setup(session, user, employee)

    assert out.uz_pack is True
    # Владельца ещё нет в `organization_members` — тумблер закрыт, но сам
    # факт включённости от этого не меняется.
    assert out.can_manage_packs is False


async def test_owner_can_turn_the_pack_off(session) -> None:
    user, employee = await _owner(session)
    await _add_member(session, role="owner")

    out = await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(uz_pack=False), session, user, employee
    )

    assert out.uz_pack is False
    assert out.can_manage_packs is True
    # Выключение переживает следующее сохранение мастера: руководитель,
    # поправивший отрасли, не должен вернуть пакет обратно.
    await routes_hr.save_org_setup(
        routes_hr.OrgSetupIn(industry="cafe"), session, user, employee
    )
    assert (await routes_hr.get_org_setup(session, user, employee)).uz_pack is False


async def test_manager_cannot_change_the_pack(session) -> None:
    """Руководитель правит мастер, но не тариф: 403 и явный код."""
    user, employee = await _owner(session)
    await _add_member(session, role="manager")

    with pytest.raises(Exception) as caught:
        await routes_hr.save_org_setup(
            routes_hr.OrgSetupIn(uz_pack=False), session, user, employee
        )

    assert getattr(caught.value, "detail", None) == "owner_only"
    assert (await routes_hr.get_org_setup(session, user, employee)).uz_pack is True
