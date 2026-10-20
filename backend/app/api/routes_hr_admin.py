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
    MODE_ONE_OF,
    PRIORITIES,
    QUESTION_KINDS,
    ROLES,
    TASK_DONE,
    TASK_MODES,
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
from app.schemas.hr_kpi import (
    KpiAdminOut,
    RulesOut,
    RulesPatch,
    to_leaderboard,
    to_winner_out,
)
from app.services import (
    hr_access,
    hr_achievements,
    hr_checklists,
    hr_demo,
    hr_departments,
    hr_feedback,
    hr_kpi,
    hr_links,
    hr_notify,
    hr_ops,
    hr_settings,
    hr_simulation,
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
    # Групповое поручение: режим («один за всех / каждый сам / части работы»)
    # и смена, на которую оно выдано.
    mode: str = MODE_ONE_OF
    shift_date: date | None = None
    # Текст части каждому исполнителю — только для режима `parts`.
    parts: dict[int, str] | None = None
    # Проверка руководителем: сотрудник сдаёт работу, руководитель принимает
    # или возвращает на доработку (MEGAPROMT2).
    requires_review: bool = False


class TaskStatusIn(BaseModel):
    status: str
    comment: str | None = None


class EmployeeAdminOut(BaseModel):
    id: int
    user_id: int
    display_name: str
    telegram_id: int
    department_id: int | None
    # Подразделение рядом с именем: в списках из 60 человек без тега не видно,
    # кто из какого отдела. Пусто, если отдел еще не выбран.
    department_name: str | None = None
    department_emoji: str | None = None
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


class TaskAssignmentOut(BaseModel):
    employee_id: int
    display_name: str
    status: str
    part: str | None
    done_at: datetime | None


class TaskAdminPhotoOut(BaseModel):
    """Фотоотчёт в карточке приёмки: ссылка уже готова для `<img>`."""

    id: int
    url: str
    width: int | None = None
    height: int | None = None


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
    mode: str = MODE_ONE_OF
    shift_date: date | None = None
    requires_review: bool = False
    progress_done: int = 0
    progress_total: int = 0
    assignments: list[TaskAssignmentOut] = []
    # Снимки, которые сотрудник приложил в приложении или прислал в чат.
    photos: list[TaskAdminPhotoOut] = []


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


async def _employee_names(session, ids: set[int]) -> dict[int, str]:  # noqa: ANN001
    """Имена исполнителей: в админских списках нужен человек, а не id."""
    if not ids:
        return {}
    rows = await session.execute(
        select(Employee.id, User.display_name)
        .join(User, User.id == Employee.user_id)
        .where(Employee.id.in_(ids))
    )
    return {int(employee_id): str(name) for employee_id, name in rows.all()}


async def _task_photo_outs(session, task_id: int) -> list[TaskAdminPhotoOut]:  # noqa: ANN001
    """Фото поручения: блоб из приложения или подписанная ссылка на кеш TG."""
    from app.db.hr_models import MediaBlob, TaskPhoto
    from app.services import hr_media

    rows = (
        await session.scalars(
            select(TaskPhoto)
            .where(TaskPhoto.task_id == task_id)
            .order_by(TaskPhoto.created_at, TaskPhoto.id)
        )
    ).all()
    if not rows:
        return []
    media_ids = [p.media_id for p in rows if p.media_id is not None]
    blobs: dict[int, MediaBlob] = {}
    if media_ids:
        for blob in (
            await session.scalars(select(MediaBlob).where(MediaBlob.id.in_(media_ids)))
        ).all():
            blobs[int(blob.id)] = blob
    out: list[TaskAdminPhotoOut] = []
    for photo in rows:
        blob = blobs.get(int(photo.media_id)) if photo.media_id is not None else None
        if blob is not None:
            out.append(
                TaskAdminPhotoOut(
                    id=int(photo.id),
                    url=hr_media.url_for(int(blob.id)),
                    width=blob.width,
                    height=blob.height,
                )
            )
        else:
            out.append(
                TaskAdminPhotoOut(id=int(photo.id), url=hr_media.photo_url(int(photo.id)))
            )
    return out


async def _task_admin_out(session, task: Task) -> TaskAdminOut:  # noqa: ANN001
    assignees = await hr_tasks.assignees(session, task)
    rows = await hr_tasks.assignments_of(session, task.id)
    names = await _employee_names(session, {row.employee_id for row in rows})
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
        mode=task.mode,
        shift_date=task.shift_date,
        requires_review=bool(task.requires_review),
        progress_done=sum(1 for row in rows if row.status == TASK_DONE),
        progress_total=len(rows),
        photos=await _task_photo_outs(session, int(task.id)),
        assignments=[
            TaskAssignmentOut(
                employee_id=row.employee_id,
                display_name=names.get(row.employee_id, "—"),
                status=row.status,
                part=row.part,
                done_at=row.done_at,
            )
            for row in rows
        ],
    )


