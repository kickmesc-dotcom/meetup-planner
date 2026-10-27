"""SemiTaskBot: скрытые ачивки сотрудника.

Живого Postgres нет (см. `tests/test_hr_core.py`), поэтому проверяем то, что
определяет поведение: каталог порогов, чистые правила выдачи (`reached`),
«ближайшие цели», правило видимости (руководитель/админ против обычного
сотрудника), идемпотентность выдачи и подключение обеих ручек.

Ключевые требования владельца (2026-10-16), которые тут и зафиксированы:
1. ачивки — про РАБОТУ (задачи, рабочие дни, пункты чек-листа), а не про шутки;
2. блок скрыт в личном профиле: пока его видят только руководитель и админ;
3. выдать ачивку дважды нельзя, а пересчёт не должен её терять.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from datetime import UTC, datetime  # noqa: E402

import pytest  # noqa: E402

from app.db.hr_models import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_AUP,
    ROLE_EMPLOYEE,
    Employee,
    EmployeeAchievement,
)
from app.schemas.hr_achievements import to_out  # noqa: E402
from app.services import hr_achievements as ach  # noqa: E402

# --------------------------------------------------------------------------
# Каталог
# --------------------------------------------------------------------------


def test_milestone_codes_are_unique():
    codes = [m.code for m in ach.MILESTONES]
    assert len(codes) == len(set(codes)), "код ачивки — ключ выдачи, дубли запрещены"


def test_thresholds_grow_inside_each_metric():
    for metric in ach.METRICS:
        thresholds = [m.threshold for m in ach.milestones_for(metric)]
        assert thresholds == sorted(thresholds), f"{metric}: пороги должны расти"
        assert thresholds[0] >= 1, "нулевой порог выдавал бы ачивку всем сразу"


def test_catalog_covers_owners_examples():
    """100-й/1000-й рабочий день и 1000-я задача — из запроса владельца."""
    codes = {m.code for m in ach.MILESTONES}
    assert {"shifts_100", "shifts_1000", "tasks_1000"} <= codes


def test_every_metric_has_milestones():
    for metric in ach.METRICS:
        assert ach.milestones_for(metric), f"{metric}: без порогов метрика мертва"
        assert metric in ach.METRIC_TITLES


# --------------------------------------------------------------------------
# Чистые правила выдачи
# --------------------------------------------------------------------------


def test_reached_awards_only_new_thresholds():
    stats = ach.Stats(tasks_done=10, shift_days=1, checklist_items=0)
    fresh = [m.code for m in ach.reached(stats, already={"first_task"})]
    assert fresh == ["tasks_10", "first_shift"]


def test_reached_is_idempotent():
    stats = ach.Stats(tasks_done=1000, shift_days=1000, checklist_items=1000)
    all_codes = {m.code for m in ach.MILESTONES}
    assert ach.reached(stats, already=all_codes) == []


def test_reached_is_empty_for_zero_activity():
    assert ach.reached(ach.Stats(), already=set()) == []


def test_next_goals_show_remaining_steps():
    stats = ach.Stats(tasks_done=12, shift_days=0, checklist_items=0)
    goals = {g.metric: g for g in ach.next_goals(stats)}
    assert goals[ach.METRIC_TASKS].code == "tasks_50"
    assert goals[ach.METRIC_TASKS].left == 38
    assert "осталось 38" in goals[ach.METRIC_TASKS].text()
    # Метрика без единого шага показывает самый первый порог, а не десятый.
    assert goals[ach.METRIC_SHIFTS].code == "first_shift"
    assert goals[ach.METRIC_SHIFTS].left == 1


def test_next_goals_skip_fully_earned_metric():
    stats = ach.Stats(tasks_done=1000)
    goals = {g.metric for g in ach.next_goals(stats)}
    assert ach.METRIC_TASKS not in goals
    assert ach.METRIC_SHIFTS in goals


# --------------------------------------------------------------------------
# Видимость
# --------------------------------------------------------------------------


def _employee(role: str) -> Employee:
    return Employee(id=1, user_id=1, role=role)


def test_visible_only_for_aup_and_admin():
    assert not ach.visible_for(_employee(ROLE_EMPLOYEE))
    assert ach.visible_for(_employee(ROLE_AUP))
    assert ach.visible_for(_employee(ROLE_ADMIN))
    assert not ach.visible_for(None)


@pytest.mark.asyncio
async def test_view_hidden_for_employee_does_not_touch_db():
    """Скрытый блок не должен стоить запросов в Neon."""

    class _ExplodingSession:
        async def scalar(self, _stmt):  # noqa: ANN001, ANN202
            raise AssertionError("скрытый блок не должен ходить в базу")

        async def scalars(self, _stmt):  # noqa: ANN001, ANN202
            raise AssertionError("скрытый блок не должен ходить в базу")

    view = await ach.view(_ExplodingSession(), _employee(ROLE_EMPLOYEE))
    assert view.visible is False
    assert view.awarded == []
    assert view.stats.as_dict() == {m: 0 for m in ach.METRICS}
    assert view.note


# --------------------------------------------------------------------------
# Запросы и выдача (лёгкие фейки вместо Postgres)
# --------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def __iter__(self):  # noqa: ANN204
        return iter(self._rows)

    def all(self) -> list[object]:
        return list(self._rows)


class _FakeSession:
    """Асинхронная замена сессии: очередь `scalar()` + строки выдачи в `scalars()`.

    Порядок счётчиков — как в `stats_for`: задачи, смены, пункты чек-листа.
    """

    def __init__(self, counts: list[int], rows: list[object] | None = None) -> None:
        self._counts = list(counts)
        self._rows = list(rows or [])
        self.added: list[EmployeeAchievement] = []
        self.flushes = 0

    async def scalar(self, _stmt):  # noqa: ANN001, ANN202
        return self._counts.pop(0) if self._counts else 0

    async def scalars(self, _stmt):  # noqa: ANN001, ANN202
        return _FakeResult(self._rows)

    def add(self, obj: EmployeeAchievement) -> None:
        # Пишем и в «таблицу», как настоящая БД: второй `awarded_rows` в
        # `_build` должен увидеть только что выданную ачивку.
        self.added.append(obj)
        self._rows.append(obj)

    async def flush(self) -> None:
        self.flushes += 1


@pytest.mark.asyncio
async def test_sync_awards_reached_and_skips_existing():
    existing = EmployeeAchievement(
        id=1, employee_id=7, code="first_task", awarded_at=datetime.now(UTC)
    )
    session = _FakeSession(counts=[10, 1, 0], rows=[existing])
    fresh = [m.code for m in await ach.sync(session, 7)]  # type: ignore[arg-type]
    assert fresh == ["tasks_10", "first_shift"]
    assert [row.code for row in session.added] == fresh
    assert session.flushes == 1


@pytest.mark.asyncio
async def test_sync_writes_nothing_when_everything_awarded():
    rows = [
        EmployeeAchievement(
            id=i, employee_id=7, code=code, awarded_at=datetime.now(UTC)
        )
        for i, code in enumerate(("first_task", "tasks_10", "first_shift"), start=1)
    ]
    session = _FakeSession(counts=[10, 1, 0], rows=rows)
    assert await ach.sync(session, 7) == []  # type: ignore[arg-type]
    assert session.added == []
    assert session.flushes == 0, "нечего писать — не должно быть и flush"


@pytest.mark.asyncio
async def test_view_for_manager_shows_progress_of_subordinate():
    # sync: 3 счётчика + выдача; затем счётчики и выдача для самого вью.
    session = _FakeSession(counts=[1, 0, 0, 1, 0, 0])
    view = await ach.view_for_manager(session, 7)  # type: ignore[arg-type]
    assert view.visible is True
    assert view.stats.tasks_done == 1
    assert [a.code for a in view.awarded] == ["first_task"]
    assert {g.code for g in view.next_goals} >= {"tasks_10", "first_shift"}


def test_awarded_from_rows_keeps_unknown_codes():
    """Старый код каталога не должен превращаться в пустую строку в профиле."""
    rows = [
        EmployeeAchievement(
            id=1, employee_id=7, code="ghg10_legacy", awarded_at=datetime.now(UTC)
        )
    ]
    awarded = ach.awarded_from_rows(rows)
    assert awarded[0].code == "ghg10_legacy"
    assert awarded[0].title == "ghg10_legacy"
    assert awarded[0].emoji


# --------------------------------------------------------------------------
# Схема ответа и подключение ручек
# --------------------------------------------------------------------------


def test_schema_hides_payload_when_invisible():
    out = to_out(ach.AchievementView(visible=False, note="скрыто"))
    assert out.visible is False
    assert out.awarded == []
    assert out.stats == {}
    assert out.next_goals == []
    assert out.note == "скрыто"


def test_schema_exposes_awards_and_goals():
    view = ach.AchievementView(
        visible=True,
        awarded=[
            ach.Awarded(
                code="first_task",
                title="Первое закрытое поручение",
                emoji="🎯",
                awarded_at=datetime.now(UTC),
            )
        ],
        stats=ach.Stats(tasks_done=1),
        next_goals=ach.next_goals(ach.Stats(tasks_done=1)),
    )
    out = to_out(view)
    assert out.visible is True
    assert out.awarded[0].code == "first_task"
    assert out.stats[ach.METRIC_TASKS] == 1
    assert all(goal.text for goal in out.next_goals)


def test_achievement_routes_are_registered():
    from app.main import create_app

    app = create_app()
    # Пути берём из `_iter_routes`: в Starlette 1.x `app.routes` больше не
    # разворачивается в плоский список, и прямой обход молча дал бы пустое
    # множество (аудит 26.10.2026, S-18).
    from app.api.routes_meta import _iter_routes

    paths = set(_iter_routes(app))
    expected = {
        ("GET", "/api/me/achievements"),
        ("GET", "/api/admin/employees/{employee_id}/achievements"),
    }
    missing = expected - paths
    assert not missing, f"не подключены ручки: {sorted(missing)}"
