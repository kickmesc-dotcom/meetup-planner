"""Полный путь сотрудника на ЖИВОЙ тестовой Postgres (интеграционный тест).

Зачем отдельный файл. Остальные тесты HR-ядра работают на фейках и чистых
правилах — и это правильно для быстрых прогонов, но именно так в этом проекте
уже уезжали в прод дефекты, которых не видно без настоящей схемы: неверный PK
в `session.get`, `scalar` вместо `first()`, `# noqa` вместо честного типа. Здесь
идёт тот же путь, что проходит человек, но через настоящие ручки FastAPI и
настоящий Postgres: онбординг → чек-лист смены (с обязательным фотоотчётом) →
поручение АУП с фотоотчётом → выдача скрытой ачивки → запись в ленте.

Как запустить (база должна быть ПУСТОЙ и на `alembic head`):

    # 1) отдельная тестовая база (не боевая!). Создаём её руками в Neon/локально:
    createdb semitask_test        # или: Neon → проект → новая база
    # 2) схема на head
    cd backend
    DATABASE_URL="postgresql://user:pw@host/semitask_test" alembic upgrade head
    # 3) прогон
    HR_FLOW_TEST_DSN="postgresql://user:pw@host/semitask_test" \\
        .venv/Scripts/python.exe -m pytest tests/test_hr_flow_pg.py -q

Без `HR_FLOW_TEST_DSN` тест ПРОПУСКАЕТСЯ: боевой DSN из `DATABASE_URL` сюда
специально не подставляется — в боевой базе этому тесту делать нечего.

Данные теста живут в одной внешней транзакции (`join_transaction_mode=
"create_savepoint"`, соединение взято из `begin()`), поэтому после прогона в
базе не остаётся ни одной строки — включая те коммиты, которые делают сами
ручки. Это проверяется ассертом по счётчику сотрудников до/после.
"""

from __future__ import annotations

import os
import ssl
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("ADMIN_TG_IDS", "")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from app.api import deps  # noqa: E402
from app.db.base import _normalize_url, _ssl_enabled_for  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ONBOARDING_DONE,
    ROLE_AUP,
    ROLE_EMPLOYEE,
    TASK_DONE,
    TEMPLATE_SHIFT,
    ChecklistItem,
    ChecklistTemplate,
    Department,
    Employee,
)
from app.db.models import User  # noqa: E402
from app.main import create_app  # noqa: E402

DSN_ENV = "HR_FLOW_TEST_DSN"
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _code_head() -> str:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, f"у миграций не один head: {heads}"
    return heads[0]


def _engine(dsn: str):
    url = _normalize_url(dsn)
    connect_args: dict[str, object] = {"command_timeout": 60}
    if "asyncpg" in url and _ssl_enabled_for(url):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ctx
    return create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)


# Таблицы, которые трогает прогон. База тестовая и выделенная, поэтому чистим её
# прямолинейно: так teardown не зависит от того, где именно упал тест.
_TOUCHED = (
    "feedback_answers",
    "employee_achievements",
    "task_photos",
    "task_issues",
    "task_events",
    "tasks",
    "checklist_completions",
    "checklist_runs",
    "checklist_items",
    "checklist_templates",
    "app_notifications",
    "departments",
    "employees",
    "users",
)


async def _wipe(engine) -> None:
    """Очистить тестовую базу от следов прогона.

    Список таблиц фильтруем по фактической схеме: если миграция переименует
    таблицу, teardown не упадёт с `relation does not exist`, а просто её не
    тронет.
    """
    async with engine.begin() as conn:
        rows = await conn.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_schema = 'public'"
            )
        )
        existing = {row[0] for row in rows}
        names = [name for name in _TOUCHED if name in existing]
        await conn.execute(
            text("truncate " + ", ".join(names) + " restart identity cascade")
        )


@dataclass
class _Actor:
    """Кто «сидит в мини-аппе» прямо сейчас: ручки читают этого пользователя."""

    user: User


