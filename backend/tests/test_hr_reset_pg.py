"""Сброс текущей работы на ЖИВОЙ Postgres — сквозной тест, а не проверка правил.

Зачем отдельный файл. Юнит-тесты сброса (`test_hr_reset.py`) проверяют подпись
токена, границы и текст. Но самое опасное в этой кнопке — SQL: область прав,
JSONB-подзапрос уведомлений и каскады. Ошибку в имени колонки (`Issue.employee_id`
вместо `created_by_employee_id`) уже ловили руками на боевой базе — здесь она
падает сразу.

Что проверяем через настоящие ручки FastAPI и настоящую схему:

1. Демо-пул `[BOT]` не считается и не удаляется.
2. Поручение отдела и личное поручение руководителя попадают в сброс.
3. Каскады: отметки, события, фото, «не успеваю» по задаче, уведомления.
4. Чужой отдел не виден в предпросмотре и не удаляется чужим токеном.
5. Завершённые поручения и закрытые проблемы остаются.

Запуск — как у `test_hr_flow_pg.py`: нужна ПУСТАЯ тестовая база на `alembic head`
и `HR_FLOW_TEST_DSN`. Без него тест пропускается: боевая база здесь не нужна.
"""

from __future__ import annotations

import os
import ssl
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

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
    ISSUE_OPEN,
    ISSUE_RESOLVED,
    ROLE_AUP,
    ROLE_EMPLOYEE,
    TASK_DONE,
    TASK_NEW,
    TASK_OVERDUE,
    TASK_SCOPE_DEPARTMENT,
    TASK_SCOPE_EMPLOYEE,
    Department,
    Employee,
    Issue,
    Task,
    TaskAssignment,
    TaskEvent,
    TaskIssue,
    TaskPhoto,
)
from app.db.models import AppNotification, User  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import hr_reset  # noqa: E402

DSN_ENV = "HR_FLOW_TEST_DSN"
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _code_head() -> str:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"у миграций не один head: {heads}"
    return heads[0]


def _engine(dsn: str):  # noqa: ANN202 — AsyncEngine
    url = _normalize_url(dsn)
    connect_args: dict[str, object] = {"command_timeout": 60}
    if "asyncpg" in url and _ssl_enabled_for(url):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ctx
    return create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)


# Те же таблицы, что чистит `test_hr_flow_pg.py`: база выделенная, поэтому
# teardown не зависит от того, где именно упал тест.
_TOUCHED = (
    "hr_simulation_sessions",
    "feedback_answers",
    "employee_achievements",
    "hr_handover_items",
    "hr_handovers",
    "hr_issue_events",
    "hr_issues",
    "task_photos",
    "task_issues",
    "task_events",
    "task_assignments",
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


async def _wipe(engine) -> None:  # noqa: ANN001 — AsyncEngine
    async with engine.begin() as conn:
        rows = await conn.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_schema = 'public'"
            )
        )
        existing = {row[0] for row in rows}
        names = [name for name in _TOUCHED if name in existing]
        await conn.execute(text("truncate " + ", ".join(names) + " restart identity cascade"))


@dataclass
class _Actor:
    user: User


@dataclass(frozen=True)
class _Ids:
    dept_a: int
    dept_b: int
    manager_a: int
    manager_b: int
    employee_a: int
    employee_b: int
    task_dept_a: int
    task_personal_a: int
    task_dept_b: int
    task_demo: int
    task_done: int
    issue_open_a: int
    issue_resolved_a: int
    issue_open_b: int


@dataclass
class ResetFlow:
    client: httpx.AsyncClient
    session_factory: async_sessionmaker[AsyncSession]
    manager_a_user: User
    manager_b_user: User
    ids: _Ids
    act_as: Callable[[User], None]


def _user(telegram_id: int, name: str) -> User:
    return User(
        telegram_id=telegram_id,
        display_name=name,
        color_hex="#123456",
        timezone="Europe/Moscow",
    )


