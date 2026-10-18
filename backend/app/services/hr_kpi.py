"""KPI-геймификация смены вместо GHG10: опыт за работу, а не за приколы.

Прежний шуточный контур (чухан/лох/червь/дуэли) уехал в `app/_legacy`: он
награждал за случайность и обиду, а не за смену. Здесь наоборот — единственный
источник опыта это реальные следы работы, которые уже пишет HR-ядро:

* закрытый пункт чек-листа — небольшой шаг опыта;
* полностью закрытая смена — заметный шаг (смена отработана, а не «отмечена»);
* закрытое поручение — основной вес;
* поручение, закрытое в срок, — надбавка (дисциплина важнее объёма).

Правила живут в `admin_config` (та же таблица, что у напоминаний и эскалации):
админ меняет веса из мини-аппа без передеплоя, а `snapshot()` отдаёт их на
фронт. Званий ровно столько, сколько помещается на карточку, и все они
нейтральные («Новичок», «Опора смены», …) — это подпись прогресса для
сотрудника ресторана, а не ярлык «кто тут лох».

«Сотрудник недели» — не случайный ролл: это лучший по опыту за текущую
календарную неделю (пн–вс, часовой пояс ресторана), при равенстве опыта выше
тот, у кого больше закрытых поручений, затем — кто раньше в списке. Номинация
считается НА ЧТЕНИЕ из тех же событий: отдельной таблицы нет, значит нечего
рассинхронизировать и не нужна миграция.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    RUN_DONE,
    TASK_DONE,
    ChecklistCompletion,
    ChecklistRun,
    Department,
    Employee,
    Task,
    TaskEvent,
)
from app.db.models import AdminConfig, User

# --------------------------------------------------------------------------
# Правила (веса)
# --------------------------------------------------------------------------

KEY_XP_CHECKLIST_ITEM = "hr.kpi.xp_checklist_item"
KEY_XP_SHIFT_DONE = "hr.kpi.xp_shift_done"
KEY_XP_TASK = "hr.kpi.xp_task"
KEY_XP_ON_TIME = "hr.kpi.xp_on_time"
KEY_MIN_XP_FOR_WINNER = "hr.kpi.min_xp_winner"

# Веса подобраны так, чтобы одна нормальная смена (10–12 пунктов + закрытая
# смена + 1–2 поручения) давала ~60–80 XP: первый «взрослый» ранг берётся за
# две-три смены, а не за месяц.
DEFAULT_XP_CHECKLIST_ITEM = 2
DEFAULT_XP_SHIFT_DONE = 10
DEFAULT_XP_TASK = 15
DEFAULT_XP_ON_TIME = 5
DEFAULT_MIN_XP_FOR_WINNER = 20

MAX_XP_WEIGHT = 100
MAX_MIN_XP = 1000


@dataclass(frozen=True)
class Rules:
    """Веса опыта. Неизменяемы: их подменяют целиком, а не правят поля."""

    xp_checklist_item: int = DEFAULT_XP_CHECKLIST_ITEM
    xp_shift_done: int = DEFAULT_XP_SHIFT_DONE
    xp_task: int = DEFAULT_XP_TASK
    xp_on_time: int = DEFAULT_XP_ON_TIME
    min_xp_winner: int = DEFAULT_MIN_XP_FOR_WINNER

    def as_dict(self) -> dict[str, int]:
        return {
            "xp_checklist_item": self.xp_checklist_item,
            "xp_shift_done": self.xp_shift_done,
            "xp_task": self.xp_task,
            "xp_on_time": self.xp_on_time,
            "min_xp_winner": self.min_xp_winner,
        }


DEFAULT_RULES = Rules()


def clamp_weight(value: int) -> int:
    """Вес одного события: 0 — «не начислять», 100 — уже много."""
    return max(0, min(MAX_XP_WEIGHT, int(value)))


def clamp_min_xp(value: int) -> int:
    return max(0, min(MAX_MIN_XP, int(value)))


# --------------------------------------------------------------------------
# Звания: пороги опыта, а не место в рейтинге
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Rank:
    code: str
    title: str
    emoji: str
    threshold: int


RANKS: tuple[Rank, ...] = (
    Rank("trainee", "Стажёр", "🌱", 0),
    Rank("shift", "В смене", "🧭", 100),
    Rank("steady", "Ровный ход", "⚙️", 300),
    Rank("anchor", "Опора смены", "🧱", 800),
    Rank("mentor", "Наставник", "🤝", 1600),
    Rank("master", "Мастер смены", "🏅", 3000),
)

# --------------------------------------------------------------------------
# Счётчики и опыт
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Counts:
    """Следы работы за окно (неделя или всё время)."""

    checklist_items: int = 0
    shifts_done: int = 0
    tasks_done: int = 0
    tasks_on_time: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "checklist_items": self.checklist_items,
            "shifts_done": self.shifts_done,
            "tasks_done": self.tasks_done,
            "tasks_on_time": self.tasks_on_time,
        }


def xp_for(counts: Counts, rules: Rules = DEFAULT_RULES) -> int:
    """Опыт по правилам. Чистая функция — её и проверяют тесты."""
    return (
        counts.checklist_items * rules.xp_checklist_item
        + counts.shifts_done * rules.xp_shift_done
        + counts.tasks_done * rules.xp_task
        + counts.tasks_on_time * rules.xp_on_time
    )


def rank_for(xp: int) -> Rank:
    current = RANKS[0]
    for rank in RANKS:
        if xp >= rank.threshold:
            current = rank
        else:
            break
    return current


def next_rank_for(xp: int) -> Rank | None:
    for rank in RANKS:
        if rank.threshold > xp:
            return rank
    return None


@dataclass(frozen=True)
class Progress:
    """Опыт + звание + сколько до следующего."""

    xp: int
    rank: Rank
    next_rank: Rank | None
    left: int
    percent: int

    def as_dict(self) -> dict[str, object]:
        return {
            "xp": self.xp,
            "rank": self.rank.code,
            "rank_title": self.rank.title,
            "rank_emoji": self.rank.emoji,
            "next_rank_title": self.next_rank.title if self.next_rank else None,
            "next_rank_xp": self.next_rank.threshold if self.next_rank else None,
            "left": self.left,
            "percent": self.percent,
        }


def progress_for(xp: int) -> Progress:
    rank = rank_for(xp)
    nxt = next_rank_for(xp)
    if nxt is None:
        return Progress(xp=xp, rank=rank, next_rank=None, left=0, percent=100)
    span = nxt.threshold - rank.threshold
    done = xp - rank.threshold
    percent = 0 if span <= 0 else max(0, min(100, round(done * 100 / span)))
    return Progress(
        xp=xp, rank=rank, next_rank=nxt, left=max(0, nxt.threshold - xp), percent=percent
    )


# --------------------------------------------------------------------------
# Неделя и «сотрудник недели»
# --------------------------------------------------------------------------


def week_bounds(day: date) -> tuple[date, date]:
    """Пн–вс недели, в которую попадает день (границы включительно)."""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


@dataclass(frozen=True)
class Candidate:
    """Строка недельного рейтинга."""

    employee_id: int
    display_name: str
    department: str | None
    counts: Counts
    xp: int
    is_demo: bool = False


@dataclass
class Winner:
    employee_id: int
    display_name: str
    department: str | None
    xp: int
    tasks_done: int

    def as_dict(self) -> dict[str, object]:
        return {
            "employee_id": self.employee_id,
            "display_name": self.display_name,
            "department": self.department,
            "xp": self.xp,
            "tasks_done": self.tasks_done,
        }


def pick_winner(candidates: Iterable[Candidate], rules: Rules = DEFAULT_RULES) -> Winner | None:
    """Лучший за неделю среди тех, кто набрал минимум опыта.

    Тестовый пул (`is_demo`) в номинацию не попадает: «сотрудник недели» —
    звание для живых людей, симуляторы не должны его забирать.
    """
    pool = [
        c for c in candidates if not c.is_demo and c.xp >= rules.min_xp_winner
    ]
    if not pool:
        return None
    best = max(pool, key=lambda c: (c.xp, c.counts.tasks_done, -c.employee_id))
    return Winner(
        employee_id=best.employee_id,
        display_name=best.display_name,
        department=best.department,
        xp=best.xp,
        tasks_done=best.counts.tasks_done,
    )


# --------------------------------------------------------------------------
# Хранилище правил (admin_config)
# --------------------------------------------------------------------------


async def _get_int(session: AsyncSession, key: str, default: int) -> int:
    value = await session.scalar(select(AdminConfig.value).where(AdminConfig.key == key))
    if value is None:
        return default
    try:
        return int(str(value))
    except ValueError:
        return default


async def get_rules(session: AsyncSession) -> Rules:
    return Rules(
        xp_checklist_item=clamp_weight(
            await _get_int(session, KEY_XP_CHECKLIST_ITEM, DEFAULT_XP_CHECKLIST_ITEM)
        ),
        xp_shift_done=clamp_weight(
            await _get_int(session, KEY_XP_SHIFT_DONE, DEFAULT_XP_SHIFT_DONE)
        ),
        xp_task=clamp_weight(await _get_int(session, KEY_XP_TASK, DEFAULT_XP_TASK)),
        xp_on_time=clamp_weight(await _get_int(session, KEY_XP_ON_TIME, DEFAULT_XP_ON_TIME)),
        min_xp_winner=clamp_min_xp(
            await _get_int(session, KEY_MIN_XP_FOR_WINNER, DEFAULT_MIN_XP_FOR_WINNER)
        ),
    )


async def _set(session: AsyncSession, key: str, value: int) -> None:
    row = await session.get(AdminConfig, key)
    if row is None:
        session.add(AdminConfig(key=key, value=str(value)))
    else:
        row.value = str(value)


async def update_rules(
    session: AsyncSession,
    *,
    xp_checklist_item: int | None = None,
    xp_shift_done: int | None = None,
    xp_task: int | None = None,
    xp_on_time: int | None = None,
    min_xp_winner: int | None = None,
) -> Rules:
    """Частичная правка весов. Значения зажимаются в сервисе, а не в схеме."""
    if xp_checklist_item is not None:
        await _set(session, KEY_XP_CHECKLIST_ITEM, clamp_weight(xp_checklist_item))
    if xp_shift_done is not None:
        await _set(session, KEY_XP_SHIFT_DONE, clamp_weight(xp_shift_done))
    if xp_task is not None:
        await _set(session, KEY_XP_TASK, clamp_weight(xp_task))
    if xp_on_time is not None:
        await _set(session, KEY_XP_ON_TIME, clamp_weight(xp_on_time))
    if min_xp_winner is not None:
        await _set(session, KEY_MIN_XP_FOR_WINNER, clamp_min_xp(min_xp_winner))
    await session.commit()
    return await get_rules(session)


# --------------------------------------------------------------------------
# Запросы
# --------------------------------------------------------------------------


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min)


def _day_end(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time.min)


async def _count(session: AsyncSession, stmt: Select[Any]) -> int:
    return int(await session.scalar(stmt) or 0)


def _window(
    stmt: Select[Any], column: Any, since: date | None, until: date | None
) -> Select[Any]:
    """Окно дат включительно: `since 00:00 <= t < (until+1) 00:00`."""
    if since is not None:
        stmt = stmt.where(column >= _day_start(since))
    if until is not None:
        stmt = stmt.where(column < _day_end(until))
    return stmt


def _base_statements(employee_id: int | None) -> dict[str, Select[Any]]:
    """Четыре независимых `COUNT` — по одному на метрику.

    Разделяем их намеренно: каждая метрика живёт в своей таблице, и склейка в
    один запрос через `UNION` тут дороже читаемости, а не быстрее — индексы под
    каждый след уже есть.
    """
    items = (
        select(func.count())
        .select_from(ChecklistCompletion)
        .join(ChecklistRun, ChecklistRun.id == ChecklistCompletion.run_id)
    )
    shifts = select(func.count()).select_from(ChecklistRun).where(
        ChecklistRun.status == RUN_DONE
    )
    tasks = select(func.count()).select_from(TaskEvent).where(
        TaskEvent.to_status == TASK_DONE
    )
    on_time = (
        select(func.count())
        .select_from(TaskEvent)
        .join(Task, Task.id == TaskEvent.task_id)
        .where(
            TaskEvent.to_status == TASK_DONE,
            Task.due_at.is_not(None),
            Task.done_at.is_not(None),
            Task.done_at <= Task.due_at,
        )
    )
    if employee_id is not None:
        items = items.where(ChecklistRun.employee_id == employee_id)
        shifts = shifts.where(ChecklistRun.employee_id == employee_id)
        tasks = tasks.where(TaskEvent.by_employee_id == employee_id)
        on_time = on_time.where(TaskEvent.by_employee_id == employee_id)
    return {"items": items, "shifts": shifts, "tasks": tasks, "on_time": on_time}


async def counts_for(
    session: AsyncSession,
    employee_id: int,
    *,
    since: date | None = None,
    until: date | None = None,
) -> Counts:
    """Следы работы одного сотрудника (опционально — за окно дат)."""
    stmts = _base_statements(employee_id)
    return Counts(
        checklist_items=await _count(
            session, _window(stmts["items"], ChecklistCompletion.done_at, since, until)
        ),
        shifts_done=await _count(
            session, _window(stmts["shifts"], ChecklistRun.completed_at, since, until)
        ),
        tasks_done=await _count(
            session, _window(stmts["tasks"], TaskEvent.at, since, until)
        ),
        tasks_on_time=await _count(
            session, _window(stmts["on_time"], TaskEvent.at, since, until)
        ),
    )


async def _grouped(
    session: AsyncSession,
    stmt: Select[Any],
    column: Any,
    since: date | None,
    until: date | None,
) -> dict[int, int]:
    """`employee_id -> count` за окно — по одной строке на человека."""
    rows = await session.execute(_window(stmt, column, since, until))
    return {int(emp_id): int(cnt) for emp_id, cnt in rows.all()}


async def board(
    session: AsyncSession,
    day: date,
    rules: Rules | None = None,
) -> list[Candidate]:
    """Рейтинг за неделю `day`: опыт каждого живого сотрудника + счётчики.

    Считается четырьмя групповыми запросами (а не N запросами по людям):
    состав смены — это десятки человек, и такой запрос дешевле держать одним
    обращением к Neon.
    """
    active_rules = rules or await get_rules(session)
    monday, sunday = week_bounds(day)

    people = (
        select(Employee.id, Employee.is_demo, Department.name, User.display_name)
        .join(User, User.id == Employee.user_id)
        .outerjoin(Department, Department.id == Employee.department_id)
        .where(
            Employee.is_active.is_(True),
            Employee.is_simulation.is_(False),
        )
    )
    rows = (await session.execute(people)).all()
    if not rows:
        return []

    items = await _grouped(
        session,
        select(ChecklistRun.employee_id, func.count())
        .select_from(ChecklistCompletion)
        .join(ChecklistRun, ChecklistRun.id == ChecklistCompletion.run_id)
        .group_by(ChecklistRun.employee_id),
        ChecklistCompletion.done_at,
        monday,
        sunday,
    )
    shifts = await _grouped(
        session,
        select(ChecklistRun.employee_id, func.count())
        .select_from(ChecklistRun)
        .where(ChecklistRun.status == RUN_DONE)
        .group_by(ChecklistRun.employee_id),
        ChecklistRun.completed_at,
        monday,
        sunday,
    )
    tasks = await _grouped(
        session,
        select(TaskEvent.by_employee_id, func.count())
        .select_from(TaskEvent)
        .where(TaskEvent.to_status == TASK_DONE)
        .group_by(TaskEvent.by_employee_id),
        TaskEvent.at,
        monday,
        sunday,
    )
    on_time = await _grouped(
        session,
        select(TaskEvent.by_employee_id, func.count())
        .select_from(TaskEvent)
        .join(Task, Task.id == TaskEvent.task_id)
        .where(
            TaskEvent.to_status == TASK_DONE,
            Task.due_at.is_not(None),
            Task.done_at.is_not(None),
            Task.done_at <= Task.due_at,
        )
        .group_by(TaskEvent.by_employee_id),
        TaskEvent.at,
        monday,
        sunday,
    )

    out: list[Candidate] = []
    for emp_id, is_demo, dept_name, display_name in rows:
        counts = Counts(
            checklist_items=items.get(int(emp_id), 0),
            shifts_done=shifts.get(int(emp_id), 0),
            tasks_done=tasks.get(int(emp_id), 0),
            tasks_on_time=on_time.get(int(emp_id), 0),
        )
        out.append(
            Candidate(
                employee_id=int(emp_id),
                display_name=str(display_name),
                department=None if dept_name is None else str(dept_name),
                counts=counts,
                xp=xp_for(counts, active_rules),
                is_demo=bool(is_demo),
            )
        )
    out.sort(key=lambda c: (c.xp, c.counts.tasks_done, -c.employee_id), reverse=True)
    return out


@dataclass
class MyKpi:
    """Личная карточка: всё время + текущая неделя + место в рейтинге."""

    progress: Progress
    week_xp: int
    week_counts: Counts
    week_place: int | None
    week_total: int
    rules: Rules = field(default_factory=lambda: DEFAULT_RULES)
    winner: Winner | None = None


async def my_kpi(session: AsyncSession, employee: Employee, today: date) -> MyKpi:
    """Карточка сотрудника. Читается на профиль, поэтому правила — один раз."""
    rules = await get_rules(session)
    total = await counts_for(session, employee.id)
    monday, sunday = week_bounds(today)
    week = await counts_for(session, employee.id, since=monday, until=sunday)
    table = await board(session, today, rules)
    place = next(
        (i + 1 for i, c in enumerate(table) if c.employee_id == employee.id), None
    )
    return MyKpi(
        progress=progress_for(xp_for(total, rules)),
        week_xp=xp_for(week, rules),
        week_counts=week,
        week_place=place,
        week_total=len(table),
        rules=rules,
        winner=pick_winner(table, rules),
    )
