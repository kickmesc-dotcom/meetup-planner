"""Режим проверки: приложение глазами сотрудника без следов в реальной истории.

Зачем теневой профиль, а не «подменить employee_id в запросе». Подмена дала бы
тестовые задачи настоящему человеку и испортила бы его кабинет, ленту и KPI.
Поэтому сеанс создаёт копию сотрудника (`employees.is_simulation=true`) с
отдельным `users`-row и отрицательным Telegram ID:

* все задачи, смены, проблемы и уведомления сеанса висят на копии;
* личные сообщения копии никуда не уходят (отрицательный Telegram ID);
* копия исключена из ленты, кабинета, отчётов и рейтинга реальных людей;
* выход удаляет копию вместе с её данными, а аудит-запись о сеансе остаётся.

Ограничения сознательные и явные: в режиме проверки нельзя ставить поручения
другим людям и заводить проблемы в общий журнал отдела — это уже внешние
действия, а не проверка интерфейса. Такие попытки отклоняются сервером.
"""

from __future__ import annotations

import random
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    SIM_ACTIVE,
    SIM_ENDED,
    SIM_FAILED,
    SIM_MODE_AS_IS,
    SIM_MODE_NEW,
    SIM_MODES,
    ChecklistRun,
    Employee,
    FeedbackAnswer,
    Handover,
    Issue,
    SimulationSession,
    Task,
    TaskAssignment,
)
from app.db.models import AppNotification, User
from app.services import hr_access

log = structlog.get_logger()

# Кого сейчас проверяют — в пределах одного HTTP-запроса. Контекст нужен
# роутам, которые создают объекты: им не надо тащить сеанс через все сигнатуры.
_current: ContextVar[SimulationContext | None] = ContextVar(
    "hr_simulation_context", default=None
)


@dataclass(frozen=True)
class SimulationContext:
    session_id: int
    shadow: Employee
    subject_name: str
    department_name: str | None
    mode: str


@dataclass(frozen=True)
class SimulationStart:
    session_id: int
    shadow_employee_id: int
    subject_employee_id: int
    subject_name: str
    department_name: str | None
    mode: str
    started_at: datetime


@dataclass(frozen=True)
class CleanupResult:
    tasks: int = 0
    runs: int = 0
    issues: int = 0
    already_ended: bool = False


def current() -> SimulationContext | None:
    """Активный сеанс проверки в этом запросе (или `None`)."""
    return _current.get()


def current_session_id() -> int | None:
    ctx = current()
    return ctx.session_id if ctx else None


def activate(ctx: SimulationContext) -> Token[SimulationContext | None]:
    return _current.set(ctx)


def deactivate(token: Token[SimulationContext | None]) -> None:
    _current.reset(token)


def _fake_telegram_id() -> int:
    """Отрицательный ID: Telegram такие не принимает, DM физически не уйдёт."""
    return -(1_000_000_000 + random.randint(1, 900_000_000))


async def _unique_fake_telegram_id(session: AsyncSession) -> int:
    for _ in range(10):
        candidate = _fake_telegram_id()
        exists = await session.scalar(
            select(func.count()).select_from(User).where(User.telegram_id == candidate)
        )
        if not exists:
            return candidate
    raise hr_access.HrAccessError("simulation_id_exhausted")


async def hidden_employee_ids(session: AsyncSession) -> set[int]:
    """Теневые профили: их активность нельзя показывать реальным людям."""
    rows = await session.scalars(
        select(Employee.id).where(Employee.is_simulation.is_(True))
    )
    return {int(i) for i in rows.all()}


async def _department_name(session: AsyncSession, department_id: int | None) -> str | None:
    if department_id is None:
        return None
    from app.db.hr_models import Department

    department = await session.get(Department, department_id)
    return department.name if department else None


