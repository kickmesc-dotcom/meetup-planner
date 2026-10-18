"""Режим проверки: старт и выход (админ/разработчик).

Ручки нарочно используют НАСТОЯЩИЙ профиль, а не теневой: иначе из режима
проверки нельзя было бы выйти, если проверяемый сотрудник — обычный работник.
Права проверяет сервис (`hr_simulation.start` / `finish`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, SessionDep
from app.db.hr_models import SIM_MODES, Employee
from app.services import hr_access, hr_simulation

router = APIRouter(prefix="/simulation", tags=["simulation"])


async def real_employee(session: SessionDep, user: CurrentUser) -> Employee:
    """Профиль без подмены сеансом проверки (нужен для старта/выхода)."""
    return await hr_access.ensure_employee(session, user)


RealEmployeeDep = Annotated[Employee, Depends(real_employee)]


class SimulationStartIn(BaseModel):
    employee_id: int
    # `new` — пройти путь новичка (онбординг с нуля), `as_is` — как сейчас.
    mode: Literal["new", "as_is"] = "new"


class SimulationStartOut(BaseModel):
    id: int
    shadow_employee_id: int
    subject_employee_id: int
    subject_name: str
    department_name: str | None
    mode: str
    started_at: datetime


class SimulationExitOut(BaseModel):
    tasks: int
    runs: int
    issues: int
    already_ended: bool


class SimulationActiveOut(BaseModel):
    id: int
    subject_name: str
    department_name: str | None
    mode: str
    started_at: datetime


def _error(exc: hr_access.HrAccessError) -> HTTPException:
    code = str(exc)
    if code == "admin_required":
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=code)
    if code == "employee_not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=code)
    if code == "simulation_already_active":
        return HTTPException(status.HTTP_409_CONFLICT, detail=code)
    if code == "simulation_cleanup_failed":
        return HTTPException(status.HTTP_409_CONFLICT, detail=code)
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=code)


@router.post("", response_model=SimulationStartOut, status_code=201)
async def start_simulation(
    body: SimulationStartIn,
    session: SessionDep,
    user: CurrentUser,
    employee: RealEmployeeDep,
) -> SimulationStartOut:
    """Открыть приложение от имени сотрудника в изолированном сеансе."""
    try:
        started = await hr_simulation.start(
            session,
            actor=employee,
            user=user,
            subject_id=body.employee_id,
            mode=body.mode,
        )
    except hr_access.HrAccessError as exc:
        await session.rollback()
        raise _error(exc) from exc
    return SimulationStartOut(
        id=started.session_id,
        shadow_employee_id=started.shadow_employee_id,
        subject_employee_id=started.subject_employee_id,
        subject_name=started.subject_name,
        department_name=started.department_name,
        mode=started.mode,
        started_at=started.started_at,
    )


@router.post("/{session_id}/exit", response_model=SimulationExitOut)
async def exit_simulation(
    session_id: int,
    session: SessionDep,
    user: CurrentUser,
    _: RealEmployeeDep,
) -> SimulationExitOut:
    """Выйти и удалить тестовые данные. Идемпотентно."""
    try:
        result = await hr_simulation.finish(session, user=user, session_id=session_id)
    except hr_access.HrAccessError as exc:
        raise _error(exc) from exc
    return SimulationExitOut(
        tasks=result.tasks,
        runs=result.runs,
        issues=result.issues,
        already_ended=result.already_ended,
    )


@router.get("/active", response_model=SimulationActiveOut | None)
async def active_simulation(
    session: SessionDep, user: CurrentUser, employee: RealEmployeeDep
) -> SimulationActiveOut | None:
    """Есть ли у меня незакрытый сеанс — чтобы восстановить индикатор после перезапуска."""
    from sqlalchemy import select

    from app.db.hr_models import SIM_ACTIVE, SimulationSession

    row = await session.scalar(
        select(SimulationSession).where(
            SimulationSession.actor_employee_id == int(employee.id),
            SimulationSession.status == SIM_ACTIVE,
        )
    )
    if row is None:
        return None
    return SimulationActiveOut(
        id=int(row.id),
        subject_name=row.subject_name or "Сотрудник",
        department_name=row.subject_department_name,
        mode=row.mode,
        started_at=row.started_at,
    )


__all__ = ["SIM_MODES", "router"]
