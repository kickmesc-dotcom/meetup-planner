"""Режим проверки на ЖИВОЙ Postgres: изоляция, очистка, чужой доступ.

Проверяем не «правила», а настоящий путь через FastAPI и схему:

1. Админ открывает сеанс от имени сотрудника (теневой профиль).
2. Запросы с `X-Simulation-Session` идут от теневого профиля: онбординг и
   задачи — свои, реальные задачи сотрудника не видны.
3. Теневой профиль не появляется в списках и журнале реальных людей.
4. Выход удаляет тестовые задачи, смены и проблемы, но не реальные данные;
   аудит-запись остаётся, повторный выход идемпотентен.

Без `HR_FLOW_TEST_DSN` тест пропускается: боевая база здесь не нужна.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("ADMIN_TG_IDS", "")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import httpx  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: E402

from app.api import deps  # noqa: E402
from app.db.hr_models import (  # noqa: E402
    ONBOARDING_DONE,
    Issue,
    ROLE_ADMIN,
    ROLE_AUP,
    TASK_NEW,
    TASK_SCOPE_EMPLOYEE,
    Department,
    Employee,
    SimulationSession,
    Task,
)
from app.db.models import AppNotification, User  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.test_hr_reset_pg import DSN_ENV, _code_head, _engine, _wipe  # noqa: E402


@dataclass
class _Actor:
    user: User


@dataclass(frozen=True)
class _Ids:
    department_id: int
    admin_employee_id: int
    subject_employee_id: int
    real_task_id: int
    real_issue_id: int


@dataclass
class SimFlow:
    client: httpx.AsyncClient
    session_factory: async_sessionmaker[AsyncSession]
    admin_user: User
    subject_user: User
    ids: _Ids

    def as_simulation(self, session_id: int) -> dict[str, str]:
        return {"X-Simulation-Session": str(session_id)}


def _user(telegram_id: int, name: str) -> User:
    return User(
        telegram_id=telegram_id,
        display_name=name,
        color_hex="#123456",
        timezone="Europe/Moscow",
    )


async def _seed(session: AsyncSession) -> tuple[_Ids, User, User]:
    dept = Department(name="Цех проверки", slug="sim-pg", is_active=True, sort_order=1)
    session.add(dept)
    await session.flush()

    admin_user = _user(830_000_001, "Проверяющий")
    subject_user = _user(830_000_002, "Проверяемый")
    session.add_all([admin_user, subject_user])
    await session.flush()

    admin = Employee(user_id=admin_user.id, role=ROLE_ADMIN)
    subject = Employee(
        user_id=subject_user.id,
        role=ROLE_AUP,
        department_id=dept.id,
        onboarding_state=ONBOARDING_DONE,
        experience="experienced",
    )
    session.add_all([admin, subject])
    await session.flush()

    real_task = Task(
        title="Настоящая задача сотрудника",
        scope=TASK_SCOPE_EMPLOYEE,
        assignee_employee_id=subject.id,
        created_by_employee_id=admin.id,
        status=TASK_NEW,
        due_at=datetime.now(UTC),
    )
    session.add(real_task)
    real_issue = Issue(
        title="Настоящая проблема отдела",
        category="other",
        severity="normal",
        department_id=dept.id,
        created_by_employee_id=subject.id,
        shift_date=date.today(),
    )
    session.add(real_issue)
    await session.flush()
    return (
        _Ids(
            department_id=int(dept.id),
            admin_employee_id=int(admin.id),
            subject_employee_id=int(subject.id),
            real_task_id=int(real_task.id),
            real_issue_id=int(real_issue.id),
        ),
        admin_user,
        subject_user,
    )


@pytest.fixture
async def sim_flow() -> AsyncIterator[SimFlow]:
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
            ids, admin_user, subject_user = await _seed(seeding)
            await seeding.commit()
            seeding.expunge_all()

        app = create_app()
        actor = _Actor(user=admin_user)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async def per_request_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[deps.db_session] = per_request_session
        app.dependency_overrides[deps.current_user] = lambda: actor.user
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            try:
                yield SimFlow(
                    client=client,
                    session_factory=session_factory,
                    admin_user=admin_user,
                    subject_user=subject_user,
                    ids=ids,
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


async def test_simulation_isolation_and_cleanup(sim_flow: SimFlow) -> None:
    client = sim_flow.client
    ids = sim_flow.ids

    # --- 1. Старт: только админ, теневой профиль создан -----------------------
    r = await client.post(
        "/api/admin/simulation",
        json={"employee_id": ids.subject_employee_id, "mode": "as_is"},
    )
    assert r.status_code == 201, r.text
    session = r.json()
    session_id = session["id"]
    shadow_id = session["shadow_employee_id"]
    assert shadow_id != ids.subject_employee_id
    assert session["subject_name"] == "Проверяемый"

    # --- 2. Запросы с заголовком идут от теневого профиля --------------------
    headers = sim_flow.as_simulation(session_id)
    r = await client.get("/api/me/employee", headers=headers)
    assert r.status_code == 200, r.text
    shadow_me = r.json()
    assert shadow_me["id"] == shadow_id
    assert shadow_me["display_name"] == "Проверяемый"
    assert shadow_me["department_id"] == ids.department_id
    # Реальная задача сотрудника в сеанс не подмешивается.
    r = await client.get("/api/tasks", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == []

    # --- 3. Тестовая задача создаётся только «себе» ---------------------------
    r = await client.post(
        "/api/admin/tasks",
        headers=headers,
        json={
            "title": "Тестовая задача сеанса",
            "scope": "employee",
            "assignee_employee_id": shadow_id,
        },
    )
    assert r.status_code == 200, r.text
    test_task_id = r.json()["id"]

    # Чужому человеку — отказ: песочница не должна ставить реальные задачи.
    r = await client.post(
        "/api/admin/tasks",
        headers=headers,
        json={
            "title": "Задача живому человеку",
            "scope": "employee",
            "assignee_employee_id": ids.subject_employee_id,
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "simulation_self_only"

    r = await client.get("/api/tasks", headers=headers)
    assert [t["id"] for t in r.json()] == [test_task_id]

    # --- 4. Проблема сеанса не попадает в общий журнал ------------------------
    r = await client.post(
        "/api/issues",
        headers=headers,
        json={"title": "Тестовая проблема", "category": "other", "severity": "normal"},
    )
    assert r.status_code == 201, r.text
    issue_id = r.json()["id"]

    # --- 4.1. Запись в реальные карточки и приёмка запрещены -----------------
    r = await client.patch(
        f"/api/issues/{ids.real_issue_id}",
        headers=headers,
        json={"title": "Подменённая проблема"},
    )
    assert r.status_code == 404, r.text

    r = await client.post(
        f"/api/tasks/{ids.real_task_id}/review",
        headers=headers,
        json={"approve": True},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "simulation_self_only"

    r = await client.post(
        "/api/handovers",
        headers=headers,
        json={"to_employee_id": ids.subject_employee_id, "note": "тест"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "simulation_self_only"

    # --- 4.2. Тестовые действия не будят реальных людей ----------------------
    async with sim_flow.session_factory() as db:
        admin_notifications = int(
            await db.scalar(
                select(func.count())
                .select_from(AppNotification)
                .where(AppNotification.user_id == sim_flow.admin_user.id)
            )
            or 0
        )
    assert admin_notifications == 0

    # --- 5. Реальный админ не видит ни теневого профиля, ни его активности ---
    r = await client.get("/api/me/employee")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == ids.admin_employee_id

    r = await client.get("/api/admin/employees")
    assert r.status_code == 200, r.text
    assert shadow_id not in {row["id"] for row in r.json()}

    r = await client.get("/api/issues")
    assert r.status_code == 200, r.text
    assert issue_id not in {row["id"] for row in r.json()["items"]}

    r = await client.get("/api/tasks")
    assert r.status_code == 200, r.text
    assert test_task_id not in {t["id"] for t in r.json()}

    async with sim_flow.session_factory() as db:
        assert (
            await db.scalar(
                select(func.count()).select_from(Task).where(Task.id == ids.real_task_id)
            )
            == 1
        )

    # --- 6. Выход: чистка, аудит остаётся, реальные данные целы --------------
    r = await client.post(f"/api/admin/simulation/{session_id}/exit")
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["tasks"] == 1 and result["issues"] == 1
    assert result["already_ended"] is False

    async with sim_flow.session_factory() as db:
        assert await db.get(Employee, shadow_id) is None
        assert await db.get(Task, test_task_id) is None
        # Реальная задача и профиль сотрудника на месте.
        assert await db.get(Task, ids.real_task_id) is not None
        assert await db.get(Employee, ids.subject_employee_id) is not None
        audit = await db.get(SimulationSession, session_id)
        assert audit is not None and audit.status == "ended"
        assert audit.ended_at is not None and audit.tasks_cleaned == 1
        # Теневой пользователь тоже удалён.
        assert (
            await db.scalar(
                select(func.count()).select_from(User).where(User.telegram_id < 0)
            )
            == 0
        )

    # --- 7. Повторный выход идемпотентен -------------------------------------
    r = await client.post(f"/api/admin/simulation/{session_id}/exit")
    assert r.status_code == 200, r.text
    assert r.json()["already_ended"] is True

    # --- 8. В базе не осталось ни одного теневого профиля --------------------
    async with sim_flow.session_factory() as db:
        assert (
            await db.scalar(
                select(func.count()).select_from(Employee).where(Employee.is_simulation)
            )
            == 0
        )
