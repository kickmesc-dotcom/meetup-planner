"""«Сказал — стало поручением» (план, 8.5): ручки разбора и создания.

Два шага, а не один, и это осознанно:

1. `POST /api/hr/quick/parse` — разбор фразы в черновик. Ничего не пишет в базу
   и никого не уведомляет: руководитель сначала видит, как его поняли.
2. `POST /api/hr/quick/task` — создание. Черновик можно поправить (исполнитель,
   срок, срочность), поэтому ручка принимает и текст, и явные значения.

Оба шага под `AupDep`: поручение — это распоряжение, а не заметка. Сотрудник
не должен уметь разослать задачи всей смене, даже если разберёт фразу сам.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import AupDep, SessionDep
from app.db.hr_models import (
    PRIORITIES,
    TASK_SCOPES,
    TASK_SCOPE_DEPARTMENT,
    TASK_SCOPE_EMPLOYEE,
    Employee,
)
from app.db.models import User
from app.services import (
    hr_demo,
    hr_feed,
    hr_notify,
    hr_quick,
    hr_settings,
    hr_simulation,
    hr_tasks,
)

router = APIRouter(prefix="/hr/quick", tags=["hr"])


class QuickParseIn(BaseModel):
    # 500 символов — предел голосовой расшифровки одной фразы; длиннее человек
    # не диктует, а если диктует — это уже не «одно поручение».
    text: str = Field(min_length=1, max_length=500)


class QuickPersonOut(BaseModel):
    id: int
    name: str
    position: str | None = None
    department_id: int | None = None


class QuickDraftOut(BaseModel):
    title: str
    text: str
    scope: str
    assignee: QuickPersonOut | None
    candidates: list[QuickPersonOut]
    department_id: int | None
    due_at: datetime | None
    due_kind: str
    priority: str
    requires_photo: bool
    requires_review: bool
    unclear: list[str]


class QuickTaskIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    # Всё ниже — необязательные правки к черновику. `None` значит «как разобрал
    # сервер», а не «сбросить»: руководитель, ничего не тронувший, отправляет
    # ровно тот текст, что произнёс.
    title: str | None = Field(default=None, max_length=hr_quick.MAX_TITLE)
    scope: str | None = None
    assignee_employee_id: int | None = None
    department_id: int | None = None
    due_at: datetime | None = None
    priority: str | None = None
    requires_photo: bool | None = None
    requires_review: bool | None = None


class QuickTaskOut(BaseModel):
    id: int
    title: str
    due_at: datetime | None
    status: str
    scope: str
    assignee_name: str | None


async def _roster(session, viewer: Employee) -> list[hr_quick.QuickPerson]:
    """Кто может стать исполнителем: та же область, что видит лента.

    Список не берётся из админской ручки «люди»: руководитель подразделения
    не админ, но назначать своим людям ему нужно. Заодно подсказка не может
    выдать человека из чужого подразделения.
    """
    allowed = await hr_feed.allowed_employee_ids(session, viewer)
    hidden = await hr_demo.hidden_employee_ids(session)
    rows = await session.execute(
        select(Employee.id, Employee.position, Employee.department_id, User.display_name)
        .join(User, User.id == Employee.user_id)
        .where(
            Employee.is_active.is_(True),
            Employee.is_simulation.is_(False),
            Employee.fired_at.is_(None),
        )
        .order_by(User.display_name)
    )
    people: list[hr_quick.QuickPerson] = []
    for employee_id, position, department_id, name in rows.all():
        if allowed is not None and int(employee_id) not in allowed:
            continue
        if int(employee_id) in hidden:
            continue
        people.append(
            hr_quick.QuickPerson(
                id=int(employee_id),
                name=name or "Без имени",
                position=position,
                department_id=department_id,
            )
        )
    return people


async def _draft(session, employee: Employee, text: str) -> hr_quick.QuickDraft:
    """Разбор с настройками заведения: смена и часовой пояс — из базы."""
    # Время заведения, а не UTC: «к закрытию» в 02:00 ночной смены — это
    # местные 02:00, иначе срок уезжает на три часа.
    now = hr_settings.local_now()
    opens_at = await hr_settings.get_work_open(session)
    closes_at = await hr_settings.get_work_close(session)
    return hr_quick.parse(
        text,
        now=now,
        opens_at=opens_at,
        closes_at=closes_at,
        people=await _roster(session, employee),
        my_department_id=employee.department_id,
        me_id=int(employee.id),
    )


def _person_out(person: hr_quick.QuickPerson | None) -> QuickPersonOut | None:
    if person is None:
        return None
    return QuickPersonOut(
        id=person.id,
        name=person.name,
        position=person.position,
        department_id=person.department_id,
    )


def _draft_out(draft: hr_quick.QuickDraft) -> QuickDraftOut:
    return QuickDraftOut(
        title=draft.title,
        text=draft.text,
        scope=draft.scope,
        assignee=_person_out(draft.assignee),
        candidates=[p for p in (_person_out(c) for c in draft.candidates) if p],
        department_id=draft.department_id,
        due_at=draft.due_at,
        due_kind=draft.due_kind,
        priority=draft.priority,
        requires_photo=draft.requires_photo,
        requires_review=draft.requires_review,
        unclear=list(draft.unclear),
    )


@router.get("/people", response_model=list[QuickPersonOut])
async def quick_people(session: SessionDep, employee: AupDep) -> list[QuickPersonOut]:
    """Кому можно назначить: тот же состав, из которого строятся подсказки.

    Отдельная ручка, а не поле в разборе: список нужен только когда человек
    меняет исполнителя руками, а тащить его в каждый разбор — лишние байты на
    каждом нажатии клавиши.
    """
    people = await _roster(session, employee)
    return [out for out in (_person_out(person) for person in people) if out]


@router.post("/parse", response_model=QuickDraftOut)
async def parse_quick(
    body: QuickParseIn, session: SessionDep, employee: AupDep
) -> QuickDraftOut:
    """Разобрать фразу. Ничего не создаёт и никого не будит."""
    draft = await _draft(session, employee, body.text)
    return _draft_out(draft)


@router.post("/task", response_model=QuickTaskOut)
async def create_quick_task(
    body: QuickTaskIn, session: SessionDep, employee: AupDep
) -> QuickTaskOut:
    """Создать поручение из фразы — с правками черновика, если они были."""
    draft = await _draft(session, employee, body.text)

    scope = body.scope or draft.scope
    if scope not in TASK_SCOPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_scope")

    assignee_id = (
        body.assignee_employee_id
        if body.assignee_employee_id is not None
        else (draft.assignee.id if draft.assignee is not None else None)
    )
    department_id = (
        body.department_id
        if body.department_id is not None
        else draft.department_id
    )

    # Проверка исполнителя идёт по тому же составу, из которого строились
    # подсказки: иначе id из чужого подразделения прошёл бы мимо подсказки, но
    # создал бы реальное поручение человеку, которого руководитель не видит.
    if assignee_id is not None:
        roster = {person.id: person for person in await _roster(session, employee)}
        if assignee_id not in roster:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="assignee_out_of_scope"
            )
    if scope == TASK_SCOPE_EMPLOYEE and assignee_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="assignee_required")
    if scope == TASK_SCOPE_DEPARTMENT and department_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="department_required"
        )

    # Песочница проверки: поручение другому человеку — реальное внешнее
    # действие, поэтому разрешено только «себе». Правило то же, что в админке.
    if hr_simulation.current() is not None and (
        scope != TASK_SCOPE_EMPLOYEE or assignee_id != int(employee.id)
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="simulation_self_only"
        )

    priority = body.priority or draft.priority
    if priority not in PRIORITIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_priority")

    title = (body.title or draft.title).strip()
    if not title:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="empty_title")

    try:
        task = await hr_tasks.create_task(
            session,
            creator=employee,
            title=title,
            scope=scope,
            department_id=department_id,
            assignee_employee_id=assignee_id,
            due_at=body.due_at if body.due_at is not None else draft.due_at,
            priority=priority,
            requires_photo=(
                body.requires_photo
                if body.requires_photo is not None
                else draft.requires_photo
            ),
            requires_review=(
                body.requires_review
                if body.requires_review is not None
                else draft.requires_review
            ),
            # Фраза целиком сохраняется описанием: в заголовке она обрезана до
            # «Протри витрину», а детали («и не забудь про низ») терять нельзя.
            description=draft.text if draft.text.strip() != title else None,
        )
    except hr_tasks.TaskError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    recipients = await hr_tasks.assignees(session, task)
    await hr_notify.notify_task_assigned(session, task, recipients)
    await session.commit()
    await session.refresh(task)

    # Имя исполнителя — для ответа «создано: Аня к 18:00». Берём из тех же
    # строк, что получили поручение, а не из черновика: в групповом режиме
    # исполнителей много, и черновик об этом ничего не знает.
    names: list[str] = []
    ids = [int(recipient.id) for recipient in recipients]
    if ids:
        rows = await session.execute(
            select(User.display_name).where(
                User.id.in_(
                    select(Employee.user_id).where(Employee.id.in_(ids))
                )
            )
        )
        names = [name for name in rows.scalars().all() if name]
    return QuickTaskOut(
        id=int(task.id),
        title=task.title,
        due_at=task.due_at,
        status=task.status,
        scope=task.scope,
        assignee_name=", ".join(names) if names else None,
    )