async def _seed(session: AsyncSession) -> tuple[_Ids, User, User]:
    dept_a = Department(name="Цех А", slug="reset-pg-a", is_active=True, sort_order=1)
    dept_b = Department(name="Цех Б", slug="reset-pg-b", is_active=True, sort_order=2)
    session.add_all([dept_a, dept_b])
    await session.flush()

    ua = _user(820_000_001, "АУП А")
    ub = _user(820_000_002, "АУП Б")
    ea = _user(820_000_003, "Сотрудник А")
    eb = _user(820_000_004, "Сотрудник Б")
    demo_user = _user(820_000_005, "[BOT] Симулятор")
    session.add_all([ua, ub, ea, eb, demo_user])
    await session.flush()

    manager_a = Employee(user_id=ua.id, role=ROLE_AUP, department_id=dept_a.id)
    manager_b = Employee(user_id=ub.id, role=ROLE_AUP, department_id=dept_b.id)
    employee_a = Employee(user_id=ea.id, role=ROLE_EMPLOYEE, department_id=dept_a.id)
    employee_b = Employee(user_id=eb.id, role=ROLE_EMPLOYEE, department_id=dept_b.id)
    demo = Employee(user_id=demo_user.id, role=ROLE_EMPLOYEE, department_id=dept_a.id, is_demo=True)
    session.add_all([manager_a, manager_b, employee_a, employee_b, demo])
    await session.flush()

    now = datetime.now(UTC)
    task_dept_a = Task(
        title="Поручение отдела А",
        scope=TASK_SCOPE_DEPARTMENT,
        department_id=dept_a.id,
        status=TASK_OVERDUE,
        due_at=now,
        created_by_employee_id=manager_a.id,
    )
    task_personal_a = Task(
        title="Личное поручение А",
        scope=TASK_SCOPE_EMPLOYEE,
        assignee_employee_id=employee_a.id,
        status=TASK_NEW,
        created_by_employee_id=manager_a.id,
    )
    task_dept_b = Task(
        title="Поручение отдела Б",
        scope=TASK_SCOPE_DEPARTMENT,
        department_id=dept_b.id,
        status=TASK_NEW,
        created_by_employee_id=manager_b.id,
    )
    task_demo = Task(
        title="Демо-задача",
        scope=TASK_SCOPE_EMPLOYEE,
        assignee_employee_id=demo.id,
        status=TASK_NEW,
        created_by_employee_id=manager_a.id,
    )
    task_done = Task(
        title="Уже закрыто",
        scope=TASK_SCOPE_DEPARTMENT,
        department_id=dept_a.id,
        status=TASK_DONE,
        done_at=now,
        created_by_employee_id=manager_a.id,
    )
    session.add_all([task_dept_a, task_personal_a, task_dept_b, task_demo, task_done])
    await session.flush()

    # Дети задач: всё это должно уйти каскадом вместе с t1.
    session.add_all(
        [
            TaskAssignment(task_id=task_dept_a.id, employee_id=employee_a.id, status=TASK_NEW),
            TaskEvent(
                task_id=task_dept_a.id,
                from_status=TASK_NEW,
                to_status=TASK_OVERDUE,
                comment="overdue",
            ),
            TaskPhoto(task_id=task_dept_a.id, employee_id=employee_a.id, file_id="photo-1"),
            TaskIssue(
                task_id=task_dept_a.id,
                employee_id=employee_a.id,
                reason_code="busy",
                comment="не успеваю",
            ),
            # У закрытой задачи — своя история: она должна остаться.
            TaskEvent(task_id=task_done.id, from_status=TASK_NEW, to_status=TASK_DONE),
        ]
    )
    session.add_all(
        [
            AppNotification(
                user_id=ua.id, kind="task_overdue", text="t1", payload={"task_id": task_dept_a.id}
            ),
            AppNotification(
                user_id=ua.id,
                kind="task_deadline",
                text="t2",
                payload={"task_id": task_personal_a.id},
            ),
            # Не про задачу — такие уведомления сброс не трогает.
            AppNotification(user_id=ua.id, kind="music_like", text="лайк", payload={"track_id": 7}),
        ]
    )

    today = date.today()
    issue_open_a = Issue(
        title="Течёт кран",
        department_id=dept_a.id,
        assignee_employee_id=employee_a.id,
        created_by_employee_id=employee_a.id,
        status=ISSUE_OPEN,
        shift_date=today,
    )
    issue_resolved_a = Issue(
        title="Старая проблема",
        department_id=dept_a.id,
        created_by_employee_id=manager_a.id,
        status=ISSUE_RESOLVED,
        shift_date=today,
    )
    issue_open_b = Issue(
        title="Проблема цеха Б",
        department_id=dept_b.id,
        created_by_employee_id=manager_b.id,
        status=ISSUE_OPEN,
        shift_date=today,
    )
    session.add_all([issue_open_a, issue_resolved_a, issue_open_b])
    await session.flush()

    ids = _Ids(
        dept_a=int(dept_a.id),
        dept_b=int(dept_b.id),
        manager_a=int(manager_a.id),
        manager_b=int(manager_b.id),
        employee_a=int(employee_a.id),
        employee_b=int(employee_b.id),
        task_dept_a=int(task_dept_a.id),
        task_personal_a=int(task_personal_a.id),
        task_dept_b=int(task_dept_b.id),
        task_demo=int(task_demo.id),
        task_done=int(task_done.id),
        issue_open_a=int(issue_open_a.id),
        issue_resolved_a=int(issue_resolved_a.id),
        issue_open_b=int(issue_open_b.id),
    )
    return ids, ua, ub


