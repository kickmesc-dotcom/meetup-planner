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
* Ручное заведение по Telegram-ID (`POST /employees-pool/add`): человек
  появляется в боте до того, как сам его откроет.
* Снапшоты состава (`/roster-snapshots`): снять состав вручную, посмотреть
  историю, вернуть людей по `telegram_id`. Перед удалением снимок снимается
  сам — пул ID не теряется вместе с данными.

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
from app.services import hr_admin_ops, hr_roster

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
    moved: bool = False


class DisabledReminderOut(BaseModel):
    task_id: int
    task_title: str
    employee_id: int
    display_name: str


class NotificationsOut(BaseModel):
    items: list[NotificationItemOut]
    pending: list[PendingNotificationOut]
    muted_until: datetime | None
    scheduled_enabled: bool
    disabled: list[DisabledReminderOut] = []


class PostponeIn(BaseModel):
    """На сколько сдвинуть напоминание вперёд (5 минут … 7 дней)."""

    minutes: int = Field(ge=5, le=7 * 24 * 60)


class ReminderMovedOut(BaseModel):
    at: datetime


class NotificationSendIn(BaseModel):
    employee_id: int
    text: str = Field(min_length=1, max_length=400)


class EmployeeCardOut(BaseModel):
    employee_id: int
    user_id: int
    # Telegram-ID нужен в админке: по нему ищут человека и выдают права.
    telegram_id: int
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
    profile_public: bool = True


class EmployeesPoolOut(BaseModel):
    items: list[EmployeeCardOut]
    trash_days: int


class EmployeePatchIn(BaseModel):
    """Частичная правка: меняются только присланные поля."""

    display_name: str | None = Field(None, max_length=64)
    position: str | None = Field(None, max_length=64)
    badge: str | None = Field(None, max_length=64)
    badge_emoji: str | None = Field(None, max_length=8)
    # Роль меняет только администратор (проверка — в сервисе).
    role: str | None = Field(None, pattern="^(employee|aup|admin)$")


class FireIn(BaseModel):
    """Как поступить с данными: корзина на 30 дней или удалить сразу."""

    mode: str = Field(pattern="^(trash|purge)$")


class ForceDoneIn(BaseModel):
    employee_id: int
    comment: str | None = Field(None, max_length=120)


class AddPersonIn(BaseModel):
    """Ручное заведение по Telegram-ID: остальные поля — по желанию."""

    telegram_id: int = Field(ge=1)
    display_name: str | None = Field(None, max_length=96)
    department_id: int | None = None
    position: str | None = Field(None, max_length=64)
    badge: str | None = Field(None, max_length=64)
    role: str | None = Field(None, pattern="^(employee|aup|admin)$")


class SnapshotOut(BaseModel):
    id: int
    label: str
    kind: str
    source: str
    people_count: int
    created_at: datetime


class SnapshotListOut(BaseModel):
    items: list[SnapshotOut]
    max_snapshots: int


class SnapshotDetailOut(BaseModel):
    snapshot: SnapshotOut
    # Состав отдаём как есть: это исторический JSON, и жёсткая схема здесь
    # сломала бы старые снимки после любой правки полей.
    people: list[dict[str, object]]


class SnapshotIn(BaseModel):
    label: str | None = Field(None, max_length=120)


class RestoreResultOut(BaseModel):
    created: int
    restored: int
    skipped: int
    departments_missing: list[str]


class TaskBriefOut(BaseModel):
    id: int
    status: str


# --------------------------------------------------------------------------
# Помощники
# --------------------------------------------------------------------------


def _ops_error(exc: hr_admin_ops.AdminOpsError) -> HTTPException:
    code = str(exc)
    if code in ("employee_not_found", "task_not_found"):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=code)
    if code in ("already_exists", "employee_fired"):
        # Это не ошибка ввода: ID верный, просто человек уже есть.
        return HTTPException(status.HTTP_409_CONFLICT, detail=code)
    if code in ("role_admin_only", "cannot_demote_self"):
        # Руководитель подразделения не выдаёт права выше своих.
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=code)
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=code)


def _roster_error(exc: hr_roster.RosterError) -> HTTPException:
    code = str(exc)
    if code == "snapshot_not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=code)
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=code)


def _snapshot(row: hr_roster.SnapshotSummary) -> SnapshotOut:
    return SnapshotOut(**row.__dict__)


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
    items, pending, muted_until, disabled = await hr_admin_ops.notification_feed(
        session, employee, limit=limit
    )
    return NotificationsOut(
        items=[NotificationItemOut(**item.__dict__) for item in items],
        pending=[PendingNotificationOut(**item.__dict__) for item in pending],
        muted_until=muted_until,
        scheduled_enabled=True,
        disabled=[DisabledReminderOut(**item.__dict__) for item in disabled],
    )


@router.post(
    "/notifications/pending/{task_id}/postpone", response_model=ReminderMovedOut
)
async def postpone_pending_notification(
    task_id: int, body: PostponeIn, session: SessionDep, employee: AupDep
) -> ReminderMovedOut:
    """Передвинуть напоминание о сроке, не меняя срок поручения."""
    try:
        at = await hr_admin_ops.postpone_pending(
            session, employee, task_id, minutes=body.minutes
        )
    except hr_admin_ops.AdminOpsError as exc:
        raise _ops_error(exc) from exc
    return ReminderMovedOut(at=at)


