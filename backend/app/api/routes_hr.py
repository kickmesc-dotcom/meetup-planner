"""REST API HR-ядра для сотрудника (мини-апп и бот).

Все ручки требуют валидный Telegram `initData` (`CurrentUser`) и работают от
имени HR-профиля (`EmployeeDep`). Никаких «передай свой id» — идентичность и
права берутся из подписанных данных и БД.

Ответы персонализированы, поэтому клиент должен слать их без кеша
(`Cache-Control: private, no-store` ставит фронт; на API это не влияет).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, EmployeeDep, SessionDep
from app.db.hr_models import (
    EXPERIENCES,
    ONBOARDING_DONE,
    ONBOARDING_EXPERIENCE,
    ONBOARDING_TRAINING,
    TASK_DONE,
    TEMPLATE_SHIFT,
    ChecklistItem,
    Department,
    Employee,
    FeedbackQuestion,
    Task,
    TaskAssignment,
    UsefulLink,
)
from app.db.models import User
from app.schemas.hr_achievements import AchievementsOut
from app.schemas.hr_achievements import to_out as _achievements_out
from app.schemas.hr_kpi import MyKpiOut, to_my_out
from app.services import (
    hr_access,
    hr_achievements,
    hr_checklists,
    hr_departments,
    hr_feed,
    hr_feedback,
    hr_kpi,
    hr_links,
    hr_tasks,
    hr_training,
)

router = APIRouter(tags=["hr"])


# --------------------------------------------------------------------------
# Схемы
# --------------------------------------------------------------------------


class EmployeeOut(BaseModel):
    id: int
    user_id: int
    display_name: str
    telegram_id: int
    department_id: int | None
    department_name: str | None
    position: str | None
    # Плашка должность/звание — её показывают бот и мини-апп рядом с именем.
    badge: str | None = None
    badge_emoji: str | None = None
    role: str
    experience: str | None
    onboarding_state: str
    is_aup: bool
    is_admin: bool
    # Прописанный доступ в админку (шестёрка/владельцы). Переживает смену
    # собственной роли: снял admin — кабинет всё равно доступен.
    is_staff: bool = False
    is_active: bool
    # Тестовый пул `[BOT]`: клиент показывает пометку и может спрятать его.
    is_demo: bool = False


class OnboardingIn(BaseModel):
    department_id: int | None = None
    experience: Literal["new", "experienced"] | None = None


class DepartmentOut(BaseModel):
    id: int
    name: str
    slug: str
    emoji: str | None
    sort_order: int


class ChecklistItemOut(BaseModel):
    id: int
    title: str
    description: str | None
    requires_photo: bool
    is_mandatory: bool
    done: bool
    done_at: datetime | None
    photo_file_id: str | None
    note: str | None


class ChecklistOut(BaseModel):
    run_id: int | None
    template_id: int | None
    template_title: str | None
    kind: str
    shift_date: date
    status: str
    done: int
    total: int
    progress_text: str
    items: list[ChecklistItemOut]


class CompleteIn(BaseModel):
    item_id: int
    photo_file_id: str | None = None
    note: str | None = None


class TaskOut(BaseModel):
    id: int
    title: str
    description: str | None
    expected_result: str | None
    scope: str
    department_id: int | None
    assignee_employee_id: int | None
    due_at: datetime | None
    priority: str
    requires_photo: bool
    comment: str | None
    status: str
    created_by_employee_id: int | None
    created_at: datetime
    done_at: datetime | None
    is_overdue: bool
    # Групповые поручения: режим, смена и ЛИЧНЫЙ статус сотрудника. Общий
    # `status` — агрегат по всем исполнителям, поэтому в «каждый сам» он не
    # говорит, закрыл ли конкретный человек свою часть.
    mode: str = "one_of"
    shift_date: date | None = None
    # Поручение с проверкой: отметка «выполнено» отправляет работу
    # руководителю (`on_review`), а не закрывает её.
    requires_review: bool = False
    my_status: str | None = None
    progress_done: int = 0
    progress_total: int = 0
    my_part: str | None = None


class TaskIssueIn(BaseModel):
    reason_code: str | None = Field(None, max_length=32)
    comment: str | None = None
    eta_at: datetime | None = None


class TaskPhotoIn(BaseModel):
    file_id: str = Field(min_length=1)


class LinkOut(BaseModel):
    id: int
    title: str
    url: str
    emoji: str | None
    department_id: int | None


class FeedbackQuestionOut(BaseModel):
    id: int
    code: str
    text: str
    kind: str
    options: list[str]


class FeedbackAnswerIn(BaseModel):
    question_id: int
    value_scale: int | None = None
    value_choice: str | None = None
    value_text: str | None = None


class FeedbackIn(BaseModel):
    shift_date: date | None = None
    answers: list[FeedbackAnswerIn]


# --------------------------------------------------------------------------
# Хелперы сериализации
# --------------------------------------------------------------------------


async def _department_name(
    session: AsyncSession, department_id: int | None
) -> str | None:
    if department_id is None:
        return None
    dept = await session.get(Department, department_id)
    return dept.name if dept else None


async def _employee_out(
    session: AsyncSession, employee: Employee, user: User
) -> EmployeeOut:
    return EmployeeOut(
        id=employee.id,
        user_id=employee.user_id,
        display_name=user.display_name,
        telegram_id=user.telegram_id,
        badge=employee.badge,
        badge_emoji=employee.badge_emoji,
        is_demo=employee.is_demo,
        department_id=employee.department_id,
        department_name=await _department_name(session, employee.department_id),
        position=employee.position,
        role=employee.role,
        experience=employee.experience,
        onboarding_state=employee.onboarding_state,
        is_aup=hr_access.is_aup(employee),
        is_admin=hr_access.is_admin(employee),
        is_staff=hr_access.is_staff(employee, user),
        is_active=employee.is_active,
    )


def _task_out(
    task: Task,
    *,
    my_status: str | None = None,
    my_part: str | None = None,
    progress: tuple[int, int] = (0, 0),
) -> TaskOut:
    return TaskOut(
        id=task.id,
        title=task.title,
        description=task.description,
        expected_result=task.expected_result,
        scope=task.scope,
        department_id=task.department_id,
        assignee_employee_id=task.assignee_employee_id,
        due_at=task.due_at,
        priority=task.priority,
        requires_photo=bool(task.requires_photo),
        comment=task.comment,
        status=task.status,
        created_by_employee_id=task.created_by_employee_id,
        created_at=task.created_at,
        done_at=task.done_at,
        is_overdue=hr_tasks.is_overdue(task),
        mode=task.mode,
        shift_date=task.shift_date,
        requires_review=bool(task.requires_review),
        my_status=my_status,
        my_part=my_part,
        progress_done=progress[0],
        progress_total=progress[1],
    )


async def _task_views(
    session: AsyncSession, rows: list[Task], employee: Employee
) -> list[TaskOut]:
    """Поручения со личным статусом и прогрессом — одним запросом на список."""
    if not rows:
        return []
    assignments = await session.scalars(
        select(TaskAssignment).where(
            TaskAssignment.task_id.in_([task.id for task in rows])
        )
    )
    mine: dict[int, TaskAssignment] = {}
    totals: dict[int, int] = {}
    done: dict[int, int] = {}
    for assignment in assignments.all():
        totals[assignment.task_id] = totals.get(assignment.task_id, 0) + 1
        if assignment.status == TASK_DONE:
            done[assignment.task_id] = done.get(assignment.task_id, 0) + 1
        if assignment.employee_id == employee.id:
            mine[assignment.task_id] = assignment

    out: list[TaskOut] = []
    for task in rows:
        own = mine.get(task.id)
        out.append(
            _task_out(
                task,
                my_status=own.status if own is not None else None,
                my_part=own.part if own is not None else None,
                progress=(done.get(task.id, 0), totals.get(task.id, 0)),
            )
        )
    return out


def _checklist_out(view: hr_checklists.ChecklistView) -> ChecklistOut:
    return ChecklistOut(
        run_id=view.run_id,
        template_id=view.template_id,
        template_title=view.template_title,
        kind=view.kind,
        shift_date=view.shift_date,
        status=view.status,
        done=view.progress.done,
        total=view.progress.total,
        progress_text=view.progress.text(),
        items=[
            ChecklistItemOut(
                id=item.id,
                title=item.title,
                description=item.description,
                requires_photo=item.requires_photo,
                is_mandatory=item.is_mandatory,
                done=item.done,
                done_at=item.done_at,
                photo_file_id=item.photo_file_id,
                note=item.note,
            )
            for item in view.items
        ],
    )


# --------------------------------------------------------------------------
# Профиль и онбординг
# --------------------------------------------------------------------------


@router.get("/me/employee", response_model=EmployeeOut)
async def me_employee(
    session: SessionDep, user: CurrentUser, employee: EmployeeDep
) -> EmployeeOut:
    return await _employee_out(session, employee, user)


@router.post("/me/onboarding", response_model=EmployeeOut)
async def onboarding(
    body: OnboardingIn, session: SessionDep, user: CurrentUser, employee: EmployeeDep
) -> EmployeeOut:
    """Шаги 2–3 первого запуска: подразделение и опыт работы.

    Состояние двигаем вперёд: выбрал подразделение → ждём опыт; выбрал опыт →
    настройка завершена. Оба поля можно прислать одним запросом.
    """
    if body.department_id is None and body.experience is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="nothing_to_update"
        )

    if body.department_id is not None:
        dept = await hr_departments.get_department(session, body.department_id)
        if dept is None or not dept.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="department_unavailable")
        employee.department_id = dept.id
        if employee.onboarding_state in {"new", ONBOARDING_DONE}:
            employee.onboarding_state = ONBOARDING_EXPERIENCE

    if body.experience is not None:
        if body.experience not in EXPERIENCES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_experience")
        employee.experience = body.experience

    # После опыта идёт этап обучения приложению: он закрывается прохождением
    # уроков (`/me/training`), а не этой ручкой. Уже прошедшим обучение
    # (state=done) повторный онбординг его не откатывает.
    if employee.department_id is not None and employee.experience is not None:
        if employee.onboarding_state != ONBOARDING_DONE:
            employee.onboarding_state = ONBOARDING_TRAINING

    await session.commit()
    await session.refresh(employee)
    return await _employee_out(session, employee, user)


# --------------------------------------------------------------------------
# Обучение пользованию приложением (этап онбординга)
# --------------------------------------------------------------------------


class LessonOut(BaseModel):
    code: str
    title: str
    emoji: str
    minutes: int
    summary: str
    steps: list[str]
    done: bool


class TrainingOut(BaseModel):
    """Курс знакомства: уроки, прогресс и что делать дальше."""

    lessons: list[LessonOut]
    done: int
    total: int
    percent: int
    complete: bool
    onboarding_state: str
    next_code: str | None = None


def _training_out(
    progress: hr_training.TrainingProgress, state: str
) -> TrainingOut:
    done = set(progress.done)
    next_lesson = next(
        (code for code in hr_training.MANDATORY_CODES if code not in done), None
    )
    return TrainingOut(
        lessons=[
            LessonOut(
                code=lesson.code,
                title=lesson.title,
                emoji=lesson.emoji,
                minutes=lesson.minutes,
                summary=lesson.summary,
                steps=list(lesson.steps),
                done=lesson.code in done,
            )
            for lesson in hr_training.LESSONS
        ],
        done=len(progress.done),
        total=progress.total,
        percent=progress.percent,
        complete=progress.complete,
        onboarding_state=state,
        next_code=next_lesson,
    )


@router.get("/me/training", response_model=TrainingOut)
async def my_training(session: SessionDep, employee: EmployeeDep) -> TrainingOut:
    progress = await hr_training.progress(session, employee)
    return _training_out(progress, employee.onboarding_state)


@router.post("/me/training/{code}", response_model=TrainingOut)
async def complete_training_lesson(
    code: str, session: SessionDep, employee: EmployeeDep
) -> TrainingOut:
    """Отметить урок пройденным. Последний урок закрывает онбординг.

    Идемпотентно: повторный тап возвращает тот же прогресс, а не 409.
    """
    try:
        progress = await hr_training.complete(session, employee, code)
    except hr_training.TrainingError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if progress.complete and employee.onboarding_state != ONBOARDING_DONE:
        employee.onboarding_state = ONBOARDING_DONE
    await session.commit()
    await session.refresh(employee)
    return _training_out(progress, employee.onboarding_state)


@router.get("/departments", response_model=list[DepartmentOut])
async def departments(session: SessionDep, _: CurrentUser) -> list[DepartmentOut]:
    rows = await hr_departments.list_departments(session)
    return [
        DepartmentOut(
            id=d.id, name=d.name, slug=d.slug, emoji=d.emoji, sort_order=d.sort_order
        )
        for d in rows
    ]


# --------------------------------------------------------------------------
# Чек-лист смены
# --------------------------------------------------------------------------


@router.get("/checklist", response_model=ChecklistOut)
async def checklist(
    session: SessionDep,
    employee: EmployeeDep,
    kind: str = TEMPLATE_SHIFT,
    shift_date: date | None = None,
) -> ChecklistOut:
    view = await hr_checklists.build_view(
        session, employee, kind=kind, shift_date=shift_date
    )
    return _checklist_out(view)


@router.post("/checklist/complete", response_model=ChecklistOut)
async def checklist_complete(
    body: CompleteIn, session: SessionDep, employee: EmployeeDep
) -> ChecklistOut:
    item = await session.get(ChecklistItem, body.item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="item_not_found")
    template = await hr_checklists.get_template(session, item.template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="template_not_found")

    shift_date = hr_checklists.local_today()
    run = await hr_checklists.get_or_create_run(session, employee, template, shift_date)
    try:
        await hr_checklists.complete_item(
            session,
            employee=employee,
            run=run,
            item=item,
            photo_file_id=body.photo_file_id,
            note=body.note,
        )
    except hr_checklists.ChecklistError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()

    view = await hr_checklists.build_view(
        session, employee, kind=template.kind, shift_date=shift_date
    )
    return _checklist_out(view)


# --------------------------------------------------------------------------
# Поручения
# --------------------------------------------------------------------------


@router.get("/tasks", response_model=list[TaskOut])
async def my_tasks(
    session: SessionDep,
    employee: EmployeeDep,
    include_closed: bool = False,
    shift_date: date | None = None,
) -> list[TaskOut]:
    """Мои поручения. `shift_date` — только поручения конкретной смены."""
    rows = await hr_tasks.list_for_employee(
        session, employee, include_closed=include_closed
    )
    if shift_date is not None:
        rows = [task for task in rows if task.shift_date == shift_date]
    return await _task_views(session, rows, employee)


async def _owned_task(
    session: AsyncSession, employee: Employee, task_id: int
) -> Task:
    """Задача, доступная этому сотруднику (иначе 404 — не светим чужие id)."""
    task = await hr_tasks.get_task(session, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="task_not_found")
    visible = await hr_tasks.list_for_employee(session, employee, include_closed=True)
    if all(t.id != task.id for t in visible):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="task_not_found")
    return task


async def _transition(
    session: AsyncSession, employee: Employee, task_id: int, to_status: str
) -> TaskOut:
    task = await _owned_task(session, employee, task_id)
    try:
        await hr_tasks.change_status(session, task, to_status, by=employee)
    except hr_tasks.TaskError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(task)
    return (await _task_views(session, [task], employee))[0]


@router.post("/tasks/{task_id}/accept", response_model=TaskOut)
async def task_accept(
    task_id: int, session: SessionDep, employee: EmployeeDep
) -> TaskOut:
    from app.db.hr_models import TASK_ACCEPTED

    return await _transition(session, employee, task_id, TASK_ACCEPTED)


@router.post("/tasks/{task_id}/start", response_model=TaskOut)
async def task_start(
    task_id: int, session: SessionDep, employee: EmployeeDep
) -> TaskOut:
    from app.db.hr_models import TASK_IN_PROGRESS

    return await _transition(session, employee, task_id, TASK_IN_PROGRESS)


@router.post("/tasks/{task_id}/done", response_model=TaskOut)
async def task_done(
    task_id: int, session: SessionDep, employee: EmployeeDep
) -> TaskOut:
    """Сдать работу. Для задач с обязательным фото сервер откажет — их
    закрывает загрузка фото (`/tasks/{id}/photo`).

    Если поручение с проверкой, работа уходит руководителю (`on_review`) и
    остаётся открытой, пока он не примет её или не вернёт на доработку.
    """
    task = await _owned_task(session, employee, task_id)
    if task.requires_photo:
        photos = await hr_tasks.photos_of(session, task.id)
        if not photos:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="photo_report_required"
            )
    from app.db.hr_models import TASK_ON_REVIEW
    from app.services import hr_notify

    try:
        await hr_tasks.submit_work(session, task, employee)
    except hr_tasks.TaskError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if task.requires_review and task.status == TASK_ON_REVIEW:
        user = await session.get(User, employee.user_id)
        await hr_notify.notify_task_submitted(
            session,
            task,
            await _managers(session),
            employee_name=user.display_name if user else None,
        )
    await session.commit()
    await session.refresh(task)
    return (await _task_views(session, [task], employee))[0]


class TaskReviewIn(BaseModel):
    approve: bool
    # Принять одного исполнителя в групповом поручении; `None` — всех, кто
    # сдал (обычный случай: руководитель смотрит работу целиком).
    employee_id: int | None = None
    comment: str | None = None


@router.post("/tasks/{task_id}/review", response_model=TaskOut)
async def task_review(
    task_id: int,
    body: TaskReviewIn,
    session: SessionDep,
    employee: EmployeeDep,
) -> TaskOut:
    """Принять работу или вернуть на доработку. Только АУП.

    Сотрудник не может принять сам себя: `review` пишет событие приёмки на
    исполнителя и закрывает задачу, поэтому права проверяются до вызова.
    """
    if not hr_access.is_aup(employee):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="aup_required")
    task = await hr_tasks.get_task(session, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="task_not_found")
    try:
        reviewed = await hr_tasks.review(
            session,
            task,
            manager=employee,
            approve=body.approve,
            employee_id=body.employee_id,
            comment=body.comment,
        )
    except hr_tasks.TaskError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # Автору работы — в колокольчик: принято или что именно переделать.
    from app.services import hr_notify

    workers = await session.scalars(
        select(Employee).where(
            Employee.id.in_([row.employee_id for row in reviewed])
        )
    )
    await hr_notify.notify_task_reviewed(
        session,
        task,
        list(workers.all()),
        approved=body.approve,
        comment=body.comment,
    )
    await session.commit()
    await session.refresh(task)
    return (await _task_views(session, [task], employee))[0]


@router.get("/tasks/review-queue", response_model=list[TaskOut])
async def review_queue(
    session: SessionDep, employee: EmployeeDep
) -> list[TaskOut]:
    """Что ждёт приёмки руководителя (пусто для сотрудника)."""
    if not hr_access.is_aup(employee):
        return []
    rows = await hr_tasks.pending_reviews(
        session,
        department_id=(
            None if hr_access.is_admin(employee) else employee.department_id
        ),
    )
    unique: dict[int, Task] = {task.id: task for task, _ in rows}
    return await _task_views(session, list(unique.values()), employee)


@router.post("/tasks/{task_id}/issue", response_model=TaskOut)
async def task_issue(
    task_id: int, body: TaskIssueIn, session: SessionDep, employee: EmployeeDep
) -> TaskOut:
    from app.services import hr_notify, hr_reminders

    task = await _owned_task(session, employee, task_id)
    issue = await hr_tasks.add_issue(
        session,
        task,
        employee=employee,
        reason_code=body.reason_code,
        comment=body.comment,
        eta_at=body.eta_at,
    )
    # Руководителя уведомляем в приложении (видит проблему в списке) и в личке
    # бота — с кнопками «решено / напомнить завтра / мьют»: ответить можно
    # прямо в сообщении, не заходя в приложение.
    managers = await _managers(session)
    await hr_notify.notify_issue(session, task, issue, managers)
    await hr_reminders.alert_managers(
        session,
        employees=managers,
        kind=hr_notify.KIND_TASK_ISSUE,
        text=hr_notify.task_issue_text(task, issue),
        task_id=int(task.id),
    )
    await session.commit()
    await session.refresh(task)
    return (await _task_views(session, [task], employee))[0]


@router.post("/tasks/{task_id}/photo", response_model=TaskOut)
async def task_photo(
    task_id: int, body: TaskPhotoIn, session: SessionDep, employee: EmployeeDep
) -> TaskOut:
    task = await _owned_task(session, employee, task_id)
    try:
        await hr_tasks.add_photo(
            session, task, employee=employee, file_id=body.file_id
        )
    except hr_tasks.TaskError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(task)
    return (await _task_views(session, [task], employee))[0]


async def _managers(session: AsyncSession) -> list[Employee]:
    from app.db.hr_models import ROLE_ADMIN, ROLE_AUP

    rows = await session.scalars(
        select(Employee).where(
            Employee.is_active.is_(True),
            Employee.role.in_((ROLE_AUP, ROLE_ADMIN)),
        )
    )
    return list(rows.all())


# --------------------------------------------------------------------------
# Полезные ссылки и обратная связь
# --------------------------------------------------------------------------


@router.get("/links", response_model=list[LinkOut])
async def links(session: SessionDep, employee: EmployeeDep) -> list[LinkOut]:
    rows = await hr_links.list_links(session, employee)
    return [_link_out(link) for link in rows]


def _link_out(link: UsefulLink) -> LinkOut:
    return LinkOut(
        id=link.id,
        title=link.title,
        url=link.url,
        emoji=link.emoji,
        department_id=link.department_id,
    )


def _question_out(q: FeedbackQuestion) -> FeedbackQuestionOut:
    return FeedbackQuestionOut(
        id=q.id,
        code=q.code,
        text=q.text,
        kind=q.kind,
        options=list(q.options or []),
    )


@router.get("/feedback/questions", response_model=list[FeedbackQuestionOut])
async def feedback_questions(
    session: SessionDep, _: CurrentUser
) -> list[FeedbackQuestionOut]:
    rows = await hr_feedback.list_questions(session)
    return [_question_out(q) for q in rows]


@router.post("/feedback", response_model=list[FeedbackQuestionOut])
async def submit_feedback(
    body: FeedbackIn, session: SessionDep, _: CurrentUser, employee: EmployeeDep
) -> list[FeedbackQuestionOut]:
    shift_date = body.shift_date or hr_checklists.local_today()
    answers = [a.model_dump() for a in body.answers]
    try:
        await hr_feedback.submit_answers(
            session, employee=employee, shift_date=shift_date, answers=answers
        )
    except hr_feedback.FeedbackError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    rows = await hr_feedback.list_questions(session)
    return [_question_out(q) for q in rows]


# --------------------------------------------------------------------------
# Лента событий (видимость — строго по роли)
# --------------------------------------------------------------------------


class FeedItemOut(BaseModel):
    at: datetime
    kind: str
    employee_id: int | None
    user_id: int | None
    display_name: str
    department_id: int | None
    text: str
    ref_id: int | None
    badge: str | None = None
    badge_emoji: str | None = None


class FeedOut(BaseModel):
    scope: str
    can_filter: bool
    items: list[FeedItemOut]


class FeedFilterEmployee(BaseModel):
    id: int
    display_name: str
    department_id: int | None


class FeedFiltersOut(BaseModel):
    scope: str
    can_filter: bool
    kinds: list[str]
    employees: list[FeedFilterEmployee]
    departments: list[DepartmentOut]


@router.get("/feed/filters", response_model=FeedFiltersOut)
async def feed_filters(session: SessionDep, employee: EmployeeDep) -> FeedFiltersOut:
    """Списки для фильтров ленты — только в доступной области видимости.

    Нужен отдельный путь, потому что админский `/api/admin/employees` закрыт
    ролью `admin`: руководитель подразделения (`aup`) не смог бы собрать фильтр
    по своим людям. Здесь же состав списков считается ТЕМ ЖЕ правилом, что и
    сама лента (`hr_feed.allowed_employee_ids`), поэтому подсказки в фильтре не
    могут выдать чужих сотрудников. Сотрудник получает пустые списки и
    `can_filter=false` — фильтровать ему нечего.
    """
    scope = hr_feed.viewer_scope(employee)
    can_filter = hr_feed.can_filter(employee)

    employees: list[FeedFilterEmployee] = []
    departments: list[DepartmentOut] = []
    if can_filter:
        allowed = await hr_feed.allowed_employee_ids(session, employee)
        stmt = (
            select(Employee.id, Employee.department_id, User.display_name)
            .join(User, User.id == Employee.user_id)
            .where(Employee.is_active.is_(True))
            .order_by(User.display_name)
        )
        if allowed is not None:
            stmt = stmt.where(Employee.id.in_(allowed))
        rows = await session.execute(stmt)
        employees = [
            FeedFilterEmployee(id=int(eid), display_name=str(name), department_id=did)
            for eid, did, name in rows.all()
        ]
        # Подразделения: управляющий видит все, руководитель — только своё.
        # Срез считает hr_feed (та же функция, что и для самой ленты), а не
        # условие в роуте — правило одно и лежит в одном месте.
        all_departments = hr_feed.scoped_departments(
            employee, await hr_departments.list_departments(session)
        )
        departments = [
            DepartmentOut(
                id=d.id,
                name=d.name,
                slug=d.slug,
                emoji=d.emoji,
                sort_order=d.sort_order,
            )
            for d in all_departments
        ]

    return FeedFiltersOut(
        scope=scope,
        can_filter=can_filter,
        kinds=list(hr_feed.ALL_KINDS),
        employees=employees,
        departments=departments,
    )


@router.get("/me/achievements", response_model=AchievementsOut)
async def my_achievements(
    session: SessionDep, employee: EmployeeDep
) -> AchievementsOut:
    """Скрытый блок личного прогресса в профиле.

    Видимость решает сервер (`services/hr_achievements.visible_for`): сейчас
    ачивки показываются только руководителю и администратору, остальным ручка
    отвечает `visible=false` без обращения к базе. Пороги считаются на чтение и
    выдаются идемпотентно, поэтому блок сам «догоняет» закрытые поручения и
    смены — без джоб и событий.
    """
    view = await hr_achievements.view(session, employee)
    return _achievements_out(view)


@router.get("/kpi", response_model=MyKpiOut)
async def my_kpi(session: SessionDep, employee: EmployeeDep) -> MyKpiOut:
    """Опыт за работу и звание — открыто всем, а не только руководителю.

    В отличие от скрытых ачивок это мотивационный блок: сотрудник видит, за что
    получил опыт (пункты, смены, поручения), сколько до следующего звания и где
    он в недельном рейтинге. Никаких штрафов и «антизваний» здесь нет.
    """
    data = await hr_kpi.my_kpi(session, employee, hr_checklists.local_today())
    return to_my_out(data)


@router.get("/feed", response_model=FeedOut)
async def feed(
    session: SessionDep,
    employee: EmployeeDep,
    employee_id: int | None = None,
    department_id: int | None = None,
    kinds: str | None = None,
    limit: int = hr_feed.DEFAULT_LIMIT,
) -> FeedOut:
    """Лента действий. Кто что видит — решает сервер (см. `services/hr_feed`).

    Сотрудник получает только свои записи; фильтры по сотруднику/подразделению
    для него игнорируются, а не «прячутся в UI». Руководитель подразделения —
    действия своих; управляющий — всё с фильтрами.
    """
    selected_kinds: tuple[str, ...] | None = None
    if kinds:
        selected_kinds = tuple(
            k.strip() for k in kinds.split(",") if k.strip()
        )
    try:
        items = await hr_feed.build_feed(
            session,
            employee,
            employee_id=employee_id,
            department_id=department_id,
            kinds=selected_kinds,
            limit=limit,
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return FeedOut(
        scope=hr_feed.viewer_scope(employee),
        can_filter=hr_feed.can_filter(employee),
        items=[
            FeedItemOut(
                at=item.at,
                kind=item.kind,
                employee_id=item.employee_id,
                user_id=item.user_id,
                display_name=item.display_name,
                department_id=item.department_id,
                text=item.text,
                ref_id=item.ref_id,
                badge=item.badge,
                badge_emoji=item.badge_emoji,
            )
            for item in items
        ],
    )