@router.get("/tasks", response_model=list[TaskAdminOut])
async def admin_tasks(
    session: SessionDep,
    _: AupDep,
    status_filter: str | None = None,
    shift_date: date | None = None,
) -> list[TaskAdminOut]:
    statuses = [status_filter] if status_filter else None
    # Тестовый пул `[BOT]` прячется тем же тумблером, что и лента: иначе его
    # поручения остались бы в боевом списке руководителя.
    hidden = await hr_demo.hidden_employee_ids(session)
    rows = await hr_tasks.list_all(
        session, statuses=statuses, exclude_employee_ids=hidden
    )
    if shift_date is not None:
        rows = [task for task in rows if task.shift_date == shift_date]
    return [await _task_admin_out(session, t) for t in rows]


@router.post("/tasks", response_model=TaskAdminOut)
async def create_task(
    body: TaskIn, session: SessionDep, employee: AupDep
) -> TaskAdminOut:
    if body.priority not in PRIORITIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_priority")
    if body.mode not in TASK_MODES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_mode")
    # Режим проверки — песочница. Поручение другому человеку или отделу было бы
    # реальным внешним действием, поэтому разрешаем только «себе».
    if hr_simulation.current() is not None and (
        body.scope != "employee"
        or body.assignee_employee_id != int(employee.id)
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="simulation_self_only"
        )
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
            mode=body.mode,
            shift_date=body.shift_date,
            parts=body.parts,
            requires_review=body.requires_review,
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
    # В сеансе проверки меняем статус только у своих тестовых задач.
    if hr_simulation.current() is not None and not (
        task.assignee_employee_id == employee.id
        or task.created_by_employee_id == employee.id
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="simulation_self_only"
        )
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


def _employee_admin_out(
    employee: Employee, user: User, department: Department | None = None
) -> EmployeeAdminOut:
    return EmployeeAdminOut(
        id=employee.id,
        user_id=employee.user_id,
        display_name=user.display_name,
        telegram_id=user.telegram_id,
        department_id=employee.department_id,
        department_name=department.name if department else None,
        department_emoji=department.emoji if department else None,
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
        select(Employee, User, Department)
        .join(User, User.id == Employee.user_id)
        .outerjoin(Department, Department.id == Employee.department_id)
        .order_by(Employee.id)
    )
    out: list[EmployeeAdminOut] = []
    for employee, user, department in rows.all():
        # Теневые профили режима проверки не выбираются как адресаты.
        if employee.is_simulation or int(employee.id) in hidden:
            continue
        if employee.is_demo and not include_demo:
            continue
        out.append(_employee_admin_out(employee, user, department))
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
        # `set_role` ставит `role_locked`: иначе env-админу роль вернут
        # автоматически на следующем запросе (`ensure_employee`).
        hr_access.set_role(employee, body.role)
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
    department = (
        await session.get(Department, employee.department_id)
        if employee.department_id
        else None
    )
    return _employee_admin_out(employee, user, department)


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
    # Вторая ступень: молчание руководителя дольше N часов → пинг админам.
    escalation_second_enabled: bool = True
    escalation_second_hours: int = 4
    # Повтор в каждой смене, пока задача висит (строгий режим).
    escalation_second_repeat: bool = False
    tick_minutes: int
    # Один тумблер тестового пула `[BOT]`: показывать его следы или нет.
    demo_visible: bool
    # Рабочие часы ресторана: на них равняются все смены и уведомления.
    work_open: str = "10:00"
    work_close: str = "23:00"
    notify_only_work_hours: bool = True
    notify_lead_minutes: int = 60
    notify_tail_minutes: int = 60
    muted_until: str | None = None
    notifications_allowed: bool = True


class HrSettingsPatch(BaseModel):
    reminders_enabled: bool | None = None
    remind_before_minutes: int | None = Field(None, ge=5, le=24 * 60)
    escalation_enabled: bool | None = None
    escalation_second_enabled: bool | None = None
    escalation_second_hours: int | None = Field(None, ge=1, le=72)
    escalation_second_repeat: bool | None = None
    tick_minutes: int | None = Field(None, ge=5, le=24 * 60)
    demo_visible: bool | None = None
    work_open: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    work_close: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    notify_only_work_hours: bool | None = None
    notify_lead_minutes: int | None = Field(None, ge=0, le=12 * 60)
    notify_tail_minutes: int | None = Field(None, ge=0, le=12 * 60)


class RoleSwitchIn(BaseModel):
    """Смена собственной роли: управляющий смотрит приложение глазами роли."""

    role: str