@router.post("/notifications/pending/{task_id}/skip")
async def skip_pending_notification(
    task_id: int, session: SessionDep, employee: AupDep
) -> dict[str, bool]:
    """Выключить напоминание о сроке по этому поручению."""
    try:
        await hr_admin_ops.skip_pending(session, employee, task_id)
    except hr_admin_ops.AdminOpsError as exc:
        raise _ops_error(exc) from exc
    return {"skipped": True}


@router.post("/notifications/pending/{task_id}/reset")
async def reset_pending_notification(
    task_id: int, session: SessionDep, employee: AupDep
) -> dict[str, bool]:
    """Вернуть напоминание к обычному расчёту планировщика."""
    try:
        await hr_admin_ops.reset_pending(session, employee, task_id)
    except hr_admin_ops.AdminOpsError as exc:
        raise _ops_error(exc) from exc
    return {"reset": True}


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


@router.post("/employees-pool/add", response_model=EmployeeCardOut)
async def add_employee(
    body: AddPersonIn, session: SessionDep, employee: AdminDep
) -> EmployeeCardOut:
    """Завести сотрудника по Telegram-ID (только администратор)."""
    try:
        card = await hr_admin_ops.add_person(
            session,
            employee,
            telegram_id=body.telegram_id,
            display_name=body.display_name,
            department_id=body.department_id,
            position=body.position,
            badge=body.badge,
            role=body.role,
        )
    except hr_admin_ops.AdminOpsError as exc:
        raise _ops_error(exc) from exc
    return _card(card)


@router.get("/employees-pool/find", response_model=EmployeeCardOut)
async def find_employee_by_telegram_id(
    telegram_id: int, session: SessionDep, employee: AdminDep
) -> EmployeeCardOut:
    """Найти человека по Telegram-ID: выдать роль, проверить, есть ли он в пуле.

    Отдельная ручка, а не поиск по уже загруженному списку: пул обрезан
    `DIRECTORY_LIMIT`, и человек из хвоста списка «не находился» бы, хотя он
    есть. Ищем напрямую по ID в базе.
    """
    try:
        card = await hr_admin_ops.card_by_telegram_id(session, employee, telegram_id)
    except hr_admin_ops.AdminOpsError as exc:
        raise _ops_error(exc) from exc
    return _card(card)


@router.patch("/employees/{employee_id}", response_model=EmployeeCardOut)
async def patch_employee(
    employee_id: int,
    body: EmployeePatchIn,
    session: SessionDep,
    employee: AupDep,
) -> EmployeeCardOut:
    """Переименовать, поменять должность/плашку или роль. Пустая строка — очистить."""
    try:
        card = await hr_admin_ops.update_profile(
            session,
            employee,
            employee_id,
            display_name=body.display_name,
            position=body.position,
            badge=body.badge,
            badge_emoji=body.badge_emoji,
            role=body.role,
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


# --------------------------------------------------------------------------
# Снапшоты состава
# --------------------------------------------------------------------------


@router.get("/roster-snapshots", response_model=SnapshotListOut)
async def roster_snapshots(session: SessionDep, _: AdminDep) -> SnapshotListOut:
    """История снимков состава: ручные и автоматические (перед удалением)."""
    items = await hr_roster.list_snapshots(session)
    return SnapshotListOut(
        items=[_snapshot(item) for item in items],
        max_snapshots=hr_roster.MAX_SNAPSHOTS,
    )


@router.post("/roster-snapshots", response_model=SnapshotDetailOut)
async def create_roster_snapshot(
    body: SnapshotIn, session: SessionDep, employee: AdminDep
) -> SnapshotDetailOut:
    """Снять состав вручную — например, перед большой чисткой."""
    row = await hr_roster.capture(
        session,
        created_by_employee_id=int(employee.id),
        label=body.label or "Снимок вручную",
        kind=hr_roster.KIND_MANUAL,
        source=hr_roster.SOURCE_MANUAL,
    )
    snapshot = _snapshot(hr_roster.summary_of(row))
    people = [item for item in (row.payload or []) if isinstance(item, dict)]
    return SnapshotDetailOut(snapshot=snapshot, people=people)


@router.get("/roster-snapshots/{snapshot_id}", response_model=SnapshotDetailOut)
async def roster_snapshot(
    snapshot_id: int, session: SessionDep, _: AdminDep
) -> SnapshotDetailOut:
    try:
        data = await hr_roster.detail(session, snapshot_id)
    except hr_roster.RosterError as exc:
        raise _roster_error(exc) from exc
    return SnapshotDetailOut(snapshot=_snapshot(data.summary), people=data.people)


@router.post(
    "/roster-snapshots/{snapshot_id}/restore", response_model=RestoreResultOut
)
async def restore_roster_snapshot(
    snapshot_id: int, session: SessionDep, _: AdminDep
) -> RestoreResultOut:
    """Вернуть людей из снимка по Telegram-ID (активных не трогаем)."""
    try:
        result = await hr_roster.restore(session, snapshot_id)
    except hr_roster.RosterError as exc:
        raise _roster_error(exc) from exc
    return RestoreResultOut(**result.__dict__)


@router.delete("/roster-snapshots/{snapshot_id}")
async def delete_roster_snapshot(
    snapshot_id: int, session: SessionDep, _: AdminDep
) -> dict[str, bool]:
    """Удалить снимок: он больше не нужен."""
    if not await hr_roster.remove(session, snapshot_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="snapshot_not_found")
    return {"removed": True}


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
