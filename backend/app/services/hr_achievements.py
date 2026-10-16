"""Скрытые ачивки сотрудника — личный прогресс, а не витрина.

Решение владельца (2026-10-16): «ачивки остаются как скрытая система, спрятанная
внутри личного профиля… связаны они будут с выполнением задач или приколов типа
ваш 100-й или 1000-й рабочий день, ваша 1000-я выполненная задача… пока только
управленцам и разрабам».

Отсюда три правила, которые и закодированы ниже.

1. **Только работа.** Каталог строится на реальных следах смены: закрытые
   поручения (`task_events.to_status='done'`), отработанные смены (уникальные
   `checklist_runs.shift_date`), закрытые пункты чек-листов. Шуточный контур
   (чухан/лох/червь/ачивки GHG10) целиком уехал в `app/_legacy` — здесь его нет.
2. **Скрыто.** Блок виден только руководителю (`aup`) и администратору
   (`admin`); обычному сотруднику ручка отвечает `visible=false` и ничего не
   отдаёт. Видимость считает СЕРВЕР (`view`), а не кнопка в мини-аппе.
3. **Один раз.** Ачивка пишется строкой `employee_achievements` с
   `unique(employee_id, code)`: повторный пересчёт её не дублирует, поэтому
   профиль можно пересчитывать на каждое чтение — без джоб и без миграций.

Пересчёт идёт НА ЧТЕНИЕ, а не по событию: поручение закрывается из нескольких
мест (API, бот, планировщик), и вешать выдачу ачивок в каждую точку — верный
способ однажды её потерять. Три `COUNT`-запроса на профиль дешевы, а выдача
идемпотентна: правило «порог взят → строка есть» восстанавливает прогресс по
исходным данным в любой момент.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    TASK_DONE,
    ChecklistCompletion,
    ChecklistRun,
    Employee,
    EmployeeAchievement,
    TaskEvent,
)
from app.services import hr_access

# Метрики: по одной на каждый «след работы», который умеем считать точно.
METRIC_TASKS = "tasks_done"
METRIC_SHIFTS = "shift_days"
METRIC_CHECKLIST = "checklist_items"

METRICS: tuple[str, ...] = (METRIC_TASKS, METRIC_SHIFTS, METRIC_CHECKLIST)

METRIC_TITLES: dict[str, str] = {
    METRIC_TASKS: "закрытых поручений",
    METRIC_SHIFTS: "рабочих дней",
    METRIC_CHECKLIST: "пунктов чек-листа",
}


@dataclass(frozen=True)
class Milestone:
    """Порог метрики, за который выдаётся ачивка."""

    code: str
    metric: str
    threshold: int
    title: str
    emoji: str


# Порядок = порядок выдачи в профиле. Пороги округлены «по-человечески»:
# первый шаг, юбилейные десятки, сотни и «тысяча» — как просил владелец.
MILESTONES: tuple[Milestone, ...] = (
    Milestone("first_task", METRIC_TASKS, 1, "Первое закрытое поручение", "🎯"),
    Milestone("tasks_10", METRIC_TASKS, 10, "10 закрытых поручений", "🔟"),
    Milestone("tasks_50", METRIC_TASKS, 50, "50 закрытых поручений", "🏅"),
    Milestone("tasks_100", METRIC_TASKS, 100, "100 закрытых поручений", "💯"),
    Milestone("tasks_500", METRIC_TASKS, 500, "500 закрытых поручений", "🚀"),
    Milestone("tasks_1000", METRIC_TASKS, 1000, "1000 поручений: легенда смены", "👑"),
    Milestone("first_shift", METRIC_SHIFTS, 1, "Первая смена в системе", "🌱"),
    Milestone("shifts_10", METRIC_SHIFTS, 10, "10 рабочих дней", "🗓"),
    Milestone("shifts_100", METRIC_SHIFTS, 100, "100 рабочих дней", "🧭"),
    Milestone("shifts_300", METRIC_SHIFTS, 300, "300 рабочих дней", "🏔"),
    Milestone("shifts_1000", METRIC_SHIFTS, 1000, "1000-й рабочий день", "🏆"),
    Milestone("checklist_10", METRIC_CHECKLIST, 10, "10 пунктов чек-листа", "🧾"),
    Milestone("checklist_100", METRIC_CHECKLIST, 100, "100 пунктов чек-листа", "📋"),
    Milestone("checklist_1000", METRIC_CHECKLIST, 1000, "1000 пунктов чек-листа", "🗂"),
)

_BY_CODE: dict[str, Milestone] = {m.code: m for m in MILESTONES}


def by_code(code: str) -> Milestone | None:
    return _BY_CODE.get(code)


def milestones_for(metric: str) -> tuple[Milestone, ...]:
    return tuple(m for m in MILESTONES if m.metric == metric)


@dataclass(frozen=True)
class Stats:
    """Счётчики сотрудника по метрикам (нули, если следов ещё нет)."""

    tasks_done: int = 0
    shift_days: int = 0
    checklist_items: int = 0

    def count(self, metric: str) -> int:
        return int(getattr(self, metric, 0) or 0)

    def as_dict(self) -> dict[str, int]:
        return {metric: self.count(metric) for metric in METRICS}


@dataclass(frozen=True)
class Awarded:
    """Выданная ачивка (код + когда)."""

    code: str
    title: str
    emoji: str
    awarded_at: datetime


@dataclass(frozen=True)
class NextGoal:
    """Ближайший невзятый порог по метрике — «сколько осталось»."""

    code: str
    title: str
    emoji: str
    metric: str
    threshold: int
    done: int

    @property
    def left(self) -> int:
        return max(0, self.threshold - self.done)

    def text(self) -> str:
        return f"{self.title}: {self.done}/{self.threshold} (осталось {self.left})"


@dataclass
class AchievementView:
    """Ответ ручки: видно ли вообще и что показать."""

    visible: bool
    awarded: list[Awarded] = field(default_factory=list)
    stats: Stats = field(default_factory=Stats)
    next_goals: list[NextGoal] = field(default_factory=list)
    note: str = ""

    @property
    def new_codes(self) -> list[str]:
        return [a.code for a in self.awarded]


# --------------------------------------------------------------------------
# Чистые правила (тестируются без БД)
# --------------------------------------------------------------------------


def visible_for(employee: Employee | None) -> bool:
    """Показывать ли ачивки этому сотруднику: руководители и админы бота."""
    return hr_access.is_aup(employee)


def reached(stats: Stats, already: Collection[str]) -> list[Milestone]:
    """Пороги, которые уже взяты, но строки выдачи по ним ещё нет.

    Идемпотентность — здесь: повторный вызов вернёт пустой список.
    """
    out: list[Milestone] = []
    for m in MILESTONES:
        if m.code in already:
            continue
        if stats.count(m.metric) >= m.threshold:
            out.append(m)
    return out


def next_goals(stats: Stats, *, per_metric: int = 1) -> list[NextGoal]:
    """Ближайшие невзятые пороги — по одному на метрику (по умолчанию).

    Метрика без единого взятого порога показывает первый шаг каталога: «1» для
    первой задачи и смены — это и есть ближайшая цель, а не «10».
    """
    take = max(1, per_metric)
    out: list[NextGoal] = []
    for metric in METRICS:
        current = stats.count(metric)
        unmet = [m for m in milestones_for(metric) if m.threshold > current]
        for milestone in unmet[:take]:
            out.append(
                NextGoal(
                    code=milestone.code,
                    title=milestone.title,
                    emoji=milestone.emoji,
                    metric=metric,
                    threshold=milestone.threshold,
                    done=current,
                )
            )
    return out


def awarded_from_rows(rows: Iterable[EmployeeAchievement]) -> list[Awarded]:
    """Строки БД → выданные ачивки. Коды без каталога (старый каталог) не теряем."""
    out: list[Awarded] = []
    for row in rows:
        milestone = by_code(row.code)
        out.append(
            Awarded(
                code=row.code,
                title=milestone.title if milestone else row.code,
                emoji=milestone.emoji if milestone else "✨",
                awarded_at=row.awarded_at,
            )
        )
    return out


# --------------------------------------------------------------------------
# Запросы и пересчёт
# --------------------------------------------------------------------------


async def _count_scalar(session: AsyncSession, stmt: object) -> int:
    value = await session.scalar(stmt)  # type: ignore[arg-type]
    return int(value or 0)


async def stats_for(session: AsyncSession, employee_id: int) -> Stats:
    """Три независимых `COUNT` — по одному на метрику."""
    done_tasks = select(func.count()).select_from(TaskEvent).where(
        TaskEvent.by_employee_id == employee_id,
        TaskEvent.to_status == TASK_DONE,
    )
    shifts = select(func.count(func.distinct(ChecklistRun.shift_date))).where(
        ChecklistRun.employee_id == employee_id
    )
    items = (
        select(func.count())
        .select_from(ChecklistCompletion)
        .join(ChecklistRun, ChecklistRun.id == ChecklistCompletion.run_id)
        .where(ChecklistRun.employee_id == employee_id)
    )
    return Stats(
        tasks_done=await _count_scalar(session, done_tasks),
        shift_days=await _count_scalar(session, shifts),
        checklist_items=await _count_scalar(session, items),
    )


async def awarded_rows(
    session: AsyncSession, employee_id: int
) -> Sequence[EmployeeAchievement]:
    result = await session.scalars(
        select(EmployeeAchievement)
        .where(EmployeeAchievement.employee_id == employee_id)
        .order_by(EmployeeAchievement.awarded_at, EmployeeAchievement.id)
    )
    return list(result)


async def sync(session: AsyncSession, employee_id: int) -> list[Milestone]:
    """Выдать всё, что уже заслужено. Возвращает ТОЛЬКО новые ачивки."""
    stats = await stats_for(session, employee_id)
    rows = await awarded_rows(session, employee_id)
    already = {row.code for row in rows}
    fresh = reached(stats, already)
    for milestone in fresh:
        session.add(
            EmployeeAchievement(employee_id=employee_id, code=milestone.code)
        )
    if fresh:
        await session.flush()
    return fresh


HIDDEN_NOTE = (
    "Личный прогресс. Показывается руководителю и администратору — решение "
    "о видимости для остальных ещё не принято."
)


async def _build(session: AsyncSession, employee_id: int) -> AchievementView:
    """Пересчёт (идемпотентный) + счётчики + ближайшие цели."""
    await sync(session, employee_id)
    stats = await stats_for(session, employee_id)
    rows = await awarded_rows(session, employee_id)
    return AchievementView(
        visible=True,
        awarded=awarded_from_rows(rows),
        stats=stats,
        next_goals=next_goals(stats),
    )


async def view(session: AsyncSession, employee: Employee | None) -> AchievementView:
    """Блок в ЛИЧНОМ профиле сотрудника.

    Обычному сотруднику БД не трогаем вовсе: блок скрыт, значит и считать нечего
    (заодно ручка не тратит запросы Neon на каждый заход в профиль).
    """
    if not visible_for(employee):
        return AchievementView(visible=False, note=HIDDEN_NOTE)
    assert employee is not None  # visible_for(None) — False
    return await _build(session, employee.id)


async def view_for_manager(
    session: AsyncSession, employee_id: int
) -> AchievementView:
    """Ачивки конкретного сотрудника глазами руководителя — всегда видимы.

    Отдельная точка входа, потому что правило видимости тут про СМОТРЯЩЕГО, а не
    про владельца ачивок: управляющему прогресс подчинённого открыт, самому
    подчинённому — пока нет.
    """
    return await _build(session, employee_id)