@pytest.fixture
async def reset_flow() -> AsyncIterator[ResetFlow]:
    dsn = (os.environ.get(DSN_ENV) or "").strip()
    if not dsn:
        pytest.skip(f"нет {DSN_ENV}: живой тестовой Postgres нет (см. докстринг модуля)")

    engine = _engine(dsn)
    try:
        head = _code_head()
        async with engine.connect() as probe:
            version = await probe.scalar(text("select version_num from alembic_version"))
        assert version == head, (
            f"тестовая база не на head: в БД {version!r}, в коде {head!r} "
            "— прогоните `alembic upgrade head` на ней"
        )
        await _wipe(engine)

        async with AsyncSession(bind=engine, expire_on_commit=False) as seeding:
            ids, ua, ub = await _seed(seeding)
            await seeding.commit()
            seeding.expunge_all()

        app = create_app()
        actor = _Actor(user=ua)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async def per_request_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[deps.db_session] = per_request_session
        app.dependency_overrides[deps.current_user] = lambda: actor.user
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            try:
                yield ResetFlow(
                    client=client,
                    session_factory=session_factory,
                    manager_a_user=ua,
                    manager_b_user=ub,
                    ids=ids,
                    act_as=lambda user: setattr(actor, "user", user),
                )
            finally:
                app.dependency_overrides.clear()
                await _wipe(engine)

        async with engine.connect() as probe:
            left = await probe.scalar(text("select count(*) from employees"))
        assert left == 0, f"тест оставил сотрудников: {left}"
    finally:
        await engine.dispose()


async def _count(factory: async_sessionmaker[AsyncSession], sql: str, **params: object) -> int:
    async with factory() as session:
        return int(await session.scalar(text(sql), params) or 0)