@dataclass
class Flow:
    """Контекст прогона.

    ВАЖНО: только id и пользователи-«актёры», без ORM-объектов. Ручки внутри
    делают `commit`/`rollback`, а rollback экспайрит ВСЕ объекты сессии; любое
    обращение к полю такого объекта дальше падало бы `MissingGreenlet` —
    именно на этом в проекте уже горели (`awards._guarded` + 500 в календаре).
    """

    session_factory: async_sessionmaker[AsyncSession]
    client: httpx.AsyncClient
    employee_user: User
    manager_user: User
    employee_name: str
    employee_id: int
    manager_id: int
    department_id: int
    template_id: int
    plain_item_id: int
    photo_item_id: int
    act_as: Callable[[User], None]


@dataclass
class _SeedIds:
    """Только первичные ключи заведённых записей."""

    employee_id: int
    manager_id: int
    department_id: int
    template_id: int
    plain_item_id: int
    photo_item_id: int


@dataclass
class _Seed:
    """Мини-ресторан, собранный для одного прогона."""

    department: Department
    template: ChecklistTemplate
    plain_item: ChecklistItem
    photo_item: ChecklistItem
    employee_user: User
    manager_user: User
    employee: Employee
    manager: Employee


def _make_user(telegram_id: int, name: str) -> User:
    return User(
        telegram_id=telegram_id,
        display_name=name,
        color_hex="#123456",
        timezone="Europe/Moscow",
    )


async def _seed(session: AsyncSession) -> _Seed:
    """Мини-ресторан внутри транзакции: подразделение, смена из двух пунктов, АУП."""
    dept = Department(name="Тестовый цех", slug="pg-test-dept", is_active=True, sort_order=1)
    session.add(dept)
    await session.flush()

    template = ChecklistTemplate(
        department_id=dept.id, title="Смена (интеграционный тест)", kind=TEMPLATE_SHIFT,
        is_active=True, sort_order=1,
    )
    session.add(template)
    await session.flush()

    plain = ChecklistItem(template_id=template.id, title="Переодеться в форму", sort_order=1)
    photo = ChecklistItem(
        template_id=template.id, title="Проверить маркировки", sort_order=2, requires_photo=True
    )
    session.add_all([plain, photo])

    employee_user = _make_user(810_000_101, "Тест Сотрудник")
    manager_user = _make_user(810_000_102, "Тест Управляющий")
    session.add_all([employee_user, manager_user])
    await session.flush()

    employee = Employee(
        user_id=employee_user.id, role=ROLE_EMPLOYEE, onboarding_state="new"
    )
    manager = Employee(user_id=manager_user.id, role=ROLE_AUP, department_id=dept.id)
    session.add_all([employee, manager])
    await session.flush()
    return _Seed(
        department=dept,
        template=template,
        plain_item=plain,
        photo_item=photo,
        employee_user=employee_user,
        manager_user=manager_user,
        employee=employee,
        manager=manager,
    )


