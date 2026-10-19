"""Админка: журнал событий, центр уведомлений и пул сотрудников.

Всё, что раньше приходилось делать руками в базе:

* `GET  /journal` — человекочитаемая история поручений, включая системные
  строки планировщика (`auto_overdue`, `reminder_sent`). В кабинете управляющего
  их нет: там нужен разбор смены, а не лог. Здесь — наоборот, есть.
* `GET  /notifications` — что лежит в колокольчиках и что запланировано:
  кому и во сколько уйдёт напоминание о сроке, включая вторую ступень.
* `POST /notifications/{id}/cancel`, `POST /notifications/send` — убрать
  конкретное уведомление или отправить сотруднику личное сообщение.
* `GET  /employees-pool` и правки профиля — переименовать, поставить
  должность/плашку, обнулить прогресс знакомства, зачесть проваленное
  поручение.
* Увольнение: доступ закрывается сразу, данные — в корзину на 30 дней или
  сразу в небытие. Восстановление — одна кнопка, автоудаление — планировщик.

Права: журнал и пул доступны `AupDep` (руководитель видит только своё
подразделение), уведомления — тоже; правила области считает сервис
(`services/hr_admin_ops`), а не клиент.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import AdminDep, AupDep, SessionDep
from app.db.hr_models import Employee
from app.services import hr_admin_ops

router = APIRouter(tags=["hr-admin-ops"])


# --------------------------------------------------------------------------
# Схемы
# --------------------------------------------------------------------------


class JournalItemOut(BaseModel):
    at: datetime
    kind: str
    text: str
    is_system: bool
    task_id: int | None
    task_title: str | None
    employee_id: int | None
    display_name: str | None


class JournalOut(BaseModel):
    """Журнал отдаём плоским списком: группирует клиент."""

    items: list[JournalItemOut]


class NotificationItemOut(BaseModel):
    id: int
    kind: str
    text: str
    created_at: datetime
    read_at: datetime | None
    employee_id: int | None
    user_id: int
    display_name: str | None
    department_name: str | None


class PendingNotificationOut(BaseModel):
    kind: str
    at: datetime
    text: str
    task_id: int
    task_title: str
    employee_id: int
    display_name: str


class NotificationsOut(BaseModel):
    items: list[NotificationItemOut]
    pending: list[PendingNotificationOut]
    muted_until: datetime | None
    scheduled_enabled: bool


class NotificationSendIn(BaseModel):
    employee_id: int
    text: str = Field(min_length=1, max_length=400)


class EmployeeCardOut(BaseModel):
    employee_id: int
    user_id: int
    display_name: str
    position: str | None
    badge: str | None
    badge_emoji: str | None
    role: str
    department_id: int | None
    department_name: str | None
    onboarding_state: str
    learning_mode: bool
    is_demo: bool
    is_active: bool
    fired_at: datetime | None
    purge_after: datetime | None


class EmployeesPoolOut(BaseModel):
    items: list[EmployeeCardOut]
    trash_days: int


class EmployeePatchIn(BaseModel):
    """Частичная правка: меняются только присланные поля."""

    display_name: str | None = Field(None, max_length=64)
    position: str | None = Field(None, max_length=64)
    badge: str | None = Field(None, max_length=64)
    badge_emoji: str | None = Field(None, max_length=8)


class FireIn(BaseModel):
    """Как поступить с данными: корзина на 30 дней или удалить сразу."""

    mode: str = Field(pattern="^(trash|purge)$")


class ForceDoneIn(BaseModel):
    employee_id: int
    comment: str | None = Field(None, max_length=120)


class TaskBriefOut(BaseModel):
    id: int
    status: str


# --------------------------------------------------------------------------
# Помощники
# --------------------------------------------------------------------------


def _ops_error(exc: hr_admin_ops.AdminOpsError) -> HTTPException:
    code = str(exc)
    if code == "employee_not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=code)
    if code == "task_not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=code)
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=code)


def _card(card: hr_admin_ops.EmployeeCard) -> EmployeeCardOut:
    return EmployeeCardOut(**card.__dict__)


async def _employee(session: SessionDep, viewer: Employee, employee_id: int) -> Employee:
    """Сотрудник в области видимости смотрящего — иначе 404, а не 403."""
    try:
        return await hr_admin_ops.employee_in_scope(session, viewer, employee_id)
    except hr_admin_ops.AdminOpsError as exc:
        raise _ops_error(exc) from exc


# --------------------------------------------------------------------------
# Журнал
# --------------------------------------------------------------------------


@router.get("/journal", response_model=JournalOut)
async def journal(
    session: SessionDep,
    employee: AupDep,
    limit: int = hr_admin_ops.JOURNAL_LIMIT,
) -> JournalOut:
    items = await hr_admin_ops.journal(session, employee, limit=limit)
    return JournalOut(
        items=[
            JournalItemOut(
                at=item.at,
                kind=item.kind,
                text=item.text,
                is_system=item.is_system,
                task_id=item.task_id,
                task_title=item.task_title,
                employee_id=item.employee_id,
                display_name=item.display_name,
            )
            for item in items
        ]
    )


# --------------------------------------------------------------------------
# Центр уведомлений
# --------------------------------------------------------------------------


@router.get("/notifications", response_model=NotificationsOut)
async def notifications(
    session: SessionDep,
    employee: AupDep,
    limit: int = hr_admin_ops.NOTIFICATION_LIMIT,
) -> NotificationsOut:
    items, pending, muted_until = await hr_admin_ops.notification_feed(
        session, employee, limit=limit
    )
    return NotificationsOut(
        items=[NotificationItemOut(**item.__dict__) for item in items],
        pending=[PendingNotificationOut(**item.__dict__) for item in pending],
        muted_until=muted_until,
        scheduled_enabled=True,
    )


@router.post("/notifications/{notification_id}/cancel")
async def cancel_notification(
    notification_id: int, session: SessionDep, _: AdminDep
) -> dict[str, bool]:
    """Убрать одно уведомление из колокольчика (и только у администратора)."""
    removed = await hr_admin_ops.cancel_notification(session, notification_id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="notification_not_found")
    return {"removed": True}


@router.post("/notifications/send", response_model=NotificationItemOut)
async def send_notification(
    body: NotificationSendIn, session: SessionDep, employee: AupDep
) -> NotificationItemOut:
    """Личное сообщение сотруднику в приложение (в чат не дублируем)."""
    target = await _employee(session, employee, body.employee_id)
    row = await hr_admin_ops.send_notification(session, employee=target, text=body.text)
    return NotificationItemOut(
        id=int(row.id),
        kind=str(row.kind),
        text=str(row.text),
        created_at=row.created_at,
        read_at=row.read_at,
        employee_id=int(target.id),
        user_id=int(target.user_id),
        display_name=None,
        department_name=None,
    )


# --------------------------------------------------------------------------
# Пул сотрудников
# --------------------------------------------------------------------------


@router.get("/employees-pool", response_model=EmployeesPoolOut)
async def employees_pool(session: SessionDep, employee: AupDep) -> EmployeesPoolOut:
    cards = await hr_admin_ops.directory(session, employee)
    return EmployeesPoolOut(
        items=[_card(card) for card in cards],
        trash_days=hr_admin_ops.TRASH_DAYS,
    )


@router.patch("/employees/{employee_id}", response_model=EmployeeCardOut)
async def patch_employee(
    employee_id: int,
    body: EmployeePatchIn,
    session: SessionDep,
    employee: AupDep,
) -> EmployeeCardOut:
    """Переименовать, поменять должность или плашку. Пустая строка — очистить."""
    try:
        card = await hr_admin_ops.update_profile(
            session,
            employee,
            employee_id,
            display_name=body.display_name,
            position=body.position,
            badge=body.badge,
            badge_emoji=body.badge_emoji,
        )
    except hr_admin_ops.AdminOpsError as exc:
        raise _ops_error(exc) from exc
    return _card(card)


@router.post("/employees/{employee_id}/reset-progress", response_model=EmployeeCardOut)
async def reset_employee_progress(
    employee_id: int, session: SessionDep, employee: AupDep
) -> EmployeeCardOut:
    """Обнулить знакомство: онбординг и уроки. Отдел и опыт остаются."""
    try:
        card = await hr_admin_ops.reset_progress(session, employee, employee_id)
    except hr_admin_ops.AdminOpsError as exc:
        raise _ops_error(exc) from exc
    return _card(card)


@router.post("/employees/{employee_id}/fire", response_model=EmployeeCardOut)
async def fire_employee(
    employee_id: int,
    body: FireIn,
    session: SessionDep,
    employee: AdminDep,
) -> EmployeeCardOut:
    """Уволить: доступ закрывается сразу, данные — по выбранному режиму.

    Только администратор: увольнение не должно зависеть от настроения
    руководителя подразделения.
    """
    try:
        card = await hr_admin_ops.fire(
            session, employee, employee_id, mode=body.mode
        )
    except hr_admin_ops.AdminOpsError as exc:
        raise _ops_error(exc) from exc
    return _card(card)


@router.post("/employees/{employee_id}/restore", response_model=EmployeeCardOut)
async def restore_employee(
    employee_id: int, session: SessionDep, employee: AupDep
) -> EmployeeCardOut:
    """Вернуть из корзины, пока не истекли 30 дней."""
    try:
        card = await hr_admin_ops.restore(session, employee, employee_id)
    except hr_admin_ops.AdminOpsError as exc:
        raise _ops_error(exc) from exc
    return _card(card)


@router.post("/tasks/{task_id}/force-done", response_model=TaskBriefOut)
async def force_task_done(
    task_id: int,
    body: ForceDoneIn,
    session: SessionDep,
    employee: AupDep,
) -> TaskBriefOut:
    """Зачесть поручение выполненным за конкретного человека (ручное решение)."""
    try:
        task = await hr_admin_ops.force_done(
            session,
            employee,
            task_id,
            body.employee_id,
            comment=body.comment,
        )
    except hr_admin_ops.AdminOpsError as exc:
        raise _ops_error(exc) from exc
    return TaskBriefOut(id=int(task.id), status=str(task.status))


__all__ = ["router"]