async def start(
    session: AsyncSession,
    *,
    actor: Employee,
    user: User,
    subject_id: int,
    mode: str = SIM_MODE_NEW,
) -> SimulationStart:
    """Начать сеанс проверки. Доступен только админу/прописанному владельцу."""
    if not (hr_access.is_admin(actor) or hr_access.is_staff(actor, user)):
        raise hr_access.HrAccessError("admin_required")
    if mode not in SIM_MODES:
        raise hr_access.HrAccessError("bad_simulation_mode")

    active = await session.scalar(
        select(SimulationSession.id).where(
            SimulationSession.actor_employee_id == int(actor.id),
            SimulationSession.status == SIM_ACTIVE,
        )
    )
    if active is not None:
        raise hr_access.HrAccessError("simulation_already_active")

    subject = await session.get(Employee, subject_id)
    if subject is None or not subject.is_active or subject.is_simulation:
        raise hr_access.HrAccessError("employee_not_found")
    subject_user = await session.get(User, subject.user_id)
    if subject_user is None:
        raise hr_access.HrAccessError("employee_not_found")

    department_name = await _department_name(session, subject.department_id)
    shadow_user = User(
        telegram_id=await _unique_fake_telegram_id(session),
        display_name=subject_user.display_name,
        username=None,
        color_hex=subject_user.color_hex,
        timezone=subject_user.timezone,
    )
    session.add(shadow_user)
    await session.flush()

    as_is = mode == SIM_MODE_AS_IS
    shadow = Employee(
        user_id=shadow_user.id,
        department_id=subject.department_id if as_is else None,
        position=subject.position if as_is else None,
        badge=subject.badge if as_is else None,
        badge_emoji=subject.badge_emoji if as_is else None,
        role=subject.role,
        experience=subject.experience if as_is else None,
        onboarding_state=subject.onboarding_state if as_is else "new",
        is_active=True,
        is_simulation=True,
    )
    session.add(shadow)
    await session.flush()

    row = SimulationSession(
        actor_employee_id=int(actor.id),
        subject_employee_id=int(subject.id),
        shadow_employee_id=int(shadow.id),
        subject_name=subject_user.display_name,
        subject_department_name=department_name,
        mode=mode,
        status=SIM_ACTIVE,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    log.info(
        "hr.simulation_started",
        session_id=int(row.id),
        actor=int(actor.id),
        subject=int(subject.id),
        mode=mode,
    )
    return SimulationStart(
        session_id=int(row.id),
        shadow_employee_id=int(shadow.id),
        subject_employee_id=int(subject.id),
        subject_name=subject_user.display_name,
        department_name=department_name,
        mode=mode,
        started_at=row.started_at,
    )


async def resolve(session: AsyncSession, *, user: User, session_id: int) -> SimulationContext:
    """Проверить сеанс и вернуть теневого сотрудника для запроса."""
    actor = await hr_access.ensure_employee(session, user)
    row = await session.get(SimulationSession, session_id)
    if row is None or row.actor_employee_id != int(actor.id):
        # Чужой сеанс не подтверждаем: для клиента это «не найдено».
        raise hr_access.HrAccessError("simulation_not_found")
    if row.status != SIM_ACTIVE:
        raise hr_access.HrAccessError("simulation_inactive")
    if not (hr_access.is_admin(actor) or hr_access.is_staff(actor, user)):
        raise hr_access.HrAccessError("admin_required")
    shadow = (
        await session.get(Employee, row.shadow_employee_id)
        if row.shadow_employee_id
        else None
    )
    if shadow is None or not shadow.is_active or not shadow.is_simulation:
        raise hr_access.HrAccessError("simulation_inactive")
    return SimulationContext(
        session_id=int(row.id),
        shadow=shadow,
        subject_name=row.subject_name or shadow.badge or "Сотрудник",
        department_name=row.subject_department_name,
        mode=row.mode,
    )


def self_only_error() -> hr_access.HrAccessError:
    """В режиме проверки нельзя трогать чужих людей и общий журнал."""
    return hr_access.HrAccessError("simulation_self_only")


async def _cleanup(session: AsyncSession, row: SimulationSession) -> CleanupResult:
    """Удалить всё, что создал сеанс. Идемпотентно: остатки прошлой попытки тоже."""
    shadow_id = row.shadow_employee_id
    if shadow_id is None:
        return CleanupResult()
    shadow = await session.get(Employee, shadow_id)
    shadow_user_id = int(shadow.user_id) if shadow is not None else None

    task_ids = [
        int(v)
        for v in (
            await session.scalars(
                select(Task.id).where(
                    or_(
                        Task.assignee_employee_id == shadow_id,
                        Task.created_by_employee_id == shadow_id,
                    )
                )
            )
        ).all()
    ]
    issue_count = int(
        await session.scalar(
            select(func.count())
            .select_from(Issue)
            .where(
                or_(
                    Issue.created_by_employee_id == shadow_id,
                    Issue.assignee_employee_id == shadow_id,
                )
            )
        )
        or 0
    )
    run_count = int(
        await session.scalar(
            select(func.count())
            .select_from(ChecklistRun)
            .where(ChecklistRun.employee_id == shadow_id)
        )
        or 0
    )

    if task_ids:
        await session.execute(delete(Task).where(Task.id.in_(task_ids)))
    await session.execute(
        delete(Issue).where(
            or_(
                Issue.created_by_employee_id == shadow_id,
                Issue.assignee_employee_id == shadow_id,
            )
        )
    )
    await session.execute(
        delete(ChecklistRun).where(ChecklistRun.employee_id == shadow_id)
    )
    await session.execute(
        delete(FeedbackAnswer).where(FeedbackAnswer.employee_id == shadow_id)
    )
    await session.execute(
        delete(TaskAssignment).where(TaskAssignment.employee_id == shadow_id)
    )
    # Передачу смены из сеанса не отправляют, но остатки прошлых версий
    # убираем: связанная с тенью карточка не должна пережить выход.
    await session.execute(
        delete(Handover).where(
            or_(
                Handover.from_employee_id == shadow_id,
                Handover.to_employee_id == shadow_id,
                Handover.accepted_by_employee_id == shadow_id,
            )
        )
    )
    if shadow_user_id is not None:
        await session.execute(
            delete(AppNotification).where(AppNotification.user_id == shadow_user_id)
        )
    await session.execute(delete(Employee).where(Employee.id == shadow_id))
    if shadow_user_id is not None:
        await session.execute(delete(User).where(User.id == shadow_user_id))
    return CleanupResult(
        tasks=len(task_ids), runs=run_count, issues=issue_count
    )


async def finish(
    session: AsyncSession, *, user: User, session_id: int
) -> CleanupResult:
    """Выйти из режима: удалить тестовые данные и закрыть сеанс.

    Если очистка упала — сеанс помечается `failed`, наружу уходит ошибка, и
    приложение НЕ должно возвращаться в обычный режим: иначе тестовые записи
    остались бы в реальной истории. Повторный вызов повторяет очистку.
    """
    actor = await hr_access.ensure_employee(session, user)
    row = await session.get(SimulationSession, session_id)
    if row is None or row.actor_employee_id != int(actor.id):
        raise hr_access.HrAccessError("simulation_not_found")
    if row.status == SIM_ENDED:
        return CleanupResult(
            tasks=int(row.tasks_cleaned or 0),
            runs=int(row.runs_cleaned or 0),
            issues=int(row.issues_cleaned or 0),
            already_ended=True,
        )

    try:
        result = await _cleanup(session, row)
        row.status = SIM_ENDED
        row.ended_at = datetime.now(UTC)
        row.cleanup_error = None
        row.tasks_cleaned = result.tasks
        row.runs_cleaned = result.runs
        row.issues_cleaned = result.issues
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — состояние важнее трейса
        await session.rollback()
        failed = await session.get(SimulationSession, session_id)
        if failed is not None:
            failed.status = SIM_FAILED
            failed.cleanup_error = str(exc)[:500]
            await session.commit()
        log.error("hr.simulation_cleanup_failed", session_id=session_id, error=str(exc))
        raise hr_access.HrAccessError("simulation_cleanup_failed") from exc

    log.info(
        "hr.simulation_finished",
        session_id=session_id,
        tasks=result.tasks,
        runs=result.runs,
        issues=result.issues,
    )
    return result


__all__ = [
    "CleanupResult",
    "SimulationContext",
    "SimulationStart",
    "activate",
    "current",
    "current_session_id",
    "deactivate",
    "finish",
    "hidden_employee_ids",
    "resolve",
    "self_only_error",
    "start",
]