@pytest.fixture
async def flow() -> AsyncIterator[Flow]:
    dsn = (os.environ.get(DSN_ENV) or "").strip()
    if not dsn:
        pytest.skip(
            f"нет {DSN_ENV}: живой тестовой Postgres нет (см. докстринг модуля)"
        )

    engine = _engine(dsn)
    try:
        # 1) База обязана быть на том же head, что и код: иначе тест мерил бы не ту схему.
        head = _code_head()
        async with engine.connect() as probe:
            version = await probe.scalar(text("select version_num from alembic_version"))
        assert version == head, (
            f"тестовая база не на head: в БД {version!r}, в коде {head!r} "
            "— прогоните `alembic upgrade head` на ней"
        )
        # 2) Чистая доска: база тестовая, но её мог оставить в мусоре прошлый упавший
        #    прогон — начинаем с пустых HR-таблиц, чтобы ассерты были детерминированы.
        await _wipe(engine)

        # 3) Заводим данные отдельной сессией и сразу отпускаем объекты
        #    (`expunge_all`): дальше тест работает только с id и с User-«актёром»,
        #    а каждая ручка получает СВОЮ сессию — как в бою.
        async with AsyncSession(bind=engine, expire_on_commit=False) as seeding:
            seed = await _seed(seeding)
            await seeding.commit()
            ids = _SeedIds(
                employee_id=seed.employee.id,
                manager_id=seed.manager.id,
                department_id=seed.department.id,
                template_id=seed.template.id,
                plain_item_id=seed.plain_item.id,
                photo_item_id=seed.photo_item.id,
            )
            seeding.expunge_all()

        app = create_app()
        actor = _Actor(user=seed.employee_user)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async def per_request_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[deps.db_session] = per_request_session
        app.dependency_overrides[deps.current_user] = lambda: actor.user
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            try:
                yield Flow(
                    session_factory=session_factory,
                    client=client,
                    employee_user=seed.employee_user,
                    manager_user=seed.manager_user,
                    employee_name=seed.employee_user.display_name,
                    employee_id=ids.employee_id,
                    manager_id=ids.manager_id,
                    department_id=ids.department_id,
                    template_id=ids.template_id,
                    plain_item_id=ids.plain_item_id,
                    photo_item_id=ids.photo_item_id,
                    act_as=lambda user: setattr(actor, "user", user),
                )
            finally:
                app.dependency_overrides.clear()
                await _wipe(engine)

        # 4) Следов не осталось — иначе тест «загрязнял» бы среду.
        async with engine.connect() as probe:
            left = await probe.scalar(text("select count(*) from employees"))
            deps_left = await probe.scalar(text("select count(*) from departments"))
        assert (left, deps_left) == (0, 0), (
            f"тест оставил строки: сотрудников {left}, подразделений {deps_left}"
        )
    finally:
        await engine.dispose()