class MuteIn(BaseModel):
    """Мьют уведомлений: часы вперёд. `0` — снять мьют."""

    hours: int


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
        escalation_second_enabled=body.escalation_second_enabled,
        escalation_second_hours=body.escalation_second_hours,
        escalation_second_repeat=body.escalation_second_repeat,
        tick_minutes=body.tick_minutes,
        demo_visible=body.demo_visible,
        work_open=body.work_open,
        work_close=body.work_close,
        notify_only_work_hours=body.notify_only_work_hours,
        notify_lead_minutes=body.notify_lead_minutes,
        notify_tail_minutes=body.notify_tail_minutes,
    )
    return HrSettingsOut(**updated)


# --------------------------------------------------------------------------
# Кабинет управляющего: сводка по смене, роли и мьют уведомлений
# --------------------------------------------------------------------------


@router.get("/dashboard", response_model=hr_ops.Dashboard)
async def manager_dashboard(
    session: SessionDep, employee: AupDep
) -> hr_ops.Dashboard:
    """Оперативная сводка: отделы, люди, просрочки и проблемы.

    Руководитель видит своё подразделение, администратор — всё. Никаких
    «передай id отдела»: область видимости выводится из роли на сервере.
    """
    return await hr_ops.build_dashboard(session, viewer=employee)


@router.post("/me/role", response_model=EmployeeAdminOut)
async def switch_my_role(
    body: RoleSwitchIn, session: SessionDep, employee: AdminDep
) -> EmployeeAdminOut:
    """Сменить собственную роль, чтобы посмотреть приложение с другой стороны.

    Доступна только тем, у кого есть прописанный доступ в админку: сняв себе
    `admin`, человек не теряет кабинет и может вернуть роль обратно. Само
    понижение не выкидывает из аккаунта и не трогает историю.
    """
    if body.role not in ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_role")
    try:
        hr_access.set_role(employee, body.role)
    except hr_access.HrAccessError as exc:  # pragma: no cover - защита на будущее
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(employee)
    user = await session.get(User, employee.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user_not_found")
    department = (
        await session.get(Department, employee.department_id)
        if employee.department_id
        else None
    )
    return _employee_admin_out(employee, user, department)


@router.post("/notifications/mute", response_model=HrSettingsOut)
async def mute_notifications(
    body: MuteIn, session: SessionDep, _: AupDep
) -> HrSettingsOut:
    """Заглушить алерты на 24ч / 3 суток / неделю / месяц (или снять мьют).

    Глушит только доставку в Telegram; уведомления в приложении продолжают
    копиться, чтобы утренний разбор не потерялся.
    """
    if body.hours <= 0:
        await hr_settings.clear_mute(session)
    else:
        await hr_settings.mute_for_hours(session, body.hours)
    return HrSettingsOut(**await hr_settings.snapshot(session))


# --------------------------------------------------------------------------
# KPI смены: правила, недельный рейтинг, сотрудник недели
# --------------------------------------------------------------------------


@router.get("/kpi", response_model=KpiAdminOut)
async def kpi_overview(session: SessionDep, _: AupDep) -> KpiAdminOut:
    """Рейтинг недели и текущие веса опыта.

    Читает руководитель: номинация «сотрудник недели» — его рабочий инструмент,
    а не развлечение. Тестовый пул `[BOT]` из рейтинга исключён, иначе
    симуляторы забирали бы звание у живых людей.
    """
    rules = await hr_kpi.get_rules(session)
    today = hr_checklists.local_today()
    monday, sunday = hr_kpi.week_bounds(today)
    board = [c for c in await hr_kpi.board(session, today, rules) if not c.is_demo]
    return KpiAdminOut(
        week_start=monday.isoformat(),
        week_end=sunday.isoformat(),
        rules=RulesOut(**rules.as_dict()),
        leaderboard=to_leaderboard(board),
        employee_of_week=to_winner_out(hr_kpi.pick_winner(board, rules)),
    )


@router.put("/kpi/rules", response_model=RulesOut)
async def put_kpi_rules(
    body: RulesPatch, session: SessionDep, _: AdminDep
) -> RulesOut:
    """Правка весов опыта без передеплоя.

    Менять может только администратор: это баланс наград, и «подкрутить себе
    опыт» из-под руководителя не должно быть возможно. Границы зажаты и в
    схеме, и в сервисе.
    """
    rules = await hr_kpi.update_rules(
        session,
        xp_checklist_item=body.xp_checklist_item,
        xp_shift_done=body.xp_shift_done,
        xp_task=body.xp_task,
        xp_on_time=body.xp_on_time,
        min_xp_winner=body.min_xp_winner,
    )
    return RulesOut(**rules.as_dict())


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
