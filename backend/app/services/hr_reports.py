"""Отчёт смены и пробелы по стандартам.

Два вопроса руководителя, на которые не отвечала сводка кабинета:

1. «Что было в смене 12-го числа?» — кабинет показывает только сегодня и
   только живые цифры. Здесь отчёт собирается на выбранную дату и отдел
   (чек-листы, поручения по статусам, проблемы) и выгружается в CSV.
2. «Кто не знает обязательную инструкцию?» — стандарты проверялись только
   личным прогрессом сотрудника. Теперь у стандарта есть `is_required`, а
   отчёт показывает по каждому обязательному стандарту, сколько людей отдела
   его сдали и кто именно ещё нет.

Почему отдельный сервис, а не расширение `hr_ops`. Кабинет — это «что горит
прямо сейчас»: он читает открытые задачи и текущее время. Отчёт — срез на
дату, он не зависит от «сейчас» и не должен случайно показывать сегодняшние
просрочки за прошлую смену. Общими остаются только правила прав и зона
видимости (`hr_ops.viewer_scope`).

Считаем на чтение: отчёт не создаёт прогоны смены и не двигает статусы.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.hr_models import (
    ISSUE_CANCELLED,
    RUN_DONE,
    TASK_DONE,
    TASK_FAILED,
    TASK_ON_REVIEW,
    TASK_OVERDUE,
    ChecklistRun,
    Department,
    Employee,
    Issue,
    Standard,
    StandardCheck,
    Task,
)
from app.db.models import User
from app.services import hr_access, hr_demo, hr_ops, hr_tasks

SCOPE_ALL = "all"
SCOPE_DEPARTMENT = "department"

# Открытые проблемы — те, что ещё требуют работы. `resolved`/`cancelled`
# остаются в журнале, но в «сейчас болит» не попадают.
OPEN_ISSUE_STATUSES: frozenset[str] = frozenset({"open", "in_progress"})


@dataclass(frozen=True)
class PersonRef:
    """Кто не сдал стандарт: только id и имя, без лишних полей."""

    employee_id: int
    display_name: str
    department_id: int | None = None


@dataclass(frozen=True)
class StandardCoverage:
    """Сколько людей отдела сдали стандарт и кто ещё нет."""

    standard_id: int
    title: str
    emoji: str | None
    department_id: int | None
    department_name: str | None
    required: bool
    passed: int
    total: int
    missing: list[PersonRef] = field(default_factory=list)


@dataclass(frozen=True)
class DepartmentRow:
    department_id: int
    name: str
    emoji: str | None
    employees: int
    shifts_started: int
    shifts_done: int
    tasks_shift: int
    tasks_done: int
    tasks_on_review: int
    tasks_overdue: int
    issues_open: int
    required_gaps: int


@dataclass(frozen=True)
class ShiftReport:
    work_date: date
    scope: str
    department_id: int | None
    departments: list[DepartmentRow] = field(default_factory=list)
    employees_total: int = 0
    shifts_started: int = 0
    shifts_done: int = 0
    tasks_shift: int = 0
    tasks_done: int = 0
    tasks_on_review: int = 0
    tasks_overdue: int = 0
    tasks_failed: int = 0
    tasks_open: int = 0
    issues_open: int = 0
    issues_new: int = 0
    standards: list[StandardCoverage] = field(default_factory=list)
    required_gaps: int = 0


# --------------------------------------------------------------------------
# Чистые правила (тестируются без базы)
# --------------------------------------------------------------------------


def resolve_scope(
    viewer: Employee, requested_department_id: int | None = None
) -> tuple[str, int | None]:
    """Какой срез можно показать этому руководителю.

    Администратор смотрит всё и может выбрать отдел. Руководитель отдела
    всегда заперт в своём подразделении: чужой `department_id` в query —
    не ошибка, а попытка выйти за права, поэтому молча подменяем на свой.
    """
    if hr_ops.viewer_scope(viewer) == SCOPE_ALL:
        return SCOPE_ALL, requested_department_id
    return SCOPE_DEPARTMENT, viewer.department_id


def coverage_percent(passed: int, total: int) -> int:
    """Процент сдачи; пустая выборка — 0, а не деление на ноль."""
    if total <= 0:
        return 0
    return round(passed * 100 / total)


def required_gap(standard: StandardCoverage) -> bool:
    """Обязательный стандарт, который сдал не каждый, — это пробел отчёта."""
    return standard.required and standard.passed < standard.total


def task_counts(statuses: list[str]) -> dict[str, int]:
    """Разложить статусы поручений смены по корзинам отчёта.

    `on_review` считаем отдельно от `done`: работа сдана, но её ещё никто не
    принял — для руководителя это не «закрыто».
    """
    counts = {TASK_DONE: 0, TASK_ON_REVIEW: 0, TASK_OVERDUE: 0, TASK_FAILED: 0}
    for status in statuses:
        if status in counts:
            counts[status] += 1
    counts["other"] = len(statuses) - sum(counts.values())
    counts["total"] = len(statuses)
    return counts


def csv_cell(value: object) -> str:
    """Экранировать ячейку CSV: `;` — разделитель, переводы строк ломают строку."""
    text = "" if value is None else str(value)
    text = text.replace("\r", " ").replace("\n", " ")
    if any(ch in text for ch in (";", '"')):
        return '"' + text.replace('"', '""') + '"'
    return text


def to_csv(report: ShiftReport) -> str:
    """Отчёт в CSV для Excel: `;`-разделитель и заголовки по-русски.

    Файл не претендует на машинный формат — его открывает руководитель.
    Поэтому секции подписаны словами, а не кодами: «Поручений за смену;12».
    """
    rows: list[list[object]] = [
        ["Отчёт смены", report.work_date.isoformat()],
        ["Срез", "всё" if report.scope == SCOPE_ALL else "подразделение"],
        [],
        ["Показатель", "Значение"],
        ["Сотрудников", report.employees_total],
        ["Смен начато", report.shifts_started],
        ["Смен закрыто", report.shifts_done],
        ["Поручений за смену", report.tasks_shift],
        ["Поручений выполнено", report.tasks_done],
        ["Поручений на проверке", report.tasks_on_review],
        ["Поручений просрочено", report.tasks_overdue],
        ["Поручений провалено", report.tasks_failed],
        ["Открытых поручений сейчас", report.tasks_open],
        ["Открытых проблем", report.issues_open],
        ["Проблем за смену", report.issues_new],
        ["Пробелов по обязательным стандартам", report.required_gaps],
        [],
    ]

    if report.departments:
        rows.append(["Подразделение", "Людей", "Смен начато", "Смен закрыто",
                     "Поручений", "Выполнено", "На проверке", "Просрочено",
                     "Проблем открыто", "Пробелов по стандартам"])
        for dept in report.departments:
            rows.append([
                dept.name,
                dept.employees,
                dept.shifts_started,
                dept.shifts_done,
                dept.tasks_shift,
                dept.tasks_done,
                dept.tasks_on_review,
                dept.tasks_overdue,
                dept.issues_open,
                dept.required_gaps,
            ])
        rows.append([])

    if report.standards:
        rows.append(["Стандарт", "Обязательный", "Сдали", "Всего", "Процент", "Не сдали"])
        for standard in report.standards:
            rows.append([
                standard.title,
                "да" if standard.required else "нет",
                standard.passed,
                standard.total,
                coverage_percent(standard.passed, standard.total),
                ", ".join(person.display_name for person in standard.missing),
            ])

    return "\r\n".join(";".join(csv_cell(cell) for cell in row) for row in rows)


def format_telegram(report: ShiftReport, *, limit: int = 3) -> str:
    """Короткий текст отчёта для бота.

    В сообщение попадает верхушка пробелов: длинный список имён в чате
    нечитаем, полный срез — в приложении и CSV.
    """
    lines = [
        f"📊 <b>Смена {report.work_date.strftime('%d.%m.%Y')}</b>",
        (
            f"Людей: {report.employees_total} · смен начато {report.shifts_started} "
            f"· закрыто {report.shifts_done}"
        ),
        (
            f"Поручения: {report.tasks_shift} · выполнено {report.tasks_done} "
            f"· на проверке {report.tasks_on_review} · просрочено {report.tasks_overdue}"
        ),
        (
            f"Сейчас открыто: {report.tasks_open} поручений, "
            f"{report.issues_open} проблем"
        ),
    ]
    gaps = [standard for standard in report.standards if required_gap(standard)]
    if gaps:
        lines.append("")
        lines.append(f"<b>Обязательные стандарты: пробелов {len(gaps)}</b>")
        for standard in gaps[:limit]:
            names = ", ".join(person.display_name for person in standard.missing[:4])
            if len(standard.missing) > 4:
                names += f" и ещё {len(standard.missing) - 4}"
            lines.append(f"• {standard.title}: {names}")
        if len(gaps) > limit:
            lines.append(f"…и ещё {len(gaps) - limit}")
    elif report.standards:
        lines.append("")
        lines.append("Обязательные стандарты сданы ✅")
    return "\n".join(lines)


def local_today(now: datetime | None = None) -> date:
    tz = ZoneInfo(get_settings().scheduler_tz)
    moment = now or datetime.now(tz=tz)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    return moment.astimezone(tz).date()


# --------------------------------------------------------------------------
# Сборка отчёта
# --------------------------------------------------------------------------


async def _scope_employees(
    session: AsyncSession, department_id: int | None
) -> list[tuple[Employee, User]]:
    hidden = await hr_demo.hidden_employee_ids(session)
    rows = (
        await session.execute(
            select(Employee, User)
            .join(User, User.id == Employee.user_id)
            .where(Employee.is_active.is_(True))
            .order_by(Employee.id)
        )
    ).all()
    return [
        (employee, user)
        for employee, user in rows
        if int(employee.id) not in hidden
        and (
            department_id is None
            or employee.department_id == department_id
        )
    ]


async def _standards_coverage(
    session: AsyncSession,
    *,
    people: list[tuple[Employee, User]],
    department_names: dict[int, str],
) -> list[StandardCoverage]:
    """По каждому активному стандарту — кто из людей среза его сдал."""
    standards = list(
        (
            await session.scalars(
                select(Standard)
                .where(Standard.is_active.is_(True))
                .order_by(Standard.is_required.desc(), Standard.sort_order, Standard.id)
            )
        ).all()
    )
    if not standards:
        return []

    employee_ids = [int(employee.id) for employee, _ in people]
    passed_pairs: set[tuple[int, int]] = set()
    if employee_ids:
        for standard_id, employee_id in (
            await session.execute(
                select(StandardCheck.standard_id, StandardCheck.employee_id)
                .where(
                    StandardCheck.passed.is_(True),
                    StandardCheck.employee_id.in_(employee_ids),
                )
                .distinct()
            )
        ).all():
            passed_pairs.add((int(standard_id), int(employee_id)))

    by_department: dict[int | None, list[tuple[Employee, User]]] = {}
    for pair in people:
        by_department.setdefault(pair[0].department_id, []).append(pair)

    coverage: list[StandardCoverage] = []
    for standard in standards:
        # Общий стандарт касается всех; отдельный — только своего отдела.
        applicable = (
            people
            if standard.department_id is None
            else by_department.get(int(standard.department_id), [])
        )
        if not applicable:
            # Стандарт чужого отдела в срез не тянем: руководителю он не нужен.
            continue
        missing = [
            PersonRef(
                employee_id=int(employee.id),
                display_name=user.display_name,
                department_id=employee.department_id,
            )
            for employee, user in applicable
            if (int(standard.id), int(employee.id)) not in passed_pairs
        ]
        missing.sort(key=lambda person: person.display_name.lower())
        coverage.append(
            StandardCoverage(
                standard_id=int(standard.id),
                title=standard.title,
                emoji=standard.emoji,
                department_id=standard.department_id,
                department_name=(
                    department_names.get(int(standard.department_id))
                    if standard.department_id
                    else None
                ),
                required=bool(standard.is_required),
                passed=len(applicable) - len(missing),
                total=len(applicable),
                missing=missing,
            )
        )
    return coverage


async def build_shift_report(
    session: AsyncSession,
    *,
    viewer: Employee,
    on: date | None = None,
    department_id: int | None = None,
) -> ShiftReport:
    """Срез смены на дату. Права уже проверены ручкой (`AupDep`)."""
    scope, selected_department = resolve_scope(viewer, department_id)
    work_date = on or local_today()
    if not hr_access.is_aup(viewer):  # защита от вызова сервиса в обход ручки
        raise PermissionError("aup_required")

    departments = list(
        (
            await session.scalars(
                select(Department)
                .where(Department.is_active.is_(True))
                .order_by(Department.sort_order, Department.id)
            )
        ).all()
    )
    if selected_department is not None:
        departments = [d for d in departments if int(d.id) == selected_department]
    department_names = {int(d.id): d.name for d in departments}
    if selected_department is not None:
        department_names.setdefault(selected_department, "")

    scoped_department = (
        selected_department if scope == SCOPE_ALL else viewer.department_id
    )
    people = await _scope_employees(session, scoped_department)
    employee_ids = [int(employee.id) for employee, _ in people]
    department_of = {int(employee.id): employee.department_id for employee, _ in people}

    runs: dict[int, bool] = {}
    runs_done: set[int] = set()
    if employee_ids:
        for employee_id, status in (
            await session.execute(
                select(ChecklistRun.employee_id, ChecklistRun.status)
                .where(
                    ChecklistRun.shift_date == work_date,
                    ChecklistRun.employee_id.in_(employee_ids),
                )
            )
        ).all():
            runs[int(employee_id)] = True
            if status == RUN_DONE:
                runs_done.add(int(employee_id))

    # Зона видимости: `selected_department is None` при `scope == all` означает
    # «всё», иначе сравниваем только с выбранным (или своим) отделом. Задача без
    # отдела попадает в срез через исполнителя.
    allowed_department = (
        selected_department if scope == SCOPE_ALL else viewer.department_id
    )
    team_ids = set(employee_ids)

    def task_in_scope(task: Task) -> bool:
        if task.department_id is not None:
            return allowed_department is None or task.department_id == allowed_department
        return task.assignee_employee_id in team_ids

    def issue_in_scope(issue: Issue) -> bool:
        if issue.department_id is not None:
            return allowed_department is None or issue.department_id == allowed_department
        return issue.employee_id in team_ids or issue.assignee_employee_id in team_ids

    tasks = [
        task
        for task in (
            await session.scalars(select(Task).where(Task.shift_date == work_date))
        ).all()
        if task_in_scope(task)
    ]
    counts = task_counts([task.status for task in tasks])

    open_tasks = [
        task
        for task in (
            await session.scalars(
                select(Task).where(Task.status.in_(tuple(hr_tasks.OPEN_STATUSES)))
            )
        ).all()
        if task_in_scope(task)
    ]

    issues = [
        issue
        for issue in (
            await session.scalars(
                select(Issue).where(Issue.status.in_(tuple(OPEN_ISSUE_STATUSES)))
            )
        ).all()
        if issue_in_scope(issue)
    ]
    issues_new = len(
        [
            issue
            for issue in (
                await session.scalars(
                    select(Issue).where(
                        Issue.shift_date == work_date,
                        Issue.status != ISSUE_CANCELLED,
                    )
                )
            ).all()
            if issue_in_scope(issue)
        ]
    )

    standards = await _standards_coverage(
        session, people=people, department_names=department_names
    )

    rows: list[DepartmentRow] = []
    for department in departments:
        dept_id = int(department.id)
        team = [employee_id for employee_id, dept in department_of.items() if dept == dept_id]
        dept_tasks = [
            task for task in tasks
            if task.department_id == dept_id or task.assignee_employee_id in team
        ]
        dept_counts = task_counts([task.status for task in dept_tasks])
        dept_issues = [
            issue for issue in issues
            if issue.department_id == dept_id
            or issue.employee_id in team
            or issue.assignee_employee_id in team
        ]
        dept_gaps = len(
            [
                standard
                for standard in standards
                if required_gap(standard)
                and (
                    standard.department_id == dept_id
                    or standard.department_id is None
                )
            ]
        )
        rows.append(
            DepartmentRow(
                department_id=dept_id,
                name=department.name,
                emoji=department.emoji,
                employees=len(team),
                shifts_started=sum(1 for employee_id in team if employee_id in runs),
                shifts_done=sum(1 for employee_id in team if employee_id in runs_done),
                tasks_shift=dept_counts["total"],
                tasks_done=dept_counts[TASK_DONE],
                tasks_on_review=dept_counts[TASK_ON_REVIEW],
                tasks_overdue=dept_counts[TASK_OVERDUE],
                issues_open=len(dept_issues),
                required_gaps=dept_gaps,
            )
        )

    return ShiftReport(
        work_date=work_date,
        scope=scope,
        department_id=selected_department if scope == SCOPE_ALL else viewer.department_id,
        departments=rows,
        employees_total=len(people),
        shifts_started=len(runs),
        shifts_done=len(runs_done),
        tasks_shift=counts["total"],
        tasks_done=counts[TASK_DONE],
        tasks_on_review=counts[TASK_ON_REVIEW],
        tasks_overdue=counts[TASK_OVERDUE],
        tasks_failed=counts[TASK_FAILED],
        tasks_open=len({int(task.id) for task in open_tasks}),
        issues_open=len({int(issue.id) for issue in issues}),
        issues_new=issues_new,
        standards=standards,
        required_gaps=len([standard for standard in standards if required_gap(standard)]),
    )


async def standards_gaps(
    session: AsyncSession,
    *,
    viewer: Employee,
    department_id: int | None = None,
    required_only: bool = True,
) -> list[StandardCoverage]:
    """Только пробелы по стандартам — для отдельной ручки и напоминаний."""
    scope, selected = resolve_scope(viewer, department_id)
    people = await _scope_employees(
        session, selected if scope == SCOPE_ALL else viewer.department_id
    )
    departments = list(
        (
            await session.scalars(
                select(Department).order_by(Department.sort_order, Department.id)
            )
        ).all()
    )
    names = {int(d.id): d.name for d in departments}
    coverage = await _standards_coverage(session, people=people, department_names=names)
    if required_only:
        coverage = [standard for standard in coverage if standard.required]
    return coverage


__all__ = [
    "OPEN_ISSUE_STATUSES",
    "DepartmentRow",
    "PersonRef",
    "ShiftReport",
    "StandardCoverage",
    "build_shift_report",
    "coverage_percent",
    "csv_cell",
    "format_telegram",
    "local_today",
    "required_gap",
    "resolve_scope",
    "standards_gaps",
    "task_counts",
    "to_csv",
]
