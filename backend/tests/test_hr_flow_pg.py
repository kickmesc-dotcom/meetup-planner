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
from datetime import UTC, date, datetime, timedelta

import pytest

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("ADMIN_TG_IDS", "")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import httpx  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
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
    ONBOARDING_TRAINING,
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
    "hr_handover_items",
    "hr_handovers",
    "hr_issue_events",
    "hr_issues",
    "task_photos",
    "task_issues",
    "task_events",
    "tasks",
    "checklist_completions",
    "checklist_runs",
    "checklist_items",
    "checklist_templates",
    "app_notifications",
    "hr_shifts",
    "employee_training_days",
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


async def _onboard_employee(flow: Flow) -> None:
    """Провести сотрудника через онбординг: без отдела он вне смены.

    Сид намеренно создаёт «пустого» новичка (его проверяет первый сценарий),
    поэтому сценариям про отдел нужно сначала выполнить те же два шага, что и
    человек в приложении, — иначе он не попадёт в групповое поручение и
    проблема останется без отдела.
    """
    flow.act_as(flow.employee_user)
    r = await flow.client.post(
        "/api/me/onboarding",
        json={"department_id": flow.department_id, "experience": "new"},
    )
    assert r.status_code == 200, r.text
    r = await flow.client.post("/api/me/onboarding", json={"finish": True})
    assert r.status_code == 200, r.text


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
    # После опыта идёт знакомство с приложением: его закрывает сам сотрудник —
    # либо уроками («Повторим вместе»), либо кнопкой «Я уже запомнил».
    assert me["onboarding_state"] == ONBOARDING_TRAINING
    assert me["learning_mode"] is False

    # «Повторим вместе»: знакомство закрыто, обучение продолжаем в смене.
    r = await client.post(
        "/api/me/onboarding",
        json={"finish": True, "learning_mode": True},
    )
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["onboarding_state"] == ONBOARDING_DONE
    assert me["learning_mode"] is True

    # Обратно в обычный режим можно вернуться из профиля — одним флагом.
    r = await client.post("/api/me/onboarding", json={"learning_mode": False})
    assert r.status_code == 200, r.text
    assert r.json()["learning_mode"] is False

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

    # --- 7б. Фильтр по конкретному человеку не подмешивает чужие действия ----
    # Симптом из живого приложения: выбрал одного сотрудника — в ленте остались
    # дела другого. Фильтр обязан сузить область и на сервере, а не только в UI.
    r = await client.get(f"/api/feed?employee_id={flow.employee_id}")
    assert r.status_code == 200, r.text
    filtered = r.json()["items"]
    assert filtered, "у сотрудника есть записи — фильтр не должен их терять"
    assert {item["employee_id"] for item in filtered} == {flow.employee_id}

    r = await client.get(f"/api/feed?employee_id={flow.manager_id}")
    assert r.status_code == 200, r.text
    only_boss = r.json()["items"]
    assert only_boss
    assert {item["employee_id"] for item in only_boss} == {flow.manager_id}