async def test_reset_double_confirm_on_real_postgres(reset_flow: ResetFlow) -> None:
    """Предпросмотр → отказ по чужому токену → удаление с каскадами."""
    client = reset_flow.client
    ids = reset_flow.ids

    # --- 1. Предпросмотр: только своё, демо и закрытое не считаются ----------
    r = await client.get("/api/admin/reset/preview")
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["is_admin"] is False
    assert preview["department_id"] == ids.dept_a
    assert preview["counts"]["tasks"] == 2, preview["counts"]
    assert preview["counts"]["issues"] == 1, preview["counts"]
    assert preview["counts"]["assignments"] == 1
    assert preview["counts"]["events"] == 1
    assert preview["counts"]["photos"] == 1
    assert preview["counts"]["notifications"] == 2
    token_a = preview["token"]

    # --- 2. Неверное слово: отказ без удаления -------------------------------
    # Регистр не важен («сброс» = «СБРОС»), важно само слово: «ОТМЕНА» — отказ.
    r = await client.post(
        "/api/admin/reset/execute", json={"token": token_a, "confirm": "ОТМЕНА"}
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "confirm_word_required"
    assert await _count(reset_flow.session_factory, "select count(*) from tasks") == 5

    # --- 3. Чужой отдел: предпросмотр не видит наши задачи -------------------
    reset_flow.act_as(reset_flow.manager_b_user)
    r = await client.get("/api/admin/reset/preview")
    assert r.status_code == 200, r.text
    foreign = r.json()
    assert foreign["department_id"] == ids.dept_b
    assert foreign["counts"]["tasks"] == 1, foreign["counts"]
    assert foreign["counts"]["issues"] == 1, foreign["counts"]

    # Токен, выданный руководителю А, чужому не подходит — и ничего не удаляет.
    r = await client.post(
        "/api/admin/reset/execute", json={"token": token_a, "confirm": "СБРОС"}
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "reset_preview_stale"
    assert await _count(reset_flow.session_factory, "select count(*) from tasks") == 5

    # --- 4. Своё подтверждение: удаляются ровно показанные задачи ------------
    reset_flow.act_as(reset_flow.manager_a_user)
    r = await client.post(
        "/api/admin/reset/execute", json={"token": token_a, "confirm": "СБРОС"}
    )
    assert r.status_code == 200, r.text
    counts = r.json()
    assert counts["tasks"] == 2 and counts["issues"] == 1, counts

    factory = reset_flow.session_factory
    ids_left = [
        int(v)
        for v in (
            await _collect(factory, "select id from tasks order by id")
        )
    ]
    assert ids_left == sorted([ids.task_dept_b, ids.task_demo, ids.task_done]), ids_left

    # Каскады: детей удалённых задач не осталось, у закрытой — остались.
    assert await _count(factory, "select count(*) from task_assignments") == 0
    assert await _count(factory, "select count(*) from task_photos") == 0
    assert await _count(factory, "select count(*) from task_issues") == 0
    assert (
        await _count(
            factory,
            "select count(*) from task_events where task_id = :t",
            t=ids.task_done,
        )
        == 1
    )
    # Уведомления по задачам удалены, постороннее («лайк») — нет.
    assert await _count(factory, "select count(*) from app_notifications") == 1
    assert (
        await _count(
            factory,
            "select count(*) from app_notifications where kind = 'music_like'",
        )
        == 1
    )

    # Проблемы: открытая своего отдела удалена, закрытая и чужая — остались.
    issues_left = [
        int(v) for v in (await _collect(factory, "select id from hr_issues order by id"))
    ]
    assert issues_left == sorted([ids.issue_resolved_a, ids.issue_open_b]), issues_left

    # --- 5. Повторный сброс: показывать нечего --------------------------------
    r = await client.get("/api/admin/reset/preview")
    assert r.status_code == 200, r.text
    again = r.json()
    assert again["counts"]["tasks"] == 0 and again["counts"]["issues"] == 0
    assert await _count(factory, "select count(*) from tasks") == 3
    assert hr_reset.CONFIRM_WORD == "СБРОС"


async def _collect(factory: async_sessionmaker[AsyncSession], sql: str) -> list[int]:
    async with factory() as session:
        rows = await session.execute(text(sql))
        return [int(row[0]) for row in rows]
