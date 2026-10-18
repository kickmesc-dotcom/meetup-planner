"""REST API журнала операционных проблем (сотрудник, руководитель, админ).

Отдельный роутер, а не еще один блок в `routes_hr`: журнал живёт дольше смены и
имеет собственную модель прав (`services/hr_issues`), поэтому его ручки проще
читать рядом с сервисом. Как и остальные HR-ручки, всё работает от подписанного
Telegram `initData`: автор, отдел и права берутся из БД, а не из тела запроса.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import EmployeeDep, SessionDep
from app.db.hr_models import (
    ISSUE_CATEGORIES,
    ISSUE_SEVERITIES,
    ISSUE_STATUSES,
    ROLE_ADMIN,
    ROLE_AUP,
    Department,
    Employee,
    Issue,
)
from app.db.models import User
from app.services import hr_issues, hr_notify, hr_simulation

router = APIRouter(tags=["issues"])


# --------------------------------------------------------------------------
# Схемы
# --------------------------------------------------------------------------


class IssueOut(BaseModel):
    id: int
    title: str
    description: str | None
    category: str
    zone: str | None
    severity: str
    status: str
    department_id: int | None
    department_name: str | None
    department_emoji: str | None
    assignee_employee_id: int | None
    assignee_name: str | None
    created_by_employee_id: int | None
    created_by_name: str | None
    task_id: int | None
    shift_date: date
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    # Сколько карточка висит — «2 ч», «3 дня» считает фронт из created_at.
    age_hours: float
    # Права на конкретную карточку: UI прячет кнопки, но решает всё равно сервер.
    can_edit: bool
    can_close: bool
    can_reopen: bool


class IssueEventOut(BaseModel):
    id: int
    kind: str
    from_status: str | None
    to_status: str | None
    by_employee_id: int | None
    by_name: str | None
    comment: str | None
    at: datetime


class IssueDetailOut(IssueOut):
    events: list[IssueEventOut]
    can_comment: bool


class IssueSummaryOut(BaseModel):
    open: int
    in_progress: int
    resolved: int
    cancelled: int
    mine_open: int
    attention: int
    total_open: int


class IssuesOut(BaseModel):
    scope: str
    summary: IssueSummaryOut
    items: list[IssueOut]


class IssueCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    category: str = "other"
    zone: str | None = Field(None, max_length=64)
    severity: str = "normal"
    department_id: int | None = None
    assignee_employee_id: int | None = None
    task_id: int | None = None


class IssueUpdateIn(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    category: str | None = None
    zone: str | None = Field(None, max_length=64)
    severity: str | None = None
    # `assignee_set` отличает «поле не прислали» от «сняли ответственного».
    assignee_employee_id: int | None = None
    assignee_set: bool = False


class IssueStatusIn(BaseModel):
    status: str
    comment: str | None = None


class IssueCommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


# --------------------------------------------------------------------------
# Хелперы сериализации
# --------------------------------------------------------------------------


async def _names(session: AsyncSession, ids: set[int]) -> dict[int, str]:
    """Имена сотрудников одним запросом (для списка и истории)."""
    if not ids:
        return {}
    rows = await session.execute(
        select(Employee.id, User.display_name)
        .join(User, User.id == Employee.user_id)
        .where(Employee.id.in_(ids))
    )
    return {int(employee_id): str(name) for employee_id, name in rows.all()}


async def _departments(
    session: AsyncSession, ids: set[int]
) -> dict[int, tuple[str, str | None]]:
    if not ids:
        return {}
    rows = await session.execute(
        select(Department.id, Department.name, Department.emoji).where(
            Department.id.in_(ids)
        )
    )
    return {int(dep_id): (str(name), emoji) for dep_id, name, emoji in rows.all()}


def _age_hours(issue: Issue) -> float:
    created = issue.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return round((datetime.now(UTC) - created).total_seconds() / 3600, 1)


def _issue_out(
    issue: Issue,
    *,
    viewer: Employee,
    names: dict[int, str],
    departments: dict[int, tuple[str, str | None]],
) -> IssueOut:
    dept = departments.get(issue.department_id) if issue.department_id else None
    return IssueOut(
        id=issue.id,
        title=issue.title,
        description=issue.description,
        category=issue.category,
        zone=issue.zone,
        severity=issue.severity,
        status=issue.status,
        department_id=issue.department_id,
        department_name=dept[0] if dept else None,
        department_emoji=dept[1] if dept else None,
        assignee_employee_id=issue.assignee_employee_id,
        assignee_name=names.get(issue.assignee_employee_id or -1),
        created_by_employee_id=issue.created_by_employee_id,
        created_by_name=names.get(issue.created_by_employee_id or -1),
        task_id=issue.task_id,
        shift_date=issue.shift_date,
        created_at=issue.created_at,
        updated_at=issue.updated_at,
        resolved_at=issue.resolved_at,
        age_hours=_age_hours(issue),
        can_edit=hr_issues.can_edit(viewer, issue),
        can_close=hr_issues.can_close(viewer, issue),
        can_reopen=hr_issues.can_reopen(viewer, issue),
    )


async def _detail(
    session: AsyncSession, issue: Issue, viewer: Employee
) -> IssueDetailOut:
    events = await hr_issues.events_of(session, issue.id)
    ids = {issue.created_by_employee_id, issue.assignee_employee_id} | {
        event.by_employee_id for event in events
    }
    names = await _names(session, {i for i in ids if i is not None})
    departments = await _departments(
        session, {issue.department_id} if issue.department_id else set()
    )
    base = _issue_out(
        issue, viewer=viewer, names=names, departments=departments
    )
    return IssueDetailOut(
        **base.model_dump(),
        events=[
            IssueEventOut(
                id=event.id,
                kind=event.kind,
                from_status=event.from_status,
                to_status=event.to_status,
                by_employee_id=event.by_employee_id,
                by_name=names.get(event.by_employee_id or -1),
                comment=event.comment,
                at=event.at,
            )
            for event in events
        ],
        can_comment=hr_issues.can_view(viewer, issue),
    )


async def _visible_issue(
    session: AsyncSession, issue_id: int, viewer: Employee
) -> Issue:
    issue = await hr_issues.get_issue(session, issue_id)
    # Чужой id не подтверждаем: 404, а не 403 — иначе по ответу можно перебирать
    # существующие карточки.
    if issue is None or not hr_issues.can_view(viewer, issue):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="issue_not_found")
    # Сеанс проверки трогает только свои карточки: иначе тень с ролью админа
    # правила бы настоящий журнал отдела.
    if hr_simulation.current() is not None and not (
        issue.created_by_employee_id == viewer.id
        or issue.assignee_employee_id == viewer.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="issue_not_found")
    return issue


async def _managers_of(session: AsyncSession, issue: Issue) -> list[Employee]:
    """Кому уходит уведомление: руководители этого отдела + администраторы."""
    rows = await session.scalars(
        select(Employee).where(
            Employee.is_active.is_(True),
            Employee.role.in_((ROLE_AUP, ROLE_ADMIN)),
        )
    )
    return [
        employee
        for employee in rows.all()
        if employee.role == ROLE_ADMIN
        or (
            employee.role == ROLE_AUP
            and employee.department_id == issue.department_id
        )
    ]


async def _notify_new_issue(
    session: AsyncSession, issue: Issue, author: Employee
) -> None:
    recipients = [
        employee
        for employee in await _managers_of(session, issue)
        if employee.id != author.id
    ]
    await hr_notify.notify_issue_created(session, issue, recipients)
    if (
        issue.assignee_employee_id is not None
        and issue.assignee_employee_id != author.id
    ):
        assignee = await session.get(Employee, issue.assignee_employee_id)
        if assignee is not None:
            await hr_notify.notify_issue_assigned(session, issue, assignee)


# --------------------------------------------------------------------------
# Ручки
# --------------------------------------------------------------------------


@router.get("/issues", response_model=IssuesOut)
async def list_issues(
    session: SessionDep,
    employee: EmployeeDep,
    statuses: str | None = Query(None, description="через запятую; пусто — открытые"),
    include_closed: bool = False,
    category: str | None = None,
    department_id: int | None = None,
    assignee: int | None = None,
    mine: bool = False,
    limit: int = hr_issues.DEFAULT_LIMIT,
) -> IssuesOut:
    selected: tuple[str, ...] | None = None
    if statuses:
        selected = tuple(s.strip() for s in statuses.split(",") if s.strip())
        unknown = [s for s in selected if s not in ISSUE_STATUSES]
        if unknown:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_status")
    if category is not None and category not in ISSUE_CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_category")

    try:
        items = await hr_issues.list_issues(
            session,
            employee,
            statuses=selected,
            include_closed=include_closed,
            category=category,
            department_id=department_id,
            assignee_employee_id=assignee,
            mine=mine,
            limit=limit,
        )
        counts = await hr_issues.summary(session, employee)
    except hr_issues.IssueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    ids: set[int] = set()
    dept_ids: set[int] = set()
    for issue in items:
        ids.update(
            i
            for i in (
                issue.created_by_employee_id,
                issue.assignee_employee_id,
            )
            if i is not None
        )
        if issue.department_id:
            dept_ids.add(issue.department_id)
    names = await _names(session, ids)
    departments = await _departments(session, dept_ids)

    return IssuesOut(
        scope=hr_issues.scope_for(employee),
        summary=IssueSummaryOut(**counts),
        items=[
            _issue_out(
                issue,
                viewer=employee,
                names=names,
                departments=departments,
            )
            for issue in items
        ],
    )


@router.get("/issues/summary", response_model=IssueSummaryOut)
async def issues_summary(
    session: SessionDep, employee: EmployeeDep
) -> IssueSummaryOut:
    return IssueSummaryOut(**await hr_issues.summary(session, employee))


@router.post("/issues", response_model=IssueDetailOut, status_code=201)
async def create_issue(
    body: IssueCreateIn,
    session: SessionDep,
    employee: EmployeeDep,
) -> IssueDetailOut:
    if body.category not in ISSUE_CATEGORIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_category")
    if body.severity not in ISSUE_SEVERITIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_severity")
    try:
        issue = await hr_issues.create_issue(
            session,
            author=employee,
            title=body.title,
            description=body.description,
            category=body.category,
            zone=body.zone,
            severity=body.severity,
            department_id=body.department_id,
            assignee_employee_id=body.assignee_employee_id,
            task_id=body.task_id,
        )
    except hr_issues.IssueError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if hr_simulation.current() is not None:
        # Проблема сеанса — личная: она не попадает в журнал отдела и никого
        # не уведомляет. Иначе проверка интерфейса будила бы живых людей.
        issue.department_id = None
        issue.assignee_employee_id = employee.id
    else:
        await _notify_new_issue(session, issue, employee)
    await session.commit()
    await session.refresh(issue)
    return await _detail(session, issue, employee)


@router.get("/issues/{issue_id}", response_model=IssueDetailOut)
async def get_issue_api(
    issue_id: int, session: SessionDep, employee: EmployeeDep
) -> IssueDetailOut:
    issue = await _visible_issue(session, issue_id, employee)
    return await _detail(session, issue, employee)


@router.patch("/issues/{issue_id}", response_model=IssueDetailOut)
async def update_issue_api(
    issue_id: int,
    body: IssueUpdateIn,
    session: SessionDep,
    employee: EmployeeDep,
) -> IssueDetailOut:
    issue = await _visible_issue(session, issue_id, employee)
    previous_assignee = issue.assignee_employee_id
    try:
        await hr_issues.update_issue(
            session,
            issue,
            actor=employee,
            title=body.title,
            description=body.description,
            category=body.category,
            zone=body.zone,
            severity=body.severity,
            assignee_employee_id=body.assignee_employee_id,
            assignee_set=body.assignee_set,
        )
    except hr_issues.IssueError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if (
        body.assignee_set
        and issue.assignee_employee_id is not None
        and issue.assignee_employee_id != previous_assignee
        and issue.assignee_employee_id != employee.id
    ):
        assignee = await session.get(Employee, issue.assignee_employee_id)
        if assignee is not None:
            await hr_notify.notify_issue_assigned(session, issue, assignee)

    await session.commit()
    await session.refresh(issue)
    return await _detail(session, issue, employee)


@router.post("/issues/{issue_id}/status", response_model=IssueDetailOut)
async def change_issue_status(
    issue_id: int,
    body: IssueStatusIn,
    session: SessionDep,
    employee: EmployeeDep,
) -> IssueDetailOut:
    issue = await _visible_issue(session, issue_id, employee)
    try:
        await hr_issues.change_status(
            session,
            issue,
            actor=employee,
            new_status=body.status,
            comment=body.comment,
        )
    except hr_issues.IssueError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(issue)
    return await _detail(session, issue, employee)


@router.post("/issues/{issue_id}/comments", response_model=IssueDetailOut)
async def comment_issue(
    issue_id: int,
    body: IssueCommentIn,
    session: SessionDep,
    employee: EmployeeDep,
) -> IssueDetailOut:
    issue = await _visible_issue(session, issue_id, employee)
    try:
        await hr_issues.add_comment(
            session, issue, actor=employee, text=body.text
        )
    except hr_issues.IssueError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(issue)
    return await _detail(session, issue, employee)