async def test_issue_journal_on_real_postgres(flow: Flow) -> None:
    """Журнал проблем: карточка переживает смену, права — на сервере."""
    client = flow.client
    await _onboard_employee(flow)

    # --- 1. Сотрудник заводит проблему, не привязанную к поручению ---------
    flow.act_as(flow.employee_user)
    r = await client.post(
        "/api/issues",
        json={
            "title": "Не работает терминал на баре",
            "description": "Перезагружали — не помогло",
            "category": "equipment",
            "zone": "бар",
            "severity": "high",
        },
    )
    assert r.status_code == 201, r.text
    issue = r.json()
    assert issue["status"] == "open"
    assert issue["created_by_employee_id"] == flow.employee_id
    assert issue["department_id"] == flow.department_id
    assert issue["severity"] == "high"
    assert issue["can_edit"] is True and issue["can_close"] is True
    # Отдел автора виден сразу: журнал общий для смены.
    assert [event["kind"] for event in issue["events"]] == ["created"]

    # --- 2. Счётчики и видимость у руководителя ----------------------------
    r = await client.get("/api/issues")
    assert r.status_code == 200, r.text
    listing = r.json()
    assert listing["scope"] == "department"
    assert listing["summary"]["total_open"] == 1
    assert listing["summary"]["attention"] == 1
    assert [item["id"] for item in listing["items"]] == [issue["id"]]

    # Уведомление легло руководителю в колокольчик (в Telegram не шлём).
    async with flow.session_factory() as session:
        bell = await session.scalar(
            text(
                "select count(*) from app_notifications "
                "where user_id = :uid and kind = 'issue_created'"
            ),
            {"uid": flow.manager_user.id},
        )
    assert bell == 1

    # --- 3. Сотрудник не может назначить проблему на коллегу ----------------
    r = await client.patch(
        f"/api/issues/{issue['id']}",
        json={"assignee_employee_id": flow.manager_id, "assignee_set": True},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "assignee_forbidden"

    # --- 4. Руководитель берёт в работу и закрывает ------------------------
    flow.act_as(flow.manager_user)
    r = await client.post(
        f"/api/issues/{issue['id']}/status",
        json={"status": "in_progress", "comment": "вызвал мастера"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_progress"

    r = await client.post(
        f"/api/issues/{issue['id']}/comments", json={"text": "мастер будет к 18:00"}
    )
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["events"][-1]["kind"] == "comment"
    assert detail["events"][-1]["comment"] == "мастер будет к 18:00"

    r = await client.post(
        f"/api/issues/{issue['id']}/status",
        json={"status": "resolved", "comment": "терминал заменён"},
    )
    assert r.status_code == 200, r.text
    resolved = r.json()
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None
    # Карточка осталась в истории: закрытая не исчезает из журнала.
    r = await client.get("/api/issues?include_closed=true")
    assert r.status_code == 200, r.text
    assert [item["id"] for item in r.json()["items"]] == [issue["id"]]

    # --- 5. Сотрудник не переоткрывает, руководитель — может ---------------
    flow.act_as(flow.employee_user)
    r = await client.post(
        f"/api/issues/{issue['id']}/status", json={"status": "open"}
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "forbidden"

    flow.act_as(flow.manager_user)
    r = await client.post(
        f"/api/issues/{issue['id']}/status", json={"status": "open"}
    )
    assert r.status_code == 200, r.text
    reopened = r.json()
    assert reopened["status"] == "open"
    assert reopened["resolved_at"] is None
    assert [event["kind"] for event in reopened["events"]][-1] == "status"

    # --- 6. Подделанные коды отклоняются -----------------------------------
    r = await client.post(
        "/api/issues", json={"title": "Тест", "category": "nonsense"}
    )
    assert r.status_code == 400
    r = await client.post(
        f"/api/issues/{issue['id']}/status", json={"status": "done"}
    )
    assert r.status_code == 400
    # Чужой id не подтверждаем — 404, а не 403.
    r = await client.get("/api/issues/999999")
    assert r.status_code == 404


async def test_handover_on_real_postgres(flow: Flow) -> None:
    """Передача смены: снимок открытых хвостов и подтверждение принимающим."""
    client = flow.client

    # --- 1. Руководитель ставит открытое поручение -------------------------
    flow.act_as(flow.manager_user)
    r = await client.post(
        "/api/admin/tasks",
        json={
            "title": "Сверить остатки на складе",
            "scope": "employee",
            "assignee_employee_id": flow.employee_id,
        },
    )
    assert r.status_code == 200, r.text

    # --- 2. Сотрудник видит, что уйдёт в сдачу -----------------------------
    flow.act_as(flow.employee_user)
    r = await client.get("/api/handovers/preview")
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["tasks"] == 1 and preview["issues"] == 0, preview
    assert preview["items"][0]["title"] == "Сверить остатки на складе"

    r = await client.get("/api/handovers/colleagues")
    assert r.status_code == 200, r.text
    assert [c["id"] for c in r.json()] == [flow.manager_id]

    r = await client.post(
        "/api/handovers/{0}/accept".format(999999), json={}
    )
    assert r.status_code == 404, "чужую сдачу нельзя даже подтвердить"

    # Себе сдать нельзя.
    r = await client.post(
        "/api/handovers", json={"to_employee_id": flow.employee_id}
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "handover_to_self"

    # --- 3. Сдача следующему -----------------------------------------------
    r = await client.post(
        "/api/handovers",
        json={
            "to_employee_id": flow.manager_id,
            "note": "Склад закрыт, ключ у охраны",
        },
    )
    assert r.status_code == 201, r.text
    card = r.json()
    assert card["status"] == "sent"
    assert card["items_count"] == 1
    assert card["from_employee_id"] == flow.employee_id
    assert card["to_employee_id"] == flow.manager_id
    assert card["can_accept"] is False, "сдающий не подтверждает сам себе"
    assert card["note"] == "Склад закрыт, ключ у охраны"

    # Входящая у принимающего и уведомление в колокольчике.
    flow.act_as(flow.manager_user)
    r = await client.get("/api/handovers?box=incoming")
    assert r.status_code == 200, r.text
    inbox = r.json()
    assert [item["id"] for item in inbox["items"]] == [card["id"]]
    assert inbox["summary"]["pending"] == 1
    assert inbox["items"][0]["can_accept"] is True

    async with flow.session_factory() as session:
        bell = await session.scalar(
            text(
                "select count(*) from app_notifications "
                "where user_id = :uid and kind = 'handover_sent'"
            ),
            {"uid": flow.manager_user.id},
        )
    assert bell == 1

    # --- 4. Подтверждение принимающим --------------------------------------
    r = await client.post(f"/api/handovers/{card['id']}/accept", json={})
    assert r.status_code == 200, r.text
    accepted = r.json()
    assert accepted["status"] == "accepted"
    assert accepted["accepted_by_employee_id"] == flow.manager_id
    assert accepted["accepted_at"] is not None
    # Повторно принять уже нечего.
    r = await client.post(f"/api/handovers/{card['id']}/accept", json={})
    assert r.status_code == 400

    flow.act_as(flow.employee_user)
    r = await client.get("/api/handovers?box=outgoing")
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["status"] == "accepted"

    # --- 5. Возврат с причиной ---------------------------------------------
    r = await client.post(
        "/api/handovers", json={"to_employee_id": flow.manager_id}
    )
    assert r.status_code == 201, r.text
    second = r.json()

    flow.act_as(flow.manager_user)
    r = await client.post(
        f"/api/handovers/{second['id']}/reject", json={"reason": ""}
    )
    assert r.status_code == 422, "пустая причина не проходит валидацию"
    r = await client.post(
        f"/api/handovers/{second['id']}/reject",
        json={"reason": "Не мой отдел, передай бармену"},
    )
    assert r.status_code == 200, r.text
    rejected = r.json()
    assert rejected["status"] == "rejected"
    assert rejected["reject_reason"] == "Не мой отдел, передай бармену"


async def test_group_task_modes_on_real_postgres(flow: Flow) -> None:
    """Групповое поручение: режимы, смена, личные отметки и один опыт за работу."""
    from app.services import hr_checklists

    client = flow.client
    await _onboard_employee(flow)
    today = hr_checklists.local_today().isoformat()

    # --- 1. Руководитель выдаёт поручение на смену в режиме «каждый сам» ----
    flow.act_as(flow.manager_user)
    r = await client.post(
        "/api/admin/tasks",
        json={
            "title": "Помыть витрину",
            "scope": "department",
            "department_id": flow.department_id,
            "mode": "each",
            "shift_date": today,
        },
    )
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["mode"] == "each"
    assert task["shift_date"] == today
    # В подразделении двое: сотрудник и сам руководитель.
    assert task["progress_total"] == 2
    assert task["progress_done"] == 0
    assert {a["status"] for a in task["assignments"]} == {"new"}

    # --- 2. Сотрудник видит свой личный статус, а не только общий ----------
    flow.act_as(flow.employee_user)
    r = await client.get(f"/api/tasks?shift_date={today}")
    assert r.status_code == 200, r.text
    mine = r.json()
    assert [t["id"] for t in mine] == [task["id"]]
    assert mine[0]["my_status"] == "new"
    assert mine[0]["progress_total"] == 2
    # Другой смены — ничего лишнего.
    r = await client.get("/api/tasks?shift_date=2000-01-01")
    assert r.json() == []

    # --- 3. Отметка одного исполнителя не закрывает общее поручение --------
    for action in ("accept", "start", "done"):
        r = await client.post(f"/api/tasks/{task['id']}/{action}")
        assert r.status_code == 200, r.text
    after = r.json()
    assert after["my_status"] == "done"
    assert after["progress_done"] == 1
    assert after["status"] == "in_progress", "второй ещё не отметился"
    assert after["is_overdue"] is False

    # --- 4. Руководитель закрывает свою часть — задача закрыта целиком -----
    flow.act_as(flow.manager_user)
    r = await client.get(f"/api/tasks?shift_date={today}")
    assert r.json()[0]["my_status"] == "new"
    r = await client.post(f"/api/tasks/{task['id']}/start")
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/tasks/{task['id']}/done")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done"

    # --- 5. Опыт за работу не задваивается агрегатом -----------------------
    flow.act_as(flow.employee_user)
    r = await client.get("/api/kpi")
    assert r.status_code == 200, r.text
    assert r.json()["week_counts"]["tasks_done"] == 1, (
        "агрегат задачи не должен начислять второй опыт за ту же работу"
    )

    # --- 6. Админский список: прогресс по смене -----------------------------
    flow.act_as(flow.manager_user)
    r = await client.get(f"/api/admin/tasks?shift_date={today}")
    assert r.status_code == 200, r.text
    admin_rows = r.json()
    assert [t["id"] for t in admin_rows] == [task["id"]]
    assert admin_rows[0]["progress_done"] == admin_rows[0]["progress_total"] == 2
    assert all(a["display_name"] != "—" for a in admin_rows[0]["assignments"])

    # Поручение «части работы» требует текста части и отвергает чужой режим.
    r = await client.post(
        "/api/admin/tasks",
        json={
            "title": "Разобрать поставку",
            "scope": "department",
            "department_id": flow.department_id,
            "mode": "parts",
            "shift_date": today,
            "parts": {flow.employee_id: "овощи", flow.manager_id: "молочка"},
        },
    )
    assert r.status_code == 200, r.text
    parts_task = r.json()
    labels = {a["employee_id"]: a["part"] for a in parts_task["assignments"]}
    assert labels[flow.employee_id] == "овощи"
    assert labels[flow.manager_id] == "молочка"

    flow.act_as(flow.employee_user)
    r = await client.get(f"/api/tasks?shift_date={today}")
    own = next(t for t in r.json() if t["id"] == parts_task["id"])
    assert own["my_part"] == "овощи", "исполнитель видит свою часть работы"

    # Кривой режим проверяет автор поручения: у сотрудника ручка отклонится
    # раньше — на правах (403), и до валидации `mode` дело не дойдёт.
    flow.act_as(flow.manager_user)
    r = await client.post(
        "/api/admin/tasks",
        json={"title": "Кривой режим", "scope": "department",
              "department_id": flow.department_id, "mode": "nonsense"},
    )
    assert r.status_code == 400


async def test_admin_ops_on_real_postgres(flow: Flow) -> None:
    """Админские операции: журнал, центр уведомлений и увольнение с корзиной.

    Проверяем ровно то, что болит в живом приложении: системные строки видны
    только в админском журнале, «последние действия» руководителя без них,
    запланированное напоминание видно заранее, пул сотрудников правится, а
    увольнение закрывает доступ и возвращается из корзины.
    """
    from app.db.hr_models import (
        ROLE_ADMIN,
        TASK_DONE,
        TASK_FAILED,
        TASK_NEW,
        TaskAssignment,
    )

    client = flow.client
    await _onboard_employee(flow)

    # 0. Руководителю выдаём админскую роль: увольнение и центр уведомлений —
    #    админские операции, а сид заводит только сотрудника и АУП.
    async with flow.session_factory() as session:
        manager = await session.get(Employee, flow.manager_id)
        assert manager is not None
        manager.role = ROLE_ADMIN
        await session.commit()

    # 1. Поручение со сроком в будущем: по нему должно быть видно напоминание.
    flow.act_as(flow.manager_user)
    due = datetime.now(UTC) + timedelta(hours=4)
    r = await client.post(
        "/api/admin/tasks",
        json={
            "title": "Проверить срок годности",
            "scope": "employee",
            "assignee_employee_id": flow.employee_id,
            "due_at": due.isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    # 2. Центр уведомлений: запланированное напоминание по этой задаче.
    r = await client.get("/api/admin/notifications")
    assert r.status_code == 200, r.text
    feed = r.json()
    planned = [
        item for item in feed["pending"] if item["task_id"] == task_id
    ]
    assert planned, feed["pending"]
    assert planned[0]["kind"] == "deadline"
    assert planned[0]["at"] < due.isoformat(), "напоминание идёт до срока"
    assert planned[0]["moved"] is False

    # 2a. «Передвинуть»: время сдвигается, срок поручения не меняется.
    was_at = datetime.fromisoformat(planned[0]["at"])
    r = await client.post(
        f"/api/admin/notifications/pending/{task_id}/postpone",
        json={"minutes": 30},
    )
    assert r.status_code == 200, r.text
    moved_at = datetime.fromisoformat(r.json()["at"])
    assert moved_at > was_at

    r = await client.get("/api/admin/notifications")
    moved = [item for item in r.json()["pending"] if item["task_id"] == task_id]
    assert moved and moved[0]["moved"] is True
    assert datetime.fromisoformat(moved[0]["at"]) == moved_at

    # 2b. «Выключить»: из «запланировано» уходит в «выключено» и возвращается.
    r = await client.post(
        f"/api/admin/notifications/pending/{task_id}/skip"
    )
    assert r.status_code == 200, r.text
    r = await client.get("/api/admin/notifications")
    assert not [item for item in r.json()["pending"] if item["task_id"] == task_id]
    assert any(item["task_id"] == task_id for item in r.json()["disabled"])

    r = await client.post(
        f"/api/admin/notifications/pending/{task_id}/reset"
    )
    assert r.status_code == 200, r.text
    r = await client.get("/api/admin/notifications")
    back = [item for item in r.json()["pending"] if item["task_id"] == task_id]
    assert back and back[0]["moved"] is False
    assert not [item for item in r.json()["disabled"] if item["task_id"] == task_id]

    # 3. Журнал: человекопонятная строка создания поручения.
    r = await client.get("/api/admin/journal")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    created = [item for item in items if item["task_id"] == task_id]
    assert created, items[:5]
    assert any("поручение" in item["text"] for item in created)
    assert all(":" not in item["text"][:9] for item in created), (
        "в журнале не должно быть сырых кодов вроде created:employee"
    )

    # 4. «Последние действия» руководителя — без системных строк.
    r = await client.get("/api/admin/dashboard")
    assert r.status_code == 200, r.text
    activity = r.json()["activity"]
    assert activity, "действие человека должно остаться в сводке"
    assert all("авто" not in item["text"] for item in activity)
    assert all(item["display_name"] for item in activity)

    # 5. Пул сотрудников: переименование и обнуление прогресса.
    r = await client.patch(
        f"/api/admin/employees/{flow.employee_id}",
        json={"position": "Су-шеф", "badge": "Стажёр"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["position"] == "Су-шеф"
    assert r.json()["badge"] == "Стажёр"

    r = await client.post(
        f"/api/admin/employees/{flow.employee_id}/reset-progress"
    )
    assert r.status_code == 200, r.text
    assert r.json()["onboarding_state"] == "new"
    assert r.json()["learning_mode"] is False

    # 6. Зачесть проваленное поручение выполненных вручную.
    async with flow.session_factory() as session:
        assignment = await session.scalar(
            select(TaskAssignment).where(
                TaskAssignment.task_id == task_id,
                TaskAssignment.employee_id == flow.employee_id,
            )
        )
        assert assignment is not None and assignment.status == TASK_NEW
        assignment.status = TASK_FAILED
        await session.commit()

    r = await client.post(
        f"/api/admin/tasks/{task_id}/force-done",
        json={"employee_id": flow.employee_id, "comment": "сделал под контролем"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == TASK_DONE

    # 7. Увольнение в корзину: доступ закрыт, но данные на месте.
    r = await client.post(
        f"/api/admin/employees/{flow.employee_id}/fire", json={"mode": "trash"}
    )
    assert r.status_code == 200, r.text
    fired = r.json()
    assert fired["fired_at"] is not None and fired["purge_after"] is not None

    flow.act_as(flow.employee_user)
    r = await client.get("/api/me/employee")
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "employee_fired"

    flow.act_as(flow.manager_user)
    r = await client.get("/api/admin/employees-pool")
    assert r.status_code == 200, r.text
    cards = {card["employee_id"]: card for card in r.json()["items"]}
    assert cards[flow.employee_id]["is_active"] is False

    r = await client.post(
        f"/api/admin/employees/{flow.employee_id}/restore"
    )
    assert r.status_code == 200, r.text
    assert r.json()["fired_at"] is None

    flow.act_as(flow.employee_user)
    r = await client.get("/api/me/employee")
    assert r.status_code == 200, r.text

    # 8. Удаление сразу: восстановить уже нельзя.
    flow.act_as(flow.manager_user)
    r = await client.post(
        f"/api/admin/employees/{flow.employee_id}/fire", json={"mode": "purge"}
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/admin/employees/{flow.employee_id}/restore"
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "already_purged"


async def test_training_plan_on_real_postgres(flow: Flow) -> None:
    """Расписание учебных смен и ставка: правка, точечный день и сегодняшний флаг.

    Проверяем то, ради чего план заводили: учебные смены идут по дням, а не
    одним флагом на профиль; управляющий может переключить конкретный день и
    вернуть правило, а сотрудник видит «сегодня учебная смена» в своём экране.
    """
    client = flow.client
    await _onboard_employee(flow)

    today = date.today()
    async with flow.session_factory() as session:
        employee = await session.get(Employee, flow.employee_id)
        assert employee is not None
        employee.hire_date = today
        employee.training_days = 3
        employee.rate_type = "full"
        await session.commit()

    flow.act_as(flow.manager_user)
    r = await client.get("/api/admin/training-plan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["start"] == today.isoformat()
    plan = {item["employee_id"]: item for item in body["items"]}[flow.employee_id]
    assert plan["rate_type"] == "full"
    assert plan["training_days"] == 3
    assert len(plan["days"]) == 14
    by_day = {item["day"]: item for item in plan["days"]}
    assert by_day[today.isoformat()]["is_training"] is True
    assert by_day[today.isoformat()]["explicit"] is False
    assert by_day[(today + timedelta(days=2)).isoformat()]["is_training"] is True
    assert by_day[(today + timedelta(days=3)).isoformat()]["is_training"] is False

    # Ставка и число первых учебных смен.
    r = await client.patch(
        f"/api/admin/training-plan/{flow.employee_id}",
        json={"rate_type": "partial", "training_days": 2},
    )
    assert r.status_code == 200, r.text
    assert r.json()["rate_type"] == "partial"
    assert r.json()["training_days"] == 2

    # Точечное исключение сильнее правила.
    r = await client.put(
        f"/api/admin/training-plan/{flow.employee_id}/days/{today.isoformat()}",
        json={"is_training": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["explicit"] is True

    r = await client.get("/api/admin/training-plan")
    plan = {item["employee_id"]: item for item in r.json()["items"]}[flow.employee_id]
    day = {item["day"]: item for item in plan["days"]}[today.isoformat()]
    assert day["is_training"] is False and day["explicit"] is True

    flow.act_as(flow.employee_user)
    r = await client.get("/api/me/training")
    assert r.status_code == 200, r.text
    assert r.json()["today_training"] is False
    assert r.json()["rate_type"] == "partial"

    # Убрать правило — день снова считается по «первым N сменам».
    flow.act_as(flow.manager_user)
    r = await client.delete(
        f"/api/admin/training-plan/{flow.employee_id}/days/{today.isoformat()}"
    )
    assert r.status_code == 200, r.text
    flow.act_as(flow.employee_user)
    r = await client.get("/api/me/training")
    assert r.json()["today_training"] is True


async def test_shifts_timesheet_and_training_by_work(flow: Flow) -> None:
    """Табель: сетка по отделам, перенос и учебные смены по факту работы.

    Учебные смены больше не считаются календарём: больничный и пропуск не
    съедают учебную, а перенесённая отработанная смена остаётся в счёте.
    """
    client = flow.client
    await _onboard_employee(flow)
    today = date.today()

    async with flow.session_factory() as session:
        employee = await session.get(Employee, flow.employee_id)
        assert employee is not None
        employee.hire_date = today - timedelta(days=10)
        employee.training_days = 2
        await session.commit()

    # Второе подразделение: управляющий должен видеть все отделы.
    async with flow.session_factory() as session:
        other_dept = Department(name="Тестовый бар", slug="test-bar-shifts")
        session.add(other_dept)
        await session.flush()
        other_user = _make_user(810_000_777, "Тест Бармен")
        session.add(other_user)
        await session.flush()
        session.add(
            Employee(
                user_id=other_user.id,
                role=ROLE_EMPLOYEE,
                department_id=other_dept.id,
            )
        )
        await session.commit()

    flow.act_as(flow.manager_user)
    first_worked = today - timedelta(days=3)
    sick_day = today - timedelta(days=2)
    second_worked = today - timedelta(days=1)
    future_shift = today + timedelta(days=1)

    for day in (first_worked, second_worked):
        r = await client.put(
            f"/api/shifts/{flow.employee_id}/{day.isoformat()}",
            json={"status": "worked", "starts_at": "10:00", "ends_at": "22:00"},
        )
        assert r.status_code == 200, r.text
    r = await client.put(
        f"/api/shifts/{flow.employee_id}/{sick_day.isoformat()}",
        json={"status": "sick", "note": "температура"},
    )
    assert r.status_code == 200, r.text
    r = await client.put(
        f"/api/shifts/{flow.employee_id}/{future_shift.isoformat()}",
        json={"status": "planned", "starts_at": "10:00"},
    )
    assert r.status_code == 200, r.text

    start = today - timedelta(days=4)
    r = await client.get(f"/api/shifts?start={start.isoformat()}&days=7")
    assert r.status_code == 200, r.text
    week = r.json()
    assert week["can_edit"] is True
    assert any(
        person["department_name"] == "Тестовый бар" for person in week["people"]
    )

    r = await client.get(
        f"/api/shifts?start={start.isoformat()}&days=7"
        f"&department_id={flow.department_id}"
    )
    filtered = r.json()
    assert all(
        person["department_id"] == flow.department_id
        for person in filtered["people"]
    )

    rows = {
        (item["employee_id"], item["day"]): item for item in week["shifts"]
    }
    assert rows[(flow.employee_id, first_worked.isoformat())]["is_training"] is True
    assert rows[(flow.employee_id, sick_day.isoformat())]["is_training"] is False
    assert rows[(flow.employee_id, second_worked.isoformat())]["is_training"] is True
    assert rows[(flow.employee_id, future_shift.isoformat())]["is_training"] is False
    assert rows[(flow.employee_id, second_worked.isoformat())]["starts_at"] == "10:00"

    # Перенос: вчерашняя смена → сегодня, история сохраняется.
    shift_id = rows[(flow.employee_id, second_worked.isoformat())]["id"]
    r = await client.post(
        f"/api/shifts/{shift_id}/move", json={"day": today.isoformat()}
    )
    assert r.status_code == 200, r.text
    moved = r.json()
    assert moved["day"] == today.isoformat()
    assert moved["moved_from"] == second_worked.isoformat()
    assert moved["is_training"] is True

    # План читает табель: planned на завтра — третья смена, уже обычная.
    r = await client.get("/api/admin/training-plan")
    plan = {item["employee_id"]: item for item in r.json()["items"]}[flow.employee_id]
    assert plan["has_shifts"] is True
    tomorrow = {item["day"]: item for item in plan["days"]}[future_shift.isoformat()]
    assert tomorrow["is_training"] is False
    assert tomorrow["shift_status"] == "planned"

    # Сотрудник видит коллег своего отдела, но править не может.
    flow.act_as(flow.employee_user)
    r = await client.get(f"/api/shifts?start={start.isoformat()}&days=7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_edit"] is False
    assert all(
        person["department_id"] == flow.department_id for person in body["people"]
    )
    r = await client.put(
        f"/api/shifts/{flow.employee_id}/{today.isoformat()}",
        json={"status": "worked"},
    )
    assert r.status_code == 403
