"""Журнал операционных проблем смены.

Зачем отдельная сущность. До сих пор «проблема» была только объяснением при
поручении (`TaskIssue`): есть задача, человек не успел, написал причину. Но
половина реальных проблем смены к поручению не привязана — течёт кран, не
работает терминал, закончились расходники, гость жалуется на шум. Такая
проблема переживает смену: её видят другие, её кому-то передают, её закрывают
через два дня. Поэтому здесь своя карточка (`Issue`) и своя история
(`IssueEvent`), а `task_id` — необязательная ссылка на поручение.

Права (проверяются здесь, а не в UI):

* сотрудник видит проблемы своего подразделения плюс те, что создал или на
  которые назначен;
* руководитель подразделения (`aup`) — весь свой отдел;
* администратор — всё;
* редактировать открытую карточку может автор и руководитель; закрывать —
  автор, ответственный или руководитель; переоткрывать — только руководитель.

Чистые функции (`scope_for`, `can_view`, `can_transition`, `can_assign`)
вынесены наружу: именно они решают, можно ли трогать карточку, и их удобно
проверять без базы.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import structlog
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    ISSUE_CANCELLED,
    ISSUE_CATEGORIES,
    ISSUE_IN_PROGRESS,
    ISSUE_OPEN,
    ISSUE_RESOLVED,
    ISSUE_SEVERITIES,
    ISSUE_SEVERITY_NORMAL,
    ISSUE_STATUSES,
    Employee,
    Issue,
    IssueEvent,
)
from app.services import hr_access, hr_checklists

log = structlog.get_logger()

SCOPE_SELF = "self"
SCOPE_DEPARTMENT = "department"
SCOPE_ALL = "all"

OPEN_STATUSES: frozenset[str] = frozenset({ISSUE_OPEN, ISSUE_IN_PROGRESS})

# Закрытая карточка не «умирает»: проблему можно переоткрыть, если она вернулась.
# Отменённая (`cancelled`) — ложная тревога; из неё тоже можно вернуться в работу.
_TRANSITIONS: dict[str, frozenset[str]] = {
    ISSUE_OPEN: frozenset({ISSUE_IN_PROGRESS, ISSUE_RESOLVED, ISSUE_CANCELLED}),
    ISSUE_IN_PROGRESS: frozenset({ISSUE_OPEN, ISSUE_RESOLVED, ISSUE_CANCELLED}),
    ISSUE_RESOLVED: frozenset({ISSUE_OPEN}),
    ISSUE_CANCELLED: frozenset({ISSUE_OPEN}),
}

_STATUS_RANK: dict[str, int] = {
    ISSUE_OPEN: 0,
    ISSUE_IN_PROGRESS: 1,
    ISSUE_RESOLVED: 2,
    ISSUE_CANCELLED: 3,
}
_SEVERITY_RANK: dict[str, int] = {"low": 0, "normal": 1, "high": 2, "critical": 3}

EVENT_CREATED = "created"
EVENT_STATUS = "status"
EVENT_ASSIGNEE = "assignee"
EVENT_COMMENT = "comment"
EVENT_EDITED = "edited"

DEFAULT_LIMIT = 100
MAX_LIMIT = 300


class IssueError(Exception):
    """Нарушение правил журнала (передаётся в API как 4xx-код)."""


# --------------------------------------------------------------------------
# Чистые правила
# --------------------------------------------------------------------------


def scope_for(employee: Employee) -> str:
    """Что человек видит в журнале: всё / свой отдел / только своё.

    Журнал — общий для смены: операционные проблемы отдела (нет горячей воды,
    сломан терминал) должны быть видны всем, кто в эту смену работает, иначе
    люди снова и снова наступают на одни и те же грабли. Сотрудник без отдела
    (онбординг не пройден) видит только то, что создал или где он ответственный.
    Управлять карточкой всё равно может только автор и руководитель — видимость
    на правку не влияет (`can_edit`).
    """
    if hr_access.is_admin(employee):
        return SCOPE_ALL
    if employee.department_id is not None:
        return SCOPE_DEPARTMENT
    return SCOPE_SELF


def _is_related(employee: Employee, issue: Issue) -> bool:
    """Создал проблему или назначен на неё — своё в любом случае видно."""
    return (
        issue.created_by_employee_id == employee.id
        or issue.assignee_employee_id == employee.id
    )


def can_view(employee: Employee, issue: Issue) -> bool:
    scope = scope_for(employee)
    if scope == SCOPE_ALL:
        return True
    if _is_related(employee, issue):
        return True
    if scope == SCOPE_DEPARTMENT:
        return (
            employee.department_id is not None
            and issue.department_id == employee.department_id
        )
    return False


def can_moderate(employee: Employee, issue: Issue) -> bool:
    """Руководитель своего отдела или админ — но не «любой aup» в чужом отделе."""
    if hr_access.is_admin(employee):
        return True
    if not hr_access.is_aup(employee):
        return False
    return employee.department_id is not None and (
        issue.department_id == employee.department_id
        or _is_related(employee, issue)
    )


def can_edit(employee: Employee, issue: Issue) -> bool:
    """Правка полей карточки.

    Руководитель правит любую свою карточку в любом статусе. Автор — только
    пока проблема не взята в работу: дальше формулировка и срочность уже часть
    общей картины смены, и менять её в одностороннем порядке нельзя. Закрытую
    карточку не правит никто, кроме руководителя.
    """
    if can_moderate(employee, issue):
        return True
    return (
        issue.created_by_employee_id == employee.id
        and issue.status == ISSUE_OPEN
    )


def can_close(employee: Employee, issue: Issue) -> bool:
    """Закрыть (решено/отменено) может автор, ответственный или руководитель."""
    if can_moderate(employee, issue):
        return True
    return _is_related(employee, issue)


def can_assign(employee: Employee, target_employee_id: int | None) -> bool:
    """Ответственного ставит руководитель; сотрудник — только себя."""
    if hr_access.is_aup(employee):
        return True
    return target_employee_id == employee.id


def can_reopen(employee: Employee, issue: Issue) -> bool:
    return can_moderate(employee, issue)


def can_transition(current: str, new: str) -> bool:
    if current not in ISSUE_STATUSES or new not in ISSUE_STATUSES:
        return False
    return new in _TRANSITIONS.get(current, frozenset())


def is_open(issue: Issue) -> bool:
    return issue.status in OPEN_STATUSES


# --------------------------------------------------------------------------
# Создание и правка
# --------------------------------------------------------------------------


def _event(
    issue: Issue,
    *,
    kind: str,
    by: Employee | None,
    from_status: str | None = None,
    to_status: str | None = None,
    comment: str | None = None,
) -> IssueEvent:
    return IssueEvent(
        issue_id=issue.id,
        kind=kind,
        from_status=from_status,
        to_status=to_status,
        by_employee_id=by.id if by is not None else None,
        comment=comment,
    )


async def create_issue(
    session: AsyncSession,
    *,
    author: Employee,
    title: str,
    description: str | None = None,
    category: str = "other",
    zone: str | None = None,
    severity: str = ISSUE_SEVERITY_NORMAL,
    department_id: int | None = None,
    assignee_employee_id: int | None = None,
    task_id: int | None = None,
    shift_date: date | None = None,
) -> Issue:
    """Завести карточку проблемы. Автор всегда фиксируется.

    Отдел по умолчанию — отдел автора: проблема смены почти всегда «здесь».
    Ответственного сотрудник может поставить только себе, остальным — лишь
    руководитель (`can_assign`).
    """
    clean_title = (title or "").strip()
    if not clean_title:
        raise IssueError("empty_title")
    if len(clean_title) > 200:
        raise IssueError("title_too_long")
    if category not in ISSUE_CATEGORIES:
        raise IssueError("bad_category")
    if severity not in ISSUE_SEVERITIES:
        raise IssueError("bad_severity")

    department = department_id if department_id is not None else author.department_id
    if department is not None:
        from app.services import hr_departments

        dept = await hr_departments.get_department(session, department)
        if dept is None or not dept.is_active:
            raise IssueError("department_unavailable")

    if assignee_employee_id is not None and not can_assign(author, assignee_employee_id):
        raise IssueError("assignee_forbidden")
    if assignee_employee_id is not None:
        assignee = await session.get(Employee, assignee_employee_id)
        if assignee is None or not assignee.is_active:
            raise IssueError("assignee_unavailable")

    if task_id is not None:
        from app.db.hr_models import Task

        if await session.get(Task, task_id) is None:
            raise IssueError("task_not_found")

    issue = Issue(
        title=clean_title,
        description=(description or "").strip() or None,
        category=category,
        zone=(zone or "").strip()[:64] or None,
        severity=severity,
        status=ISSUE_OPEN,
        department_id=department,
        assignee_employee_id=assignee_employee_id,
        created_by_employee_id=author.id,
        task_id=task_id,
        shift_date=shift_date or hr_checklists.local_today(),
    )
    session.add(issue)
    await session.flush()

    session.add(
        _event(issue, kind=EVENT_CREATED, by=author, to_status=ISSUE_OPEN)
    )
    if assignee_employee_id is not None:
        session.add(
            _event(
                issue,
                kind=EVENT_ASSIGNEE,
                by=author,
                comment=f"назначен:{assignee_employee_id}",
            )
        )
    await session.flush()
    log.info(
        "hr.issue_created",
        issue_id=issue.id,
        by=author.id,
        category=category,
        severity=severity,
    )
    return issue


async def change_status(
    session: AsyncSession,
    issue: Issue,
    *,
    actor: Employee,
    new_status: str,
    comment: str | None = None,
) -> Issue:
    """Перевести карточку в новый статус с проверкой прав и перехода."""
    if not can_view(actor, issue):
        raise IssueError("forbidden")
    if new_status not in ISSUE_STATUSES:
        raise IssueError("bad_status")

    current = issue.status
    if current == new_status:
        return issue
    if not can_transition(current, new_status):
        raise IssueError("bad_transition")
    if current in OPEN_STATUSES:
        if new_status != ISSUE_IN_PROGRESS and not can_close(actor, issue):
            raise IssueError("forbidden")
        if new_status == ISSUE_IN_PROGRESS and not can_edit(actor, issue):
            raise IssueError("forbidden")
    elif not can_reopen(actor, issue):
        raise IssueError("forbidden")

    issue.status = new_status
    if new_status in OPEN_STATUSES:
        issue.resolved_at = None
    else:
        issue.resolved_at = datetime.now(UTC)
    issue.updated_at = datetime.now(UTC)

    session.add(
        _event(
            issue,
            kind=EVENT_STATUS,
            by=actor,
            from_status=current,
            to_status=new_status,
            comment=(comment or "").strip() or None,
        )
    )
    await session.flush()
    return issue


async def update_issue(
    session: AsyncSession,
    issue: Issue,
    *,
    actor: Employee,
    title: str | None = None,
    description: str | None = None,
    category: str | None = None,
    zone: str | None = None,
    severity: str | None = None,
    assignee_employee_id: int | None = None,
    assignee_set: bool = False,
) -> Issue:
    """Точечная правка карточки. `assignee_set` различает «не трогали» и «сняли»."""
    if not can_edit(actor, issue):
        raise IssueError("forbidden")
    if issue.status not in OPEN_STATUSES and not can_moderate(actor, issue):
        raise IssueError("issue_closed")

    changed: list[str] = []
    if title is not None:
        clean = title.strip()
        if not clean:
            raise IssueError("empty_title")
        if len(clean) > 200:
            raise IssueError("title_too_long")
        if clean != issue.title:
            issue.title = clean
            changed.append("title")
    if description is not None:
        clean_desc = description.strip() or None
        if clean_desc != issue.description:
            issue.description = clean_desc
            changed.append("description")
    if category is not None:
        if category not in ISSUE_CATEGORIES:
            raise IssueError("bad_category")
        if category != issue.category:
            issue.category = category
            changed.append("category")
    if zone is not None:
        clean_zone = zone.strip()[:64] or None
        if clean_zone != issue.zone:
            issue.zone = clean_zone
            changed.append("zone")
    if severity is not None:
        if severity not in ISSUE_SEVERITIES:
            raise IssueError("bad_severity")
        if severity != issue.severity:
            issue.severity = severity
            changed.append("severity")
    if assignee_set:
        if not can_assign(actor, assignee_employee_id):
            raise IssueError("assignee_forbidden")
        if assignee_employee_id is not None:
            assignee = await session.get(Employee, assignee_employee_id)
            if assignee is None or not assignee.is_active:
                raise IssueError("assignee_unavailable")
        if assignee_employee_id != issue.assignee_employee_id:
            issue.assignee_employee_id = assignee_employee_id
            changed.append("assignee")
            session.add(
                _event(
                    issue,
                    kind=EVENT_ASSIGNEE,
                    by=actor,
                    comment=(
                        f"назначен:{assignee_employee_id}"
                        if assignee_employee_id is not None
                        else "снят"
                    ),
                )
            )

    if not changed:
        return issue

    issue.updated_at = datetime.now(UTC)
    session.add(
        _event(
            issue,
            kind=EVENT_EDITED,
            by=actor,
            comment=",".join(changed),
        )
    )
    await session.flush()
    return issue


async def add_comment(
    session: AsyncSession, issue: Issue, *, actor: Employee, text: str
) -> IssueEvent:
    """Комментарий в историю. Пустой текст — ошибка, а не «тихий» no-op."""
    if not can_view(actor, issue):
        raise IssueError("forbidden")
    clean = (text or "").strip()
    if not clean:
        raise IssueError("empty_comment")
    if len(clean) > 2000:
        raise IssueError("comment_too_long")

    event = _event(issue, kind=EVENT_COMMENT, by=actor, comment=clean)
    session.add(event)
    issue.updated_at = datetime.now(UTC)
    await session.flush()
    return event


# --------------------------------------------------------------------------
# Выборки
# --------------------------------------------------------------------------


def visible_filter(employee: Employee):
    """SQL-условие «что этому человеку видно» — одно правило для списка и счётчиков."""
    scope = scope_for(employee)
    own = or_(
        Issue.created_by_employee_id == employee.id,
        Issue.assignee_employee_id == employee.id,
    )
    if scope == SCOPE_ALL:
        return None
    if scope == SCOPE_DEPARTMENT and employee.department_id is not None:
        return or_(Issue.department_id == employee.department_id, own)
    return own


async def list_issues(
    session: AsyncSession,
    employee: Employee,
    *,
    statuses: tuple[str, ...] | None = None,
    include_closed: bool = False,
    category: str | None = None,
    department_id: int | None = None,
    assignee_employee_id: int | None = None,
    mine: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> list[Issue]:
    """Журнал: сначала открытые и срочные, потом остальные. Свежие — выше."""
    stmt = select(Issue)
    condition = visible_filter(employee)
    if condition is not None:
        stmt = stmt.where(condition)
    # Проблемы сеанса проверки не попадают в реальный журнал.
    if not employee.is_simulation:
        stmt = stmt.where(
            or_(
                Issue.created_by_employee_id.is_(None),
                Issue.created_by_employee_id.notin_(
                    select(Employee.id).where(Employee.is_simulation.is_(True))
                ),
            )
        )

    if statuses:
        unknown = [s for s in statuses if s not in ISSUE_STATUSES]
        if unknown:
            raise IssueError("bad_status")
        stmt = stmt.where(Issue.status.in_(statuses))
    elif not include_closed:
        stmt = stmt.where(Issue.status.in_(tuple(OPEN_STATUSES)))

    if category:
        if category not in ISSUE_CATEGORIES:
            raise IssueError("bad_category")
        stmt = stmt.where(Issue.category == category)
    if department_id is not None:
        stmt = stmt.where(Issue.department_id == department_id)
    if assignee_employee_id is not None:
        stmt = stmt.where(Issue.assignee_employee_id == assignee_employee_id)
    if mine:
        stmt = stmt.where(
            or_(
                Issue.created_by_employee_id == employee.id,
                Issue.assignee_employee_id == employee.id,
            )
        )

    capped = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    stmt = stmt.order_by(
        case(_STATUS_RANK, value=Issue.status),
        case(_SEVERITY_RANK, value=Issue.severity).desc(),
        Issue.updated_at.desc(),
        Issue.id.desc(),
    ).limit(capped)

    rows = await session.scalars(stmt)
    return list(rows.all())


async def get_issue(session: AsyncSession, issue_id: int) -> Issue | None:
    return await session.get(Issue, issue_id)


async def events_of(session: AsyncSession, issue_id: int) -> list[IssueEvent]:
    rows = await session.scalars(
        select(IssueEvent)
        .where(IssueEvent.issue_id == issue_id)
        .order_by(IssueEvent.at, IssueEvent.id)
    )
    return list(rows.all())


async def summary(session: AsyncSession, employee: Employee) -> dict[str, int]:
    """Счётчики для шапки журнала и бейджа «есть проблемы»."""
    condition = visible_filter(employee)
    stmt = select(Issue.status, func.count()).select_from(Issue).group_by(Issue.status)
    if condition is not None:
        stmt = stmt.where(condition)
    if not employee.is_simulation:
        stmt = stmt.where(
            or_(
                Issue.created_by_employee_id.is_(None),
                Issue.created_by_employee_id.notin_(
                    select(Employee.id).where(Employee.is_simulation.is_(True))
                ),
            )
        )
    rows = await session.execute(stmt)
    counts = {str(status): int(count) for status, count in rows.all()}

    mine_stmt = (
        select(func.count())
        .select_from(Issue)
        .where(
            Issue.status.in_(tuple(OPEN_STATUSES)),
            or_(
                Issue.created_by_employee_id == employee.id,
                Issue.assignee_employee_id == employee.id,
            ),
        )
    )
    mine_open = int(await session.scalar(mine_stmt) or 0)

    attention_stmt = (
        select(func.count())
        .select_from(Issue)
        .where(
            Issue.status.in_(tuple(OPEN_STATUSES)),
            Issue.severity.in_(("high", "critical")),
        )
    )
    if condition is not None:
        attention_stmt = attention_stmt.where(condition)
    if not employee.is_simulation:
        attention_stmt = attention_stmt.where(
            or_(
                Issue.created_by_employee_id.is_(None),
                Issue.created_by_employee_id.notin_(
                    select(Employee.id).where(Employee.is_simulation.is_(True))
                ),
            )
        )
    attention = int(await session.scalar(attention_stmt) or 0)

    return {
        "open": counts.get(ISSUE_OPEN, 0),
        "in_progress": counts.get(ISSUE_IN_PROGRESS, 0),
        "resolved": counts.get(ISSUE_RESOLVED, 0),
        "cancelled": counts.get(ISSUE_CANCELLED, 0),
        "mine_open": mine_open,
        "attention": attention,
        "total_open": counts.get(ISSUE_OPEN, 0) + counts.get(ISSUE_IN_PROGRESS, 0),
    }