async def test_employee_full_path_on_real_postgres(flow: Flow) -> None:
    """Онбординг → чек-лист → поручение с фото → скрытая ачивка → лента."""
    client = flow.client

    # --- 1. Первый запуск: профиль пустой, онбординг не пройден -------------
    r = await client.get("/api/me/employee")
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["onboarding_state"] == "new"
    assert me["department_id"] is None

    # --- 2. Шаги 2–3 онбординга: подразделение и опыт работы ---------------
    r = await client.post(
        "/api/me/onboarding",
        json={"department_id": flow.department_id, "experience": "new"},
    )
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["department_id"] == flow.department_id
    assert me["experience"] == "new"
    assert me["onboarding_state"] == ONBOARDING_DONE

    # --- 3. Чек-лист смены: пункты подразделения, прогресс пустой ----------
    r = await client.get("/api/checklist")
    assert r.status_code == 200, r.text
    checklist = r.json()
    assert checklist["template_id"] == flow.template_id
    assert checklist["run_id"] is None, "прогон создаётся только при первой отметке"
    assert [i["id"] for i in checklist["items"]] == [flow.plain_item_id, flow.photo_item_id]
    assert checklist["progress_text"]

    # Обычный пункт закрывается кнопкой.
    r = await client.post("/api/checklist/complete", json={"item_id": flow.plain_item_id})
    assert r.status_code == 200, r.text
    checklist = r.json()
    assert checklist["run_id"] is not None
    assert checklist["done"] == 1 and checklist["total"] == 2

    # Пункт с обязательным фотоотчётом без фото НЕ закрывается (п.3.5 брифа).
    r = await client.post("/api/checklist/complete", json={"item_id": flow.photo_item_id})
    assert r.status_code == 400
    assert r.json()["detail"] == "photo_required"

    # С фотоотчётом — закрывается, и прогон смены становится done.
    r = await client.post(
        "/api/checklist/complete",
        json={"item_id": flow.photo_item_id, "photo_file_id": "checklist-photo-1"},
    )
    assert r.status_code == 200, r.text
    checklist = r.json()
    assert checklist["status"] == "done"
    assert checklist["done"] == checklist["total"] == 2

    # --- 4. Поручение от АУП лично сотруднику, с обязательным фотоотчётом ---
    flow.act_as(flow.manager_user)
    r = await client.post(
        "/api/admin/tasks",
        json={
            "title": "Помыть холодильник",
            "scope": "employee",
            "assignee_employee_id": flow.employee_id,
            "description": "Полная разморозка и мойка",
            "expected_result": "Фото пустого чистого холодильника",
            "requires_photo": True,
            "priority": "high",
            "due_at": (datetime.now(UTC) + timedelta(hours=4)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["assignee_employee_id"] == flow.employee_id
    assert task["requires_photo"] is True

    # Сотрудник видит его в своём списке.
    flow.act_as(flow.employee_user)
    r = await client.get("/api/tasks")
    assert r.status_code == 200, r.text
    assert [t["id"] for t in r.json()] == [task["id"]]

    # Без фото поручение не закрывается...
    r = await client.post(f"/api/tasks/{task['id']}/done")
    assert r.status_code == 400
    assert r.json()["detail"] == "photo_report_required"

    # ...а с фотоотчётом закрывается само (п.4.4 брифа).
    r = await client.post(f"/api/tasks/{task['id']}/photo", json={"file_id": "task-photo-1"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == TASK_DONE

    # --- 5. Скрытая ачивка: сотруднику НЕ показываем, руководителю — да -----
    r = await client.get("/api/me/achievements")
    assert r.status_code == 200, r.text
    mine = r.json()
    assert mine["visible"] is False, "обычный сотрудник не видит блок прогресса"
    assert mine["awarded"] == []

    flow.act_as(flow.manager_user)
    r = await client.get(f"/api/admin/employees/{flow.employee_id}/achievements")
    assert r.status_code == 200, r.text
    boss_view = r.json()
    assert boss_view["visible"] is True
    codes = {a["code"] for a in boss_view["awarded"]}
    assert {"first_shift", "first_task"} <= codes, f"выданы не все заслуженные: {codes}"
    assert boss_view["stats"]["tasks_done"] == 1
    assert boss_view["stats"]["checklist_items"] == 2
    assert boss_view["stats"]["shift_days"] == 1

    # Повторное чтение не выдаёт ачивку дважды (идемпотентность на живой схеме).
    r = await client.get(f"/api/admin/employees/{flow.employee_id}/achievements")
    assert len(r.json()["awarded"]) == len(boss_view["awarded"])

    # --- 6. Лента: работа сотрудника видна ему самому -----------------------
    flow.act_as(flow.employee_user)
    r = await client.get("/api/feed")
    assert r.status_code == 200, r.text
    feed = r.json()
    assert feed["scope"] == "self"
    kinds = {item["kind"] for item in feed["items"]}
    # Поручение создал руководитель — «создано» в ленте СОТРУДНИКА и не должно
    # быть (иначе чужая работа висела бы в его личной ленте); ниже проверяем,
    # что у автора это событие есть.
    assert {
        "checklist_item",
        "checklist_done",
        "task_status",
        "task_photo",
    } <= kinds, f"в ленте не хватает событий: {kinds}"
    assert "task_created" not in kinds
    assert all(item["display_name"] == flow.employee_name for item in feed["items"])
    assert any("Помыть холодильник" in item["text"] for item in feed["items"])

    # --- 6b. KPI смены: опыт за работу, а не за приколы -------------------
    # Опыт считается из тех же следов, что уже записаны выше: 2 пункта
    # чек-листа, закрытая смена, поручение с фото и надбавка «в срок».
    flow.act_as(flow.employee_user)
    r = await client.get("/api/kpi")
    assert r.status_code == 200, r.text
    kpi = r.json()
    assert kpi["week_counts"] == {
        "checklist_items": 2,
        "shifts_done": 1,
        "tasks_done": 1,
        "tasks_on_time": 1,
    }, kpi["week_counts"]
    rules = kpi["rules"]
    assert kpi["xp"] == (
        2 * rules["xp_checklist_item"]
        + rules["xp_shift_done"]
        + rules["xp_task"]
        + rules["xp_on_time"]
    )
    assert kpi["rank"]["title"] == "Стажёр"
    assert kpi["week_place"] == 1 and kpi["week_total"] >= 1
    assert kpi["employee_of_week"]["employee_id"] == flow.employee_id

    # --- 7. У автора поручения видно, что он его поставил -------------------
    # (KPI выше уже проверил недельный рейтинг глазами сотрудника)

    flow.act_as(flow.manager_user)
    r = await client.get("/api/feed")
    assert r.status_code == 200, r.text
    boss_kinds = {item["kind"] for item in r.json()["items"]}
    assert "task_created" in boss_kinds
