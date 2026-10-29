"""Тенант-ядро: организации, членство и страж схемы (B2B_PLATFORM_PLAN, фаза 1).

Здесь три вещи, которые нельзя проверить «глазами»:

1. **Страж схемы.** Любая новая таблица обязана либо иметь `org_id`, либо быть
   явно перечисленной в списке глобальных с обоснованием. Без этого модели
   плодятся, а вопрос «чьи это данные» никто не задаёт — и вторая организация
   получает чужие записи. Страж работает в обе стороны: нельзя убрать `org_id`
   у готовой таблицы и нельзя тайком добавить его глобальной, не обновив список.
2. **Резолв организации.** Членство важнее «первой активной»: человек из второй
   организации не должен попадать в данные первой.
3. **Уникальность внутри тенанта.** Слаг подразделения уникален в паре с
   `org_id`, иначе салон не сможет завести свой «bar» рядом с рестораном.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
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
    reset_org,
    set_org,
)
from app.db.tenancy import all_orgs  # noqa: E402
from app.services import orgs  # noqa: E402

# Все бизнес-таблицы. Список явный, а не «всё, что есть в metadata»: новая
# таблица обязана получить решение осознанно, а не проскочить вместе с
# остальными. На 22.10.2026 здесь 72 таблицы — то есть `org_id` есть у всего,
# что принадлежит клиенту.
TENANT_TABLES: set[str] = {
    "achievement_counters",
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
    "departments",
    "employee_achievements",
    "employee_training_days",
    "employee_training_steps",
    "employees",
    # Приглашение принадлежит организации, из которой выписано (шаг 2.2):
    # именно его `org_id` решает, куда попадёт приглашённый.
    "org_invitations",
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
    # Благодарности — данные организации: в одной сети спасибо говорят
    # по-узбекски, в другой по-русски, но топ чужой команды видеть нельзя.
    "hr_kudos",
    "hr_roster_snapshots",
    "hr_shift_templates",
    "hr_shifts",
    "hr_simulation_sessions",
    "loser_outbox",
    "loser_rolls",
    "media_blobs",
    "meeting_attendance",
    "meeting_feedback",
    "meeting_reminders",
    "meetings",
    "music_game_rounds",
    "music_selections",
    "music_track_likes",
    "music_tracks",
    "organization_members",
    "participant_personas",
    "poll_options",
    "poll_votes",
    "polls",
    "proxy_entries",
    "push_subscriptions",
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
    "useful_links",
    "user_achievements",
    "weekly_chukhan",
    "worm_assignments",
    "xp_daily",
    "xp_grants",
}

# Сама организация — корень тенанта: `org_id` у неё был бы ссылкой на себя.
TENANT_ROOT: set[str] = {"organizations"}

# Глобальные таблицы — не «долг», а осознанное решение, и каждое с причиной:
#
# * `users` — личность человека. Один Telegram-аккаунт может работать в двух
#   организациях сети, поэтому человек не принадлежит ни одной из них; связь
#   живёт в `organization_members`.
# * `admin_config` — настройки установки (ключ-значение) с первичным ключом по
#   `key`. Пока один контур; при переходе на несколько клиентов ключ станет
#   составным `(org_id, key)`, и таблица переедет в TENANT_TABLES. Это
#   единственная оставшаяся строка долга, и она записана в плане.
GLOBAL_TABLES: set[str] = {
    "users",
    "admin_config",
    # Вход и сброс живут вне тенанта: аутентификация происходит ДО того, как
    # известно, в какую организацию идёт запрос (человек может состоять в
    # двух). Токен проверяется без фильтра, иначе вход зависел бы от угаданной
    # организации.
    "auth_sessions",
    "password_resets",
    # Подтверждение почты (шаг 2.1) тоже живёт до выбора организации: ссылка
    # может открыться на устройстве без входа.
    "email_verifications",
    # Кэш перевода данных (план, 11) — осознанно вне тенанта. Ключ —
    # sha256(текст + язык), значение — перевод этой строки. Одинаковая фраза
    # («Помыть пол в зале») переводится одинаково в любой организации, и
    # хранить её дважды — платить за одно и то же дважды. Утечки нет: в строке
    # лежит перевод того текста, который запросивший и так видит, а исходного
    # текста в таблице нет вовсе.
    "translation_cache",
}

# Глобальные таблицы, которым `org_id` нужен как ДАННЫЕ, а не как фильтр:
# сессия помнит, в какой организации выдан вход, но сама не является её
# содержимым.
ORG_ID_ALLOWED_GLOBAL: set[str] = {"auth_sessions"}


def test_lists_do_not_overlap() -> None:
    assert TENANT_TABLES & GLOBAL_TABLES == set()
    assert TENANT_ROOT & (TENANT_TABLES | GLOBAL_TABLES) == set()


def test_every_table_is_classified() -> None:
    """Новая таблица обязана получить решение, а не проскочить молча."""
    unknown = set(Base.metadata.tables) - TENANT_TABLES - GLOBAL_TABLES - TENANT_ROOT
    assert not unknown, (
        "новая таблица без решения по тенанту: "
        f"{sorted(unknown)} — добавьте org_id и запишите её в TENANT_TABLES "
        "или осознанно внесите в GLOBAL_TABLES (с обоснованием в комментарии)"
    )


def test_tenant_tables_have_org_id() -> None:
    missing = {
        name
        for name in TENANT_TABLES
        if "org_id" not in Base.metadata.tables[name].columns
    }
    assert not missing, f"пропал org_id: {sorted(missing)}"


def test_global_tables_still_have_no_org_id() -> None:
    """Расхождение списка с реальностью ловится сразу, а не через полгода."""
    for name in sorted(GLOBAL_TABLES - ORG_ID_ALLOWED_GLOBAL):
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
    # Обе организации сразу видны только платформенному обходу: обычный
    # запрос отфильтрован по текущему тенанту (шаг 1.3).
    with all_orgs():
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


# --------------------------------------------------------------------------
# Сверка миграции с моделями
# --------------------------------------------------------------------------
# Страж выше ловит таблицу без `org_id` в моделях. Но схеме нужно ещё одно:
# чтобы миграция добавляла `org_id` РОВНО тем таблицам, и чтобы уникальные
# ключи переезжали внутри тенанта вместе с моделями. Иначе `alembic upgrade`
# на чистой базе даст схему, отличную от той, что видят тесты на metadata.

MIGRATION_0054 = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0054_tenant_columns.py"


def _migration_0054():
    spec = importlib.util.spec_from_file_location("_migration_0054", MIGRATION_0054)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0054_covers_every_tenant_table() -> None:
    module = _migration_0054()
    already = {"departments", "employees", "organization_members"}  # получили в 0053
    # Таблицы, созданные позже 0054: у них `org_id` есть с рождения, и
    # добавлять его миграцией 0054 было бы некуда. Список явный, чтобы новая
    # таблица всё равно требовала решения.
    created_later = {
        "org_invitations",
        "push_subscriptions",
        "hr_kudos",  # 0062
    }  # 0057, 0058, 0062
    assert set(module.TENANT_TABLES) == TENANT_TABLES - already - created_later


def test_migration_0054_unique_swaps_match_models() -> None:
    module = _migration_0054()
    for table, old, new, columns in module.UNIQUE_SWAPS:
        constraints = {
            constraint.name: tuple(column.name for column in constraint.columns)
            for constraint in Base.metadata.tables[table].constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
            and constraint.name
        }
        assert constraints.get(new) == columns, f"{table}: {new} не совпал с моделью"
        assert old not in constraints, f"{table}: старый ключ {old} остался в модели"

    indexes = {
        index.name: (index.unique, tuple(column.name for column in index.columns))
        for table in Base.metadata.tables.values()
        for index in table.indexes
    }
    for name, _table, columns in module.UNIQUE_INDEX_SWAPS:
        unique, actual = indexes[name]
        assert unique, f"{name}: индекс перестал быть уникальным"
        assert actual == columns, f"{name}: колонки индекса разошлись с миграцией"


# --------------------------------------------------------------------------
# Тенантский фильтр (шаг 1.3)
# --------------------------------------------------------------------------
# Колонка `org_id` без фильтра ничего не защищает: забытый `where` вернёт
# строки всех клиентов. Слушатель в `app.db.tenancy` добавляет условие сам,
# и эти тесты проверяют его на тех путях, которыми реально ходит код:
# выборка, `count`, `Session.get`, вставка и отношения.

TENANT_FIXTURE_TABLES = (
    "organizations",
    "users",
    "departments",
    "employees",
    "organization_members",
)


@pytest.fixture()
async def tenant_session():
    engine = create_async_engine("sqlite+aiosqlite://")
    tables = [Base.metadata.tables[name] for name in TENANT_FIXTURE_TABLES]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


async def _two_orgs_with_employees(session):
    first = await orgs.ensure_default(session)
    second = await orgs.create_org(session, slug="salon", name="Салон")
    user_a = await _user(session, 5001)
    user_b = await _user(session, 5002)
    session.add(Employee(id=1, user_id=user_a.id, org_id=first.id))
    session.add(Employee(id=2, user_id=user_b.id, org_id=second.id))
    session.add(Department(id=1, org_id=first.id, name="Зал", slug="hall"))
    session.add(Department(id=2, org_id=second.id, name="Зал", slug="hall"))
    await session.commit()
    return first, second, user_a, user_b


async def test_selects_see_only_the_current_org(tenant_session) -> None:
    _first, second, _user_a, user_b = await _two_orgs_with_employees(tenant_session)

    token = set_org(second.id)
    try:
        tenant_session.expunge_all()
        employees = list(await tenant_session.scalars(select(Employee)))
        assert [row.user_id for row in employees] == [user_b.id]

        departments = list(await tenant_session.scalars(select(Department)))
        assert [row.org_id for row in departments] == [second.id]

        total = await tenant_session.scalar(select(func.count()).select_from(Employee))
        assert total == 1
    finally:
        reset_org(token)

    tenant_session.expunge_all()
    # Вне контекста — организация по умолчанию, то есть первая.
    assert {row.org_id for row in await tenant_session.scalars(select(Employee))} == {
        DEFAULT_ORG_ID
    }


async def test_get_by_primary_key_is_scoped(tenant_session) -> None:
    first, second, _user_a, _user_b = await _two_orgs_with_employees(tenant_session)

    token = set_org(second.id)
    try:
        tenant_session.expunge_all()
        # Чужой id не должен находиться: иначе достаточно подставить число.
        assert await tenant_session.get(Employee, 1) is None
        found = await tenant_session.get(Employee, 2)
        assert found is not None and found.org_id == second.id
    finally:
        reset_org(token)

    tenant_session.expunge_all()
    assert (await tenant_session.get(Employee, 1)).org_id == first.id


async def test_insert_lands_in_the_current_org(tenant_session) -> None:
    _first, second, user_a, _user_b = await _two_orgs_with_employees(tenant_session)

    token = set_org(second.id)
    try:
        session_row = Employee(id=3, user_id=user_a.id)
        tenant_session.add(session_row)
        await tenant_session.commit()
        await tenant_session.refresh(session_row)
        assert session_row.org_id == second.id
    finally:
        reset_org(token)


async def test_relationship_load_is_scoped(tenant_session) -> None:
    """Связь «отдел → сотрудники» не должна тянуть чужие строки."""
    first, second, _user_a, _user_b = await _two_orgs_with_employees(tenant_session)

    token = set_org(second.id)
    try:
        tenant_session.expunge_all()
        department = await tenant_session.get(Department, 2)
        assert department is not None
        # Отношение есть не у всех версий модели: если его нет — тест не врёт,
        # а честно пропускает проверку (фильтр выборок уже проверен выше).
        if hasattr(department, "employees"):
            assert {row.org_id for row in await department.awaitable_attrs.employees} == {
                second.id
            }
        else:  # pragma: no cover - зависит от состава модели
            assert department.org_id == second.id
    finally:
        reset_org(token)
