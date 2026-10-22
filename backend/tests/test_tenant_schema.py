"""Тенант-ядро: организации, членство и страж схемы (B2B_PLATFORM_PLAN, фаза 1).

Здесь три вещи, которые нельзя проверить «глазами»:

1. **Страж схемы.** Любая новая таблица обязана либо иметь `org_id`, либо быть
   явно перечисленной в легаси-списке. Без этого модели плодятся, а вопрос
   «чьи это данные» никто не задаёт — и вторая организация получает чужие
   записи. Страж работает в обе стороны: нельзя убрать `org_id` у готовой
   таблицы и нельзя тайком добавить его легаси-таблице, не обновив список.
2. **Резолв организации.** Членство важнее «первой активной»: человек из второй
   организации не должен попадать в данные первой.
3. **Уникальность внутри тенанта.** Слаг подразделения уникален в паре с
   `org_id`, иначе салон не сможет завести свой «bar» рядом с рестораном.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

import app.db.models  # noqa: E402,F401  — регистрирует все таблицы
from app.api import deps  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import Department, Employee  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    OrganizationMember,
)
from app.services import orgs  # noqa: E402

# Таблицы, у которых `org_id` уже есть. Список только растёт: перенос таблицы
# сюда — это и есть прогресс фазы 1.
TENANT_TABLES: set[str] = {
    "departments",
    "employees",
    "organization_members",
}

# Сама организация — корень тенанта: `org_id` у неё был бы ссылкой на себя.
TENANT_ROOT: set[str] = {"organizations"}

# Легаси: пока живут в одном контуре. Каждая строка — долг из плана.
LEGACY_TABLES: set[str] = {
    "achievement_counters",
    "admin_config",
    "app_access_links",
    "app_notifications",
    "availability_ranges",
    "birthday_notifications",
    "birthdays",
    "bot_pause",
    "chat_activity_daily",
    "chat_messages",
    "checklist_completions",
    "checklist_items",
    "checklist_runs",
    "checklist_templates",
    "employee_achievements",
    "employee_training_days",
    "employee_training_steps",
    "event_log",
    "feedback_answers",
    "feedback_questions",
    "game_holidays",
    "game_journal",
    "game_media_posts",
    "game_nominations",
    "game_profiles",
    "game_prompts",
    "game_voice_submissions",
    "game_voice_tasks",
    "halls",
    "hr_handover_items",
    "hr_handovers",
    "hr_issue_events",
    "hr_issues",
    "hr_roster_snapshots",
    "hr_shift_templates",
    "hr_shifts",
    "hr_simulation_sessions",
    "loser_outbox",
    "loser_rolls",
    "meeting_attendance",
    "meeting_feedback",
    "meeting_reminders",
    "meetings",
    "media_blobs",
    "music_game_rounds",
    "music_selections",
    "music_track_likes",
    "music_tracks",
    "participant_personas",
    "poll_options",
    "poll_votes",
    "polls",
    "proxy_entries",
    "sheet_sources",
    "shift_hall_choices",
    "standard_checks",
    "standard_questions",
    "standards",
    "task_assignments",
    "task_events",
    "task_issues",
    "task_photos",
    "task_reminders",
    "tasks",
    "user_achievements",
    "useful_links",
    "users",
    "weekly_chukhan",
    "worm_assignments",
    "xp_daily",
    "xp_grants",
}


def test_lists_do_not_overlap() -> None:
    assert TENANT_TABLES & LEGACY_TABLES == set()
    assert TENANT_ROOT & (TENANT_TABLES | LEGACY_TABLES) == set()


def test_every_table_is_classified() -> None:
    """Новая таблица обязана получить решение, а не проскочить молча."""
    unknown = set(Base.metadata.tables) - TENANT_TABLES - LEGACY_TABLES - TENANT_ROOT
    assert not unknown, (
        "новая таблица без решения по тенанту: "
        f"{sorted(unknown)} — добавьте org_id и запишите её в TENANT_TABLES "
        "или осознанно внесите в LEGACY_TABLES"
    )


def test_tenant_tables_have_org_id() -> None:
    missing = {
        name
        for name in TENANT_TABLES
        if "org_id" not in Base.metadata.tables[name].columns
    }
    assert not missing, f"пропал org_id: {sorted(missing)}"


def test_legacy_tables_still_have_no_org_id() -> None:
    """Расхождение списка с реальностью ловится сразу, а не через полгода."""
    for name in sorted(LEGACY_TABLES):
        assert "org_id" not in Base.metadata.tables[name].columns, (
            f"{name} уже получила org_id — перенесите её в TENANT_TABLES"
        )


def test_department_slug_is_unique_inside_org() -> None:
    names = {
        constraint.name
        for constraint in Department.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert "uq_department_org_slug" in names
    # Глобальной уникальности быть не должно: она не даст завести «bar»
    # двум разным организациям.
    assert "uq_department_slug" not in names


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    tables = [
        Base.metadata.tables[name]
        for name in (
            "organizations",
            "users",
            "departments",
            "employees",
            "organization_members",
        )
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


async def _user(session, telegram_id: int) -> User:
    user = User(
        id=telegram_id,
        telegram_id=telegram_id,
        display_name=f"Человек {telegram_id}",
        color_hex="#336699",
        timezone="Europe/Moscow",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def test_ensure_default_is_idempotent(session) -> None:
    first = await orgs.ensure_default(session)
    second = await orgs.ensure_default(session)
    assert first.id == DEFAULT_ORG_ID == second.id
    assert first.slug == "default"
    assert len(await orgs.list_active(session)) == 1


async def test_create_org_normalizes_slug_and_validates(session) -> None:
    await orgs.ensure_default(session)
    created = await orgs.create_org(
        session, slug="Krasota  Plus_1", name="  Салон Красоты  ", industry="salon"
    )
    assert created.slug == "krasota-plus-1"
    assert created.name == "Салон Красоты"
    assert created.industry == "salon"
    # Первая организация заняла id=1 — новая не должна с ней столкнуться.
    assert created.id != DEFAULT_ORG_ID

    with pytest.raises(orgs.OrgsError, match="slug_taken"):
        await orgs.create_org(session, slug="krasota-plus-1", name="Дубль")
    with pytest.raises(orgs.OrgsError, match="bad_industry"):
        await orgs.create_org(session, slug="drugoe", name="Другое", industry="space")
    with pytest.raises(orgs.OrgsError, match="bad_name"):
        await orgs.create_org(session, slug="pustoe", name="   ")
    with pytest.raises(orgs.OrgsError, match="bad_slug"):
        await orgs.create_org(session, slug="!!", name="Плохой код")


async def test_membership_is_idempotent_and_updates_role(session) -> None:
    await orgs.ensure_default(session)
    org = await orgs.create_org(session, slug="salon", name="Салон")
    user = await _user(session, 1001)

    first = await orgs.add_member(session, org_id=org.id, user_id=user.id)
    assert first.role == "staff"
    second = await orgs.add_member(
        session, org_id=org.id, user_id=user.id, role="owner"
    )
    assert second.id == first.id
    assert second.role == "owner"
    assert await orgs.member(session, org_id=org.id, user_id=user.id) is not None

    with pytest.raises(orgs.OrgsError, match="bad_role"):
        await orgs.add_member(
            session, org_id=org.id, user_id=user.id, role="superuser"
        )


async def test_default_org_prefers_membership_over_first_org(session) -> None:
    """Человек из второй организации не должен попадать в данные первой."""
    default = await orgs.ensure_default(session)
    other = await orgs.create_org(session, slug="avto", name="Автосервис")
    member = await _user(session, 2001)
    stranger = await _user(session, 2002)

    await orgs.add_member(session, org_id=other.id, user_id=member.id, role="manager")

    assert (await orgs.default_org_for(session, member)).id == other.id
    # Без членства поведение прежнее — первая организация.
    assert (await orgs.default_org_for(session, stranger)).id == default.id
    assert [o.id for o in await orgs.orgs_of(session, member.id)] == [other.id]


async def test_current_org_rejects_inactive_and_missing(session) -> None:
    org = await orgs.ensure_default(session)
    user = await _user(session, 3001)
    employee = Employee(id=1, user_id=user.id, org_id=org.id)
    session.add(employee)
    await session.commit()
    await session.refresh(employee)

    resolved = await deps.current_org(session, employee)
    assert resolved.id == org.id

    org.is_active = False
    await session.commit()
    with pytest.raises(HTTPException) as inactive:
        await deps.current_org(session, employee)
    assert inactive.value.status_code == 403
    assert inactive.value.detail == "org_inactive"

    employee.org_id = 999
    await session.commit()
    with pytest.raises(HTTPException) as missing:
        await deps.current_org(session, employee)
    assert missing.value.detail == "org_missing"


async def test_two_orgs_can_have_departments_with_the_same_slug(session) -> None:
    first = await orgs.ensure_default(session)
    second = await orgs.create_org(session, slug="retail", name="Магазин")
    # id задаём явно: BIGINT-первичник в sqlite не автоинкрементится.
    session.add(Department(id=1, org_id=first.id, name="Бар", slug="bar"))
    session.add(Department(id=2, org_id=second.id, name="Бар", slug="bar"))
    await session.commit()
    bars = list(
        await session.scalars(select(Department).where(Department.slug == "bar"))
    )
    assert {row.org_id for row in bars} == {first.id, second.id}


async def test_membership_row_links_user_and_org(session) -> None:
    org = await orgs.ensure_default(session)
    user = await _user(session, 4001)
    await orgs.add_member(session, org_id=org.id, user_id=user.id)
    rows = list(await session.scalars(select(OrganizationMember)))
    assert len(rows) == 1
    assert rows[0].org_id == org.id
    assert isinstance(await orgs.get(session, org.id), Organization)
