"""Расписание обучения новичков: учебные и обычные смены + ставка.

Отдельный подраздел админки, потому что это не «правка сотрудника на бегу»:
управляющий садится и раскладывает первые смены новичка — где ещё учимся
вместе, а где человек уже работает сам. Рядом ставка (полная/частичная):
раньше её приходилось держать в голове или в чате.

Права: `AupDep` — как у пула сотрудников. Руководитель подразделения видит и
правит только своих, администратор — всех.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import AupDep, SessionDep
from app.services import hr_admin_ops, hr_training_plan

router = APIRouter(tags=["hr-training-plan"])


class PlanDayOut(BaseModel):
    day: date
    is_training: bool
    explicit: bool
    # Статус смены в табеле (`None` — смены нет).
    shift_status: str | None = None


class EmployeePlanOut(BaseModel):
    employee_id: int
    user_id: int
    display_name: str
    position: str | None
    department_name: str | None
    role: str
    onboarding_state: str
    learning_mode: bool
    rate_type: str
    training_days: int
    hire_date: date | None
    # В табеле есть смены: учебные считаются по факту.
    has_shifts: bool
    days: list[PlanDayOut]


class TrainingPlanOut(BaseModel):
    start: date
    days: int
    rate_labels: dict[str, str]
    items: list[EmployeePlanOut]


class PlanPatchIn(BaseModel):
    rate_type: str | None = Field(None, pattern="^(full|partial)$")
    training_days: int | None = Field(None, ge=0, le=hr_training_plan.MAX_TRAINING_DAYS)


class PlanDayIn(BaseModel):
    is_training: bool


class DayClearedOut(BaseModel):
    cleared: bool


def _plan_error(exc: Exception) -> HTTPException:
    code = str(exc)
    if code == "employee_not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=code)
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=code)


def _plan_out(plan: hr_training_plan.EmployeePlan) -> EmployeePlanOut:
    return EmployeePlanOut(
        employee_id=plan.employee_id,
        user_id=plan.user_id,
        display_name=plan.display_name,
        position=plan.position,
        department_name=plan.department_name,
        role=plan.role,
        onboarding_state=plan.onboarding_state,
        learning_mode=plan.learning_mode,
        rate_type=plan.rate_type,
        training_days=plan.training_days,
        hire_date=plan.hire_date,
        has_shifts=plan.has_shifts,
        days=[
            PlanDayOut(
                day=item.day,
                is_training=item.is_training,
                explicit=item.explicit,
                shift_status=item.shift_status,
            )
            for item in plan.days
        ],
    )


@router.get("/training-plan", response_model=TrainingPlanOut)
async def training_plan(
    session: SessionDep,
    employee: AupDep,
    days: int = Query(
        hr_training_plan.DEFAULT_HORIZON_DAYS, ge=1, le=hr_training_plan.MAX_HORIZON_DAYS
    ),
) -> TrainingPlanOut:
    """Планы всех сотрудников в области видимости, новички — первыми."""
    start = hr_training_plan.today()
    items = await hr_training_plan.plans(session, employee, days=days, start=start)
    return TrainingPlanOut(
        start=start,
        days=hr_training_plan.clamp_horizon(days),
        rate_labels=hr_training_plan.RATE_LABELS,
        items=[_plan_out(item) for item in items],
    )


@router.patch("/training-plan/{employee_id}", response_model=EmployeePlanOut)
async def patch_training_plan(
    employee_id: int,
    body: PlanPatchIn,
    session: SessionDep,
    employee: AupDep,
) -> EmployeePlanOut:
    """Ставка и число первых учебных смен. Точки по дням меняются отдельно."""
    try:
        plan = await hr_training_plan.update_plan(
            session,
            employee,
            employee_id,
            rate_type=body.rate_type,
            training_days=body.training_days,
        )
    except (hr_training_plan.PlanError, hr_admin_ops.AdminOpsError) as exc:
        raise _plan_error(exc) from exc
    return _plan_out(plan)


@router.put("/training-plan/{employee_id}/days/{day}", response_model=PlanDayOut)
async def set_training_day(
    employee_id: int,
    day: date,
    body: PlanDayIn,
    session: SessionDep,
    employee: AupDep,
) -> PlanDayOut:
    """Сделать конкретную смену учебной или обычной."""
    try:
        item = await hr_training_plan.set_day(
            session, employee, employee_id, day, is_training=body.is_training
        )
    except (hr_training_plan.PlanError, hr_admin_ops.AdminOpsError) as exc:
        raise _plan_error(exc) from exc
    return PlanDayOut(day=item.day, is_training=item.is_training, explicit=item.explicit)


@router.delete(
    "/training-plan/{employee_id}/days/{day}", response_model=DayClearedOut
)
async def clear_training_day(
    employee_id: int,
    day: date,
    session: SessionDep,
    employee: AupDep,
) -> DayClearedOut:
    """Убрать ручное правило и вернуть расчёт «первые N смен»."""
    try:
        await hr_training_plan.clear_day(session, employee, employee_id, day)
    except (hr_training_plan.PlanError, hr_admin_ops.AdminOpsError) as exc:
        raise _plan_error(exc) from exc
    return DayClearedOut(cleared=True)


__all__ = ["router"]
