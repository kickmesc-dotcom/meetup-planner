"""Управляющий REST API HR-ядра (АУП и администратор).

Разделение прав строго по брифу (п.9 mainPROMT):

* **АУП** (`AupDep`): создаёт/ведёт поручения, смотрит отчёты и обратную связь.
* **Администратор** (`AdminDep`): всё выше + подразделения, чек-листы, ссылки,
  вопросы обратной связи, роли сотрудников.

Права проверяются зависимостями, а не «фронт спрятал кнопку»: без нужной роли
ручка отвечает 403 ещё до тела. Это позволяет администрации править всё
перечисленное без разработчика (шаг 2, п.3, п.8 mainPROMT).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, or_, select

from app.api.deps import AdminDep, AupDep, SessionDep
from app.db.hr_models import (
    PRIORITIES,
    QUESTION_KINDS,
    ROLES,
    TEMPLATE_KINDS,
    ChecklistItem,
    ChecklistTemplate,
    Department,
    Employee,
    FeedbackQuestion,
    Task,
    UsefulLink,
)
from app.db.models import User
from app.schemas.hr_achievements import AchievementsOut
from app.schemas.hr_achievements import to_out as _achievements_out
from app.services import (
    hr_achievements,
    hr_checklists,
    hr_demo,
    hr_departments,
    hr_feedback,
    hr_links,
    hr_notify,
    hr_settings,
    hr_tasks,
)

router = APIRouter(tags=["hr-admin"])


# --------------------------------------------------------------------------
# Схемы
# --------------------------------------------------------------------------


class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    emoji: str | None = Field(None, max_length=16)
    slug: str | None = Field(None, max_length=64)


class DepartmentPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    emoji: str | None = Field(None, max_length=16)
    is_active: bool | None = None
    sort_order: int | None = None


class DepartmentAdminOut(BaseModel):
    id: int
    name: str
    slug: str
    emoji: str | None
    is_active: bool
    sort_order: int


class TemplateIn(BaseModel):
    department_id: int
    title: str = Field(min_length=1)
    kind: str = "shift"


class TemplatePatch(BaseModel):
    title: str | None = Field(None, min_length=1)
    kind: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class ItemOut(BaseModel):
    id: int
    template_id: int
    title: str
    description: str | None
    requires_photo: bool
    is_mandatory: bool
    condition_position: str | None
    sort_order: int


class TemplateOut(BaseModel):
    id: int
    department_id: int
    title: str
    kind: str
    is_active: bool
    sort_order: int
    items: list[ItemOut]


class ItemIn(BaseModel):
    title: str = Field(min_length=1)
    description: str | None = None
    requires_photo: bool = False
    is_mandatory: bool = True
    condition_position: str | None = None
    sort_order: int | None = None


class ItemPatch(BaseModel):
    title: str | None = Field(None, min_length=1)
    description: str | None = None
    requires_photo: bool | None = None
    is_mandatory: bool | None = None
    condition_position: str | None = None
    sort_order: int | None = None


class LinkIn(BaseModel):
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    emoji: str | None = Field(None, max_length=16)
    department_id: int | None = None


class LinkPatch(BaseModel):
    title: str | None = Field(None, min_length=1)
    url: str | None = Field(None, min_length=1)
    emoji: str | None = Field(None, max_length=16)
    department_id: int | None = None
    clear_department: bool = False
    is_active: bool | None = None
    sort_order: int | None = None


class LinkAdminOut(BaseModel):
    id: int
    title: str
    url: str
    emoji: str | None
    department_id: int | None
    is_active: bool
    sort_order: int


class QuestionIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1)
    kind: str = "scale"
    options: list[str] = []
    sort_order: int | None = None


class QuestionPatch(BaseModel):
    text: str | None = Field(None, min_length=1)
    kind: str | None = None
    options: list[str] | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class QuestionOut(BaseModel):
    id: int
    code: str
    text: str
    kind: str
    options: list[str]
    is_active: bool
    sort_order: int


def _question_out(q: FeedbackQuestion) -> QuestionOut:
    return QuestionOut(
        id=q.id,
        code=q.code,
        text=q.text,
        kind=q.kind,
        options=list(q.options or []),
        is_active=q.is_active,
        sort_order=q.sort_order,
    )


class TaskIn(BaseModel):
    title: str = Field(min_length=1)
    scope: str = "employee"
    description: str | None = None
    expected_result: str | None = None
    department_id: int | None = None
    assignee_employee_id: int | None = None
    due_at: datetime | None = None
    priority: str = "normal"
    requires_photo: bool = False
    comment: str | None = None


class TaskStatusIn(BaseModel):
    status: str
    comment: str | None = None


class EmployeeAdminOut(BaseModel):
    id: int
    user_id: int
    display_name: str
    telegram_id: int
    department_id: int | None
    position: str | None
    badge: str | None = None
    badge_emoji: str | None = None
    role: str
    experience: str | None
    onboarding_state: str
    is_active: bool
    is_demo: bool = False


class EmployeePatch(BaseModel):
    role: str | None = None
    department_id: int | None = None
    position: str | None = None
    # Плашка должность/звание: `badge` — текст, `badge_emoji` — значок.
    # `clear_badge` снимает плашку целиком (пустая строка в `badge` иначе
    # неотличима от «не трогать»).
    badge: str | None = Field(None, max_length=64)
    badge_emoji: str | None = Field(None, max_length=8)
    clear_badge: bool = False
    clear_department: bool = False
    is_active: bool | None = None


class TaskAdminOut(BaseModel):
    id: int
    title: str
    scope: str
    department_id: int | None
    assignee_employee_id: int | None
    due_at: datetime | None
    priority: str
    requires_photo: bool
    status: str
    created_by_employee_id: int | None
    created_at: datetime
    done_at: datetime | None
    is_overdue: bool
    assignee_ids: list[int]


class ReportOut(BaseModel):
    open_tasks: int
    overdue_tasks: int
    done_tasks: int
    checklist_runs_done_today: int
    checklist_runs_total_today: int
    selected_date: date


# --------------------------------------------------------------------------
# Подразделения (админ)
# --------------------------------------------------------------------------


def _dept_out(d: Department) -> DepartmentAdminOut:
    return DepartmentAdminOut(
        id=d.id,
        name=d.name,
        slug=d.slug,
        emoji=d.emoji,
        is_active=d.is_active,
        sort_order=d.sort_order,
    )


@router.get("/departments", response_model=list[DepartmentAdminOut])
async def admin_departments(
    session: SessionDep, _: AdminDep
) -> list[DepartmentAdminOut]:
    rows = await hr_departments.list_departments(session, active_only=False)
    return [_dept_out(d) for d in rows]


@router.post("/departments", response_model=DepartmentAdminOut)
async def create_department(
    body: DepartmentIn, session: SessionDep, _: AdminDep
) -> DepartmentAdminOut:
    try:
        dept = await hr_departments.create_department(
            session, name=body.name, emoji=body.emoji, slug=body.slug
        )
    except hr_departments.DepartmentError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(dept)
    return _dept_out(dept)


@router.patch("/departments/{department_id}", response_model=DepartmentAdminOut)
async def patch_department(
    department_id: int, body: DepartmentPatch, session: SessionDep, _: AdminDep
) -> DepartmentAdminOut:
    dept = await hr_departments.get_department(session, department_id)
    if dept is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="department_not_found")
    try:
        await hr_departments.update_department(
            session,
            dept,
            name=body.name,
            emoji=body.emoji,
            is_active=body.is_active,
            sort_order=body.sort_order,
        )
    except hr_departments.DepartmentError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(dept)
    return _dept_out(dept)


# --------------------------------------------------------------------------
# Чек-листы (админ)
# --------------------------------------------------------------------------


def _item_out(item: ChecklistItem) -> ItemOut:
    return ItemOut(
        id=item.id,
        template_id=item.template_id,
        title=item.title,
        description=item.description,
        requires_photo=bool(item.requires_photo),
        is_mandatory=bool(item.is_mandatory),
        condition_position=item.condition_position,
        sort_order=item.sort_order,
    )


async def _template_out(
    session, template: ChecklistTemplate
) -> TemplateOut:  # noqa: ANN001
    items = await hr_checklists.items_of(session, template.id)
    return TemplateOut(
        id=template.id,
        department_id=template.department_id,
        title=template.title,
        kind=template.kind,
        is_active=template.is_active,
        sort_order=template.sort_order,
        items=[_item_out(i) for i in items],
    )


@router.get("/checklists", response_model=list[TemplateOut])
async def admin_checklists(
    session: SessionDep,
    _: AdminDep,
    department_id: int | None = None,
) -> list[TemplateOut]:
    rows = await hr_checklists.list_templates(
        session, department_id=department_id, active_only=False
    )
    return [await _template_out(session, t) for t in rows]


@router.post("/checklists", response_model=TemplateOut)
async def create_template(
    body: TemplateIn, session: SessionDep, _: AdminDep
) -> TemplateOut:
    if body.kind not in TEMPLATE_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_kind")
    dept = await hr_departments.get_department(session, body.department_id)
    if dept is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="department_not_found")
    template = ChecklistTemplate(
        department_id=body.department_id,
        title=body.title.strip(),
        kind=body.kind,
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return await _template_out(session, template)


@router.patch("/checklists/{template_id}", response_model=TemplateOut)
async def patch_template(
    template_id: int, body: TemplatePatch, session: SessionDep, _: AdminDep
) -> TemplateOut:
    template = await hr_checklists.get_template(session, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="template_not_found")
    if body.kind is not None:
        if body.kind not in TEMPLATE_KINDS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_kind")
        template.kind = body.kind
    if body.title is not None:
        template.title = body.title.strip()
    if body.is_active is not None:
        template.is_active = body.is_active
    if body.sort_order is not None:
        template.sort_order = body.sort_order
    await session.commit()
    await session.refresh(template)
    return await _template_out(session, template)


@router.post("/checklists/{template_id}/items", response_model=ItemOut)
async def create_item(
    template_id: int, body: ItemIn, session: SessionDep, _: AdminDep
) -> ItemOut:
    template = await hr_checklists.get_template(session, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="template_not_found")
    if body.sort_order is None:
        body.sort_order = len(await hr_checklists.items_of(session, template_id))
    item = ChecklistItem(
        template_id=template_id,
        title=body.title.strip(),
        description=body.description,
        requires_photo=body.requires_photo,
        is_mandatory=body.is_mandatory,
        condition_position=body.condition_position,
        sort_order=body.sort_order,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return _item_out(item)


@router.patch("/checklist-items/{item_id}", response_model=ItemOut)
async def patch_item(
    item_id: int, body: ItemPatch, session: SessionDep, _: AdminDep
) -> ItemOut:
    item = await session.get(ChecklistItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="item_not_found")
    if body.title is not None:
        item.title = body.title.strip()
    if body.description is not None:
        item.description = body.description
    if body.requires_photo is not None:
        item.requires_photo = body.requires_photo
    if body.is_mandatory is not None:
        item.is_mandatory = body.is_mandatory
    if body.condition_position is not None:
        item.condition_position = body.condition_position or None
    if body.sort_order is not None:
        item.sort_order = body.sort_order
    await session.commit()
    await session.refresh(item)
    return _item_out(item)


# `response_model=None` обязателен: у 204 не может быть тела, а FastAPI иначе
# выводит модель ответа из аннотации `-> None` (получается `NoneType`) и падает
# на собственной проверке «status 204 must not have a response body».
@router.delete(
    "/checklist-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_item(item_id: int, session: SessionDep, _: AdminDep) -> None:
    item = await session.get(ChecklistItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="item_not_found")
    await session.delete(item)
    await session.commit()


# --------------------------------------------------------------------------
# Ссылки (админ)
# --------------------------------------------------------------------------


def _link_admin_out(link: UsefulLink) -> LinkAdminOut:
    return LinkAdminOut(
        id=link.id,
        title=link.title,
        url=link.url,
        emoji=link.emoji,
        department_id=link.department_id,
        is_active=link.is_active,
        sort_order=link.sort_order,
    )


@router.get("/links", response_model=list[LinkAdminOut])
async def admin_links(session: SessionDep, _: AdminDep) -> list[LinkAdminOut]:
    rows = await hr_links.list_links(session, include_inactive=True)
    return [_link_admin_out(link) for link in rows]


@router.post("/links", response_model=LinkAdminOut)
async def create_link(
    body: LinkIn, session: SessionDep, _: AdminDep
) -> LinkAdminOut:
    try:
        link = await hr_links.create_link(
            session,
            title=body.title,
            url=body.url,
            emoji=body.emoji,
            department_id=body.department_id,
        )
    except hr_links.LinkError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(link)
    return _link_admin_out(link)


@router.patch("/links/{link_id}", response_model=LinkAdminOut)
async def patch_link(
    link_id: int, body: LinkPatch, session: SessionDep, _: AdminDep
) -> LinkAdminOut:
    link = await hr_links.get_link(session, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="link_not_found")
    try:
        await hr_links.update_link(
            session,
            link,
            title=body.title,
            url=body.url,
            emoji=body.emoji,
            department_id=body.department_id,
            clear_department=body.clear_department,
            is_active=body.is_active,
            sort_order=body.sort_order,
        )
    except hr_links.LinkError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(link)
    return _link_admin_out(link)


# --------------------------------------------------------------------------
# Вопросы обратной связи (админ)
# --------------------------------------------------------------------------


@router.get("/feedback/questions", response_model=list[QuestionOut])
async def admin_questions(session: SessionDep, _: AdminDep) -> list[QuestionOut]:
    rows = await hr_feedback.list_questions(session, active_only=False)
    return [_question_out(q) for q in rows]


@router.post("/feedback/questions", response_model=QuestionOut)
async def create_question(
    body: QuestionIn, session: SessionDep, _: AdminDep
) -> QuestionOut:
    if body.kind not in QUESTION_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_kind")
    if body.kind == "choice" and not body.options:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="options_required")
    sort_order = body.sort_order
    if sort_order is None:
        sort_order = len(await hr_feedback.list_questions(session, active_only=False))
    question = FeedbackQuestion(
        code=body.code.strip(),
        text=body.text.strip(),
        kind=body.kind,
        options=list(body.options),
        sort_order=sort_order,
    )
    session.add(question)
    await session.commit()
    await session.refresh(question)
    return _question_out(question)


@router.patch("/feedback/questions/{question_id}", response_model=QuestionOut)
async def patch_question(
    question_id: int, body: QuestionPatch, session: SessionDep, _: AdminDep
) -> QuestionOut:
    question = await hr_feedback.get_question(session, question_id)
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="question_not_found")
    if body.kind is not None:
        if body.kind not in QUESTION_KINDS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_kind")
        question.kind = body.kind
    if body.text is not None:
        question.text = body.text.strip()
    if body.options is not None:
        question.options = list(body.options)
    if body.is_active is not None:
        question.is_active = body.is_active
    if body.sort_order is not None:
        question.sort_order = body.sort_order
    await session.commit()
    await session.refresh(question)
    return _question_out(question)


# --------------------------------------------------------------------------
# Поручения (АУП) и сотрудники
# --------------------------------------------------------------------------


async def _task_admin_out(session, task: Task) -> TaskAdminOut:  # noqa: ANN001
    assignees = await hr_tasks.assignees(session, task)
    return TaskAdminOut(
        id=task.id,
        title=task.title,
        scope=task.scope,
        department_id=task.department_id,
        assignee_employee_id=task.assignee_employee_id,
        due_at=task.due_at,
        priority=task.priority,
        requires_photo=bool(task.requires_photo),
        status=task.status,
        created_by_employee_id=task.created_by_employee_id,
        created_at=task.created_at,
        done_at=task.done_at,
        is_overdue=hr_tasks.is_overdue(task),
        assignee_ids=[e.id for e in assignees],
    )


@router.get("/tasks", response_model=list[TaskAdminOut])
async def admin_tasks(
    session: SessionDep, _: AupDep, status_filter: str | None = None
) -> list[TaskAdminOut]:
    statuses = [status_filter] if status_filter else None
    # Тестовый пул `[BOT]` прячется тем же тумблером, что и лента: иначе его
    # поручения остались бы в боевом списке руководителя.
    hidden = await hr_demo.hidden_employee_ids(session)
    rows = await hr_tasks.list_all(
        session, statuses=statuses, exclude_employee_ids=hidden
    )
    return [await _task_admin_out(session, t) for t in rows]


@router.post("/tasks", response_model=TaskAdminOut)
async def create_task(
    body: TaskIn, session: SessionDep, employee: AupDep
) -> TaskAdminOut:
    if body.priority not in PRIORITIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_priority")
    try:
        task = await hr_tasks.create_task(
            session,
            creator=employee,
            title=body.title,
            scope=body.scope,
            description=body.description,
            expected_result=body.expected_result,
            department_id=body.department_id,
            assignee_employee_id=body.assignee_employee_id,
            due_at=body.due_at,
            priority=body.priority,
            requires_photo=body.requires_photo,
            comment=body.comment,
        )
    except hr_tasks.TaskError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    recipients = await hr_tasks.assignees(session, task)
    await hr_notify.notify_task_assigned(session, task, recipients)
    await session.commit()
    await session.refresh(task)
    return await _task_admin_out(session, task)


@router.patch("/tasks/{task_id}/status", response_model=TaskAdminOut)
async def set_task_status(
    task_id: int, body: TaskStatusIn, session: SessionDep, employee: AupDep
) -> TaskAdminOut:
    task = await hr_tasks.get_task(session, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="task_not_found")
    try:
        await hr_tasks.change_status(
            session, task, body.status, by=employee, comment=body.comment
        )
    except hr_tasks.TaskError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(task)
    return await _task_admin_out(session, task)


def _employee_admin_out(employee: Employee, user: User) -> EmployeeAdminOut:
    return EmployeeAdminOut(
        id=employee.id,
        user_id=employee.user_id,
        display_name=user.display_name,
        telegram_id=user.telegram_id,
        department_id=employee.department_id,
        position=employee.position,
        badge=employee.badge,
        badge_emoji=employee.badge_emoji,
        role=employee.role,
        experience=employee.experience,
        onboarding_state=employee.onboarding_state,
        is_active=employee.is_active,
        is_demo=employee.is_demo,
    )


@router.get("/employees", response_model=list[EmployeeAdminOut])
async def admin_employees(
    session: SessionDep, _: AupDep, include_demo: bool = False
) -> list[EmployeeAdminOut]:
    """Список сотрудников — для выбора адресата персонального поручения.

    `include_demo=false` (по умолчанию) прячет тестовый пул `[BOT]`: адресатом
    боевого поручения тестовый человек быть не должен. Если пул выключен
    тумблером (`hr.demo.visible`), он скрыт даже при `include_demo=true`.
    """
    hidden = await hr_demo.hidden_employee_ids(session)
    rows = await session.execute(
        select(Employee, User).join(User, User.id == Employee.user_id).order_by(Employee.id)
    )
    out: list[EmployeeAdminOut] = []
    for employee, user in rows.all():
        if int(employee.id) in hidden:
            continue
        if employee.is_demo and not include_demo:
            continue
        out.append(_employee_admin_out(employee, user))
    return out


@router.patch("/employees/{employee_id}", response_model=EmployeeAdminOut)
async def patch_employee(
    employee_id: int, body: EmployeePatch, session: SessionDep, _: AdminDep
) -> EmployeeAdminOut:
    employee = await session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="employee_not_found")
    user = await session.get(User, employee.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user_not_found")

    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_role")
        employee.role = body.role
    if body.clear_department:
        employee.department_id = None
    elif body.department_id is not None:
        if await hr_departments.get_department(session, body.department_id) is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="department_not_found"
            )
        employee.department_id = body.department_id
    if body.position is not None:
        employee.position = body.position or None
    if body.clear_badge:
        employee.badge = None
        employee.badge_emoji = None
    else:
        if body.badge is not None:
            employee.badge = body.badge or None
        if body.badge_emoji is not None:
            employee.badge_emoji = body.badge_emoji or None
    if body.is_active is not None:
        employee.is_active = body.is_active
    await session.commit()
    await session.refresh(employee)
    return _employee_admin_out(employee, user)


@router.get(
    "/employees/{employee_id}/achievements", response_model=AchievementsOut
)
async def employee_achievements(
    employee_id: int, session: SessionDep, _: AupDep
) -> AchievementsOut:
    """Скрытые ачивки конкретного сотрудника — для руководителя.

    Отдельная ручка, а не дополнительное поле в карточке сотрудника: скрытый
    блок должен запрашиваться осознанно, а не приезжать вместе со списком людей.
    Сам пересчёт идемпотентен (`services/hr_achievements`), поэтому ручку можно
    звать сколько угодно — дублей не появится.
    """
    employee = await session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="employee_not_found")
    view = await hr_achievements.view_for_manager(session, employee.id)
    return _achievements_out(view)


# --------------------------------------------------------------------------
# Сводный отчёт (АУП)
# --------------------------------------------------------------------------


@router.get("/reports/overview", response_model=ReportOut)
async def reports_overview(
    session: SessionDep, _: AupDep, on: date | None = None
) -> ReportOut:
    """Короткая сводка для руководителя: поручения и чек-листы за дату."""
    from sqlalchemy import func

    from app.db.hr_models import (
        RUN_DONE,
        TASK_DONE,
        TASK_OVERDUE,
        ChecklistRun,
    )

    selected = on or hr_checklists.local_today()

    # Скрытые сотрудники (тумблер тестового пула `[BOT]`) не попадают в сводку:
    # иначе «отчёт за смену» показывал бы работу симуляторов как боевую.
    hidden = await hr_demo.hidden_employee_ids(session)

    def _visible(stmt: Select[Any]) -> Select[Any]:
        if hidden:
            stmt = stmt.where(ChecklistRun.employee_id.notin_(hidden))
        return stmt

    def _visible_tasks(stmt: Select[Any]) -> Select[Any]:
        if hidden:
            stmt = stmt.where(
                or_(
                    Task.assignee_employee_id.is_(None),
                    Task.assignee_employee_id.notin_(hidden),
                )
            )
        return stmt

    async def _count_tasks(status_value: str) -> int:
        return int(
            await session.scalar(
                _visible_tasks(
                    select(func.count())
                    .select_from(Task)
                    .where(Task.status == status_value)
                )
            )
            or 0
        )

    open_total = int(
        await session.scalar(
            _visible_tasks(
                select(func.count())
                .select_from(Task)
                .where(Task.status.notin_((TASK_DONE, TASK_OVERDUE)))
            )
        )
        or 0
    )
    runs_total = int(
        await session.scalar(
            _visible(
                select(func.count())
                .select_from(ChecklistRun)
                .where(ChecklistRun.shift_date == selected)
            )
        )
        or 0
    )
    runs_done = int(
        await session.scalar(
            _visible(
                select(func.count())
                .select_from(ChecklistRun)
                .where(
                    ChecklistRun.shift_date == selected,
                    ChecklistRun.status == RUN_DONE,
                )
            )
        )
        or 0
    )
    return ReportOut(
        open_tasks=open_total,
        overdue_tasks=await _count_tasks(TASK_OVERDUE),
        done_tasks=await _count_tasks(TASK_DONE),
        checklist_runs_done_today=runs_done,
        checklist_runs_total_today=runs_total,
        selected_date=selected,
    )


# --------------------------------------------------------------------------
# Правила напоминаний и эскалации (админ)
# --------------------------------------------------------------------------


class HrSettingsOut(BaseModel):
    reminders_enabled: bool
    remind_before_minutes: int
    escalation_enabled: bool
    tick_minutes: int
    # Один тумблер тестового пула `[BOT]`: показывать его следы или нет.
    demo_visible: bool


class HrSettingsPatch(BaseModel):
    reminders_enabled: bool | None = None
    remind_before_minutes: int | None = Field(None, ge=5, le=24 * 60)
    escalation_enabled: bool | None = None
    tick_minutes: int | None = Field(None, ge=5, le=24 * 60)
    demo_visible: bool | None = None


@router.get("/settings/hr", response_model=HrSettingsOut)
async def get_hr_settings(session: SessionDep, _: AdminDep) -> HrSettingsOut:
    """Как сейчас настроены напоминания о сроке и эскалация просрочки."""
    return HrSettingsOut(**await hr_settings.snapshot(session))


@router.put("/settings/hr", response_model=HrSettingsOut)
async def put_hr_settings(
    body: HrSettingsPatch, session: SessionDep, _: AdminDep
) -> HrSettingsOut:
    """Частичная правка правил: менять можно только присланные поля.

    Значения читает планировщик на каждом тике, поэтому правка действует без
    передеплоя. Границы (5 минут … сутки) зажаты и в схеме, и в сервисе.
    """
    updated = await hr_settings.update(
        session,
        reminders_enabled=body.reminders_enabled,
        remind_before_minutes=body.remind_before_minutes,
        escalation_enabled=body.escalation_enabled,
        tick_minutes=body.tick_minutes,
        demo_visible=body.demo_visible,
    )
    return HrSettingsOut(**updated)


# --------------------------------------------------------------------------
# Тестовый пул `[BOT]` (админ)
# --------------------------------------------------------------------------


class DemoEmployeeOut(BaseModel):
    employee_id: int
    telegram_id: int
    display_name: str
    badge: str | None
    badge_emoji: str | None
    department_id: int | None
    department_name: str | None
    is_active: bool


class DemoActivityOut(BaseModel):
    checklist_runs: int
    tasks: int
    feedback_answers: int


class DemoStateOut(BaseModel):
    visible: bool
    prefix: str
    employees: list[DemoEmployeeOut]
    activity: DemoActivityOut


class DemoVisibilityIn(BaseModel):
    visible: bool


class DemoPurgeIn(BaseModel):
    # `false` — снести только активность (люди остаются в пуле),
    # `true` — удалить и самих сотрудников вместе с их `users`.
    delete_employees: bool = False


class DemoSimulateIn(BaseModel):
    days: int = Field(3, ge=1, le=14)


def _demo_state(data: hr_demo.DemoOverview) -> DemoStateOut:
    """Разложить состояние пула в схему ответа — поля перечислены явно.

    `model_validate` тут не подходит: сервис отдаёт dataclass, и явный маппинг
    оставляет видимым, что именно уезжает клиенту.
    """
    return DemoStateOut(
        visible=data.visible,
        prefix=data.prefix,
        employees=[
            DemoEmployeeOut(
                employee_id=row.employee_id,
                telegram_id=row.telegram_id,
                display_name=row.display_name,
                badge=row.badge,
                badge_emoji=row.badge_emoji,
                department_id=row.department_id,
                department_name=row.department_name,
                is_active=row.is_active,
            )
            for row in data.employees
        ],
        activity=DemoActivityOut(
            checklist_runs=data.activity.checklist_runs,
            tasks=data.activity.tasks,
            feedback_answers=data.activity.feedback_answers,
        ),
    )


@router.get("/demo", response_model=DemoStateOut)
async def demo_state(session: SessionDep, _: AdminDep) -> DemoStateOut:
    """Что сейчас в тестовом пуле и видно ли его следы."""
    return _demo_state(await hr_demo.overview(session))


@router.put("/demo", response_model=DemoStateOut)
async def demo_set_visibility(
    body: DemoVisibilityIn, session: SessionDep, _: AdminDep
) -> DemoStateOut:
    """Один тумблер: показывать следы пула или прятать их."""
    await hr_settings.set_demo_visible(session, body.visible)
    return _demo_state(await hr_demo.overview(session))


@router.post("/demo/seed", response_model=DemoStateOut)
async def demo_seed(session: SessionDep, _: AdminDep) -> DemoStateOut:
    """Завести тестовый пул (идемпотентно)."""
    await hr_demo.seed_pool(session)
    await session.commit()
    return _demo_state(await hr_demo.overview(session))


@router.post("/demo/simulate")
async def demo_simulate(
    body: DemoSimulateIn, session: SessionDep, _: AdminDep
) -> dict[str, int]:
    """Симулировать деятельность пула за последние `days` смен."""
    return await hr_demo.simulate(session, days=body.days)


@router.post("/demo/purge")
async def demo_purge(
    body: DemoPurgeIn, session: SessionDep, _: AdminDep
) -> dict[str, int]:
    """Удалить следы пула. С `delete_employees` — вместе с людьми и их `users`."""
    return await hr_demo.purge(session, delete_employees=body.delete_employees)
