"""Первая неделя новичка: список стажёров и наставник.

Права те же, что у отчётов и плана обучения (`AupDep`): руководитель отдела
видит своих, администратор — всех. Подмена `department_id` в query ничего не
открывает, потому что сужение делает `hr_reports.resolve_scope` на сервере.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import AupDep, SessionDep
from app.services import hr_mentorship

router = APIRouter(prefix="/mentorship", tags=["mentorship"])


class TraineeOut(BaseModel):
    employee_id: int
    name: str
    position: str | None
    department_id: int | None
    department: str | None
    hired_on: date
    days_in_team: int
    shifts_week: int
    overdue_tasks: int
    last_seen_at: datetime | None
    mentor_employee_id: int | None
    mentor_name: str | None
    at_risk: bool


class TraineesOut(BaseModel):
    window_days: int
    items: list[TraineeOut]


class MentorIn(BaseModel):
    # `None` — снять наставника: это осознанное действие, а не «забыли поле».
    mentor_employee_id: int | None = Field(default=None)


def _error(exc: hr_mentorship.MentorshipError) -> HTTPException:
    code = str(exc)
    if code == "employee_not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=code)
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=code)


def _out(item: hr_mentorship.Trainee) -> TraineeOut:
    return TraineeOut(
        employee_id=item.employee_id,
        name=item.name,
        position=item.position,
        department_id=item.department_id,
        department=item.department,
        hired_on=item.hired_on,
        days_in_team=item.days_in_team,
        shifts_week=item.shifts_week,
        overdue_tasks=item.overdue_tasks,
        last_seen_at=item.last_seen_at,
        mentor_employee_id=item.mentor_employee_id,
        mentor_name=item.mentor_name,
        at_risk=item.at_risk,
    )


@router.get("/trainees", response_model=TraineesOut)
async def trainees(
    session: SessionDep,
    employee: AupDep,
    department_id: int | None = None,
) -> TraineesOut:
    """Новички последних двух недель: смены, просрочки, вход и наставник."""
    items = await hr_mentorship.list_trainees(
        session, viewer=employee, department_id=department_id
    )
    return TraineesOut(
        window_days=hr_mentorship.WINDOW_DAYS,
        items=[_out(item) for item in items],
    )


@router.patch("/trainees/{employee_id}/mentor", response_model=TraineeOut)
async def set_mentor(
    employee_id: int,
    body: MentorIn,
    session: SessionDep,
    employee: AupDep,
) -> TraineeOut:
    """Назначить наставника или снять его (`null`)."""
    try:
        item = await hr_mentorship.assign_mentor(
            session,
            viewer=employee,
            employee_id=employee_id,
            mentor_id=body.mentor_employee_id,
        )
    except hr_mentorship.MentorshipError as exc:
        raise _error(exc) from exc
    return _out(item)


__all__ = ["router"]
