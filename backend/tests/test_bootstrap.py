"""Старт приложения одним запросом: тот же состав, что у шести ручек.

Зачем отдельный тест, если каждая ручка проверена. Здесь ловится ровно тот
класс поломок, который появляется, когда одну и ту же выборку собирают в двух
местах: bootstrap собрали из других функций (или забыли обновить вместе с
ручкой) — и приложение на быстром старте показывает одно, а после перезагрузки
другое. Поэтому главная проверка — сравнение с ответами отдельных ручек, а не
перечисление полей.

Второй риск того же рода — потерянные побочные действия. `/me` и
`/me/employee` при заходе пишут «последний заход» и `last_seen_at`; если
bootstrap их не зовёт, функция карточки коллеги тихо исчезает, и никакой тест
ответов этого не заметит.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.api import routes_bootstrap, routes_hr, routes_users  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ONBOARDING_DONE,
    ONBOARDING_NEW,
    ROLE_ADMIN,
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

# Только те таблицы, которые реально трогает путь старта. Полную схему в
# sqlite не поднять (Postgres-специфика), а «всё или ничего» здесь означало бы
# непроверяемую ручку.
TABLES = (
    "organizations",
    "organization_members",
    "users",
    "employees",
    "departments",
    "admin_config",
    "game_profiles",
    "tasks",
    "task_assignments",
    "task_photos",
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


async def _person(session, *, onboarding: str = ONBOARDING_DONE) -> tuple[User, Employee]:
    session.add(Organization(id=DEFAULT_ORG_ID, slug="default", name="Кофейня"))
    session.add(OrganizationMember(org_id=DEFAULT_ORG_ID, user_id=1, role="owner"))
    user = User(id=1, telegram_id=None, email="owner@example.com", display_name="Сергей")
    session.add(user)
    employee = Employee(
        org_id=DEFAULT_ORG_ID,
        user_id=1,
        role=ROLE_ADMIN,
        onboarding_state=onboarding,
    )
    session.add(employee)
    await session.commit()
    return user, employee


async def test_bootstrap_returns_exactly_what_the_six_endpoints_return(session) -> None:
    """Один ответ == шесть ответов, поле в поле.

    Сравнение идёт через `model_dump`, а не по отдельным полям: любое новое
    поле, добавленное в `UserOut`/`OrgSetupOut` и не доехавшее до bootstrap,
    должно ронять тест, а не всплывать в проде.
    """
    user, employee = await _person(session)

    boot = await routes_bootstrap.bootstrap(session, user, employee)

    assert boot.me.model_dump() == (await routes_users.me_out(session, user)).model_dump()
    assert [u.model_dump() for u in boot.users] == [
        u.model_dump() for u in await routes_users.users_out(session)
    ]
    assert boot.employee is not None
    assert boot.employee.model_dump() == (
        await routes_hr.me_employee(session, user, employee)
    ).model_dump()
    assert [t.model_dump() for t in boot.tasks or []] == [
        t.model_dump() for t in await routes_hr.my_tasks(session, employee, False, None)
    ]
    assert boot.org_setup is not None
    assert boot.org_setup.model_dump() == (
        await routes_hr.get_org_setup(session, user, employee)
    ).model_dump()
    assert boot.ui_prefs is not None
    assert boot.ui_prefs.model_dump() == (
        await routes_users.ui_prefs_out(session, user)
    ).model_dump()


async def test_tasks_are_not_asked_for_before_the_intro_is_finished(session) -> None:
    """До знакомства поручений нет — и запрос за ними не делается вовсе.

    Ровно как на фронте, где вкладка «Задачи» появляется после онбординга.
    Иначе каждый новый сотрудник платил бы за старт запросом, результат
    которого некуда показать.
    """
    user, employee = await _person(session, onboarding=ONBOARDING_NEW)

    boot = await routes_bootstrap.bootstrap(session, user, employee)

    assert boot.tasks is None
    # Остальные куски при этом на месте: «нет поручений» — не «нет профиля».
    assert boot.employee is not None
    assert boot.org_setup is not None


async def test_bootstrap_still_marks_the_employee_as_seen(session) -> None:
    """`last_seen_at` обновляется и на быстром старте.

    Проверяем именно запись в базу, а не поле в ответе: карточка коллеги
    читает `employees.last_seen_at`, и потерять её можно, не заметив разницы
    в JSON.
    """
    user, employee = await _person(session)
    assert employee.last_seen_at is None

    await routes_bootstrap.bootstrap(session, user, employee)

    await session.refresh(employee)
    assert employee.last_seen_at is not None


async def test_users_list_is_scoped_to_the_organization(session) -> None:
    """Аккаунт без членства в организации в списке участников не появляется.

    Найдено на боевом экране 29.10: сотрудников в организации три, а `/users`
    отдавал восемь — в списках висели пять аккаунтов прошлой группы (Митян,
    Сомов, Никита, Русланище и ещё один). Причина не в вёрстке: выборка шла по
    глобальной таблице `users`, а не по членству.

    Тест смотрит именно на список, а не на права: право входить у старого
    аккаунта никто не отбирает (пароль/Telegram у него свои), его просто не
    должно быть среди «наших людей».
    """
    user, employee = await _person(session)
    # Личность из прошлого контура: заходила в старый бот, в этой организации
    # не состоит.
    session.add(User(id=2, telegram_id=111, display_name="Митян"))
    await session.commit()

    listed = await routes_users.users_out(session)

    assert [u.id for u in listed] == [user.id]

    # И то же самое через быстрый старт: у него свой список, и он обязан
    # совпадать — иначе экран «до» и «после» перезагрузки показывал бы разное.
    boot = await routes_bootstrap.bootstrap(session, user, employee)
    assert [u.id for u in boot.users or []] == [user.id]
