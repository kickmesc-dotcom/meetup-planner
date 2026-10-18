"""REST API передачи смены.

Отдельный роутер по той же причине, что и журнал проблем: у сдачи своя модель
прав и свой жизненный цикл (`sent → accepted / rejected`). Все ручки работают
от подписанного Telegram `initData`; кто сдаёт и кому можно передать, решает
сервер.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, EmployeeDep, SessionDep
from app.db.hr_models import Handover, HandoverItem, Department, Employee
from app.db.models import User
from app.services import hr_handovers, hr_notify

router = APIRouter(tags=["handovers"])


# --------------------------------------------------------------------------
# Схемы
# --------------------------------------------------------------------------


class HandoverItemOut(BaseModel):
    id: int
    kind: str
    ref_id: int | None
    title: str
    status: str
    meta: str | None


class HandoverOut(BaseModel):
    id: int
    status: str
    shift_date: date
    note: str | None
    reject_reason: str | None
    department_id: int | None
    department_name: str | None
    from_employee_id: int | None
    from_name: str | None
    to_employee_id: int | None
    to_name: str | None
    accepted_by_employee_id: int | None
    accepted_by_name: str | None
    created_at: datetime
    accepted_at: datetime | None
    items_count: int
    can_accept: bool
    can_reject: bool
    items: list[HandoverItemOut]


class HandoverSummaryOut(BaseModel):
    incoming: int
    outgoing: int
    pending: int


class HandoversOut(BaseModel):
    summary: HandoverSummaryOut
    items: list[HandoverOut]


class HandoverPreviewOut(BaseModel):
    items: list[HandoverItemOut]
    tasks: int
    issues: int


class ColleagueOut(BaseModel):
    id: int
    display_name: str


class HandoverCreateIn(BaseModel):
    to_employee_id: int
    note: str | None = Field(None, max_length=2000)


class HandoverRejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class HandoverAcceptIn(BaseModel):
    note: str | None = Field(None, max_length=2000)


# --------------------------------------------------------------------------
# Хелперы
# --------------------------------------------------------------------------


async def _names(session: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await session.execute(
        select(Employee.id, User.display_name)
        .join(User, User.id == Employee.user_id)
        .where(Employee.id.in_(ids))
    )
    return {int(employee_id): str(name) for employee_id, name in rows.all()}


async def _counts(
    session: AsyncSession, handover_ids: list[int]
) -> dict[int, int]:
    """Сколько пунктов в каждой сдаче — без N+1 на список."""
    if not handover_ids:
        return {}
    rows = await session.execute(
        select(HandoverItem.handover_id, func.count())
        .where(HandoverItem.handover_id.in_(handover_ids))
        .group_by(HandoverItem.handover_id)
    )
    return {int(handover_id): int(count) for handover_id, count in rows.all()}


def _handover_out(
    handover: Handover,
    *,
    viewer: Employee,
    names: dict[int, str],
    departments: dict[int, str],
    items_count: int,
    items: list[HandoverItem] | None = None,
) -> HandoverOut:
    return HandoverOut(
        id=handover.id,
        status=handover.status,
        shift_date=handover.shift_date,
        note=handover.note,
        reject_reason=handover.reject_reason,
        department_id=handover.department_id,
        department_name=departments.get(handover.department_id or -1),
        from_employee_id=handover.from_employee_id,
        from_name=names.get(handover.from_employee_id or -1),
        to_employee_id=handover.to_employee_id,
        to_name=names.get(handover.to_employee_id or -1),
        accepted_by_employee_id=handover.accepted_by_employee_id,
        accepted_by_name=names.get(handover.accepted_by_employee_id or -1),
        created_at=handover.created_at,
        accepted_at=handover.accepted_at,
        items_count=items_count,
        can_accept=hr_handovers.can_accept(viewer, handover),
        can_reject=hr_handovers.can_reject(viewer, handover),
        items=[
            HandoverItemOut(
                id=item.id,
                kind=item.kind,
                ref_id=item.ref_id,
                title=item.title,
                status=item.status,
                meta=item.meta,
            )
            for item in (items or [])
        ],
    )


async def _visible(
    session: AsyncSession, handover_id: int, viewer: Employee
) -> Handover:
    handover = await hr_handovers.get_handover(session, handover_id)
    if handover is None or not hr_handovers.can_view(viewer, handover):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="handover_not_found")
    return handover


async def _detail(
    session: AsyncSession,
    handover: Handover,
    *,
    viewer: Employee,
    names: dict[int, str] | None = None,
    departments: dict[int, str] | None = None,
) -> HandoverOut:
    items = await hr_handovers.items_of(session, handover.id)
    if names is None:
        ids = {
            handover.from_employee_id,
            handover.to_employee_id,
            handover.accepted_by_employee_id,
        }
        names = await _names(session, {i for i in ids if i is not None})
    if departments is None:
        departments = await _departments(
            session, {handover.department_id} if handover.department_id else set()
        )
    return _handover_out(
        handover,
        viewer=viewer,
        names=names,
        departments=departments,
        items_count=len(items),
        items=items,
    )


async def _departments(session: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await session.execute(
        select(Department.id, Department.name).where(Department.id.in_(ids))
    )
    return {int(dep_id): str(name) for dep_id, name in rows.all()}


async def _summary(
    session: AsyncSession, employee: Employee
) -> HandoverSummaryOut:
    incoming = int(
        await session.scalar(
            select(func.count())
            .select_from(Handover)
            .where(
                Handover.to_employee_id == employee.id,
            )
        )
        or 0
    )
    outgoing = int(
        await session.scalar(
            select(func.count())
            .select_from(Handover)
            .where(Handover.from_employee_id == employee.id)
        )
        or 0
    )
    pending = await hr_handovers.pending_count(session, employee)
    return HandoverSummaryOut(incoming=incoming, outgoing=outgoing, pending=pending)


# --------------------------------------------------------------------------
# Ручки
# --------------------------------------------------------------------------


@router.get("/handovers", response_model=HandoversOut)
async def list_handovers(
    session: SessionDep,
    employee: EmployeeDep,
    box: str = Query("all", pattern="^(all|incoming|outgoing)$"),
    limit: int = 50,
) -> HandoversOut:
    rows = await hr_handovers.list_for(session, employee, box=box, limit=limit)
    ids = {h.id for h in rows}
    counts = await _counts(session, list(ids))

    employee_ids: set[int] = set()
    department_ids: set[int] = set()
    for handover in rows:
        employee_ids.update(
            i
            for i in (
                handover.from_employee_id,
                handover.to_employee_id,
                handover.accepted_by_employee_id,
            )
            if i is not None
        )
        if handover.department_id:
            department_ids.add(handover.department_id)
    names = await _names(session, employee_ids)
    departments = await _departments(session, department_ids)

    return HandoversOut(
        summary=await _summary(session, employee),
        items=[
            _handover_out(
                handover,
                viewer=employee,
                names=names,
                departments=departments,
                items_count=counts.get(handover.id, 0),
            )
            for handover in rows
        ],
    )


@router.get("/handovers/summary", response_model=HandoverSummaryOut)
async def handovers_summary(
    session: SessionDep, employee: EmployeeDep
) -> HandoverSummaryOut:
    return await _summary(session, employee)


@router.get("/handovers/colleagues", response_model=list[ColleagueOut])
async def handover_colleagues(
    session: SessionDep, employee: EmployeeDep
) -> list[ColleagueOut]:
    rows = await hr_handovers.colleagues(session, employee)
    return [ColleagueOut(id=eid, display_name=name) for eid, name, _ in rows]


@router.get("/handovers/preview", response_model=HandoverPreviewOut)
async def handover_preview(
    session: SessionDep, employee: EmployeeDep
) -> HandoverPreviewOut:
    """Что уйдёт в сдачу прямо сейчас — до её создания.

    Отдельная ручка, а не сбор на клиенте: правило «что считается хвостом»
    должно быть одно и жить рядом с созданием сдачи.
    """
    snapshots = await hr_handovers.collect_open(session, employee)
    return HandoverPreviewOut(
        items=[
            HandoverItemOut(
                id=index,
                kind=snap.kind,
                ref_id=snap.ref_id,
                title=snap.title,
                status=snap.status,
                meta=snap.meta,
            )
            for index, snap in enumerate(snapshots, start=1)
        ],
        tasks=sum(1 for s in snapshots if s.kind == "task"),
        issues=sum(1 for s in snapshots if s.kind == "issue"),
    )


@router.post("/handovers", response_model=HandoverOut, status_code=201)
async def create_handover(
    body: HandoverCreateIn,
    session: SessionDep,
    user: CurrentUser,
    employee: EmployeeDep,
) -> HandoverOut:
    from app.services import hr_simulation

    if hr_simulation.current() is not None:
        # Передача смены адресована живому коллеге: из сеанса проверки её
        # отправить нельзя, иначе тест разбудил бы реального человека.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="simulation_self_only"
        )
    try:
        handover = await hr_handovers.create_handover(
            session,
            author=employee,
            to_employee_id=body.to_employee_id,
            note=body.note,
        )
    except hr_handovers.HandoverError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    recipient = await session.get(Employee, handover.to_employee_id)
    if recipient is not None:
        items = await hr_handovers.items_of(session, handover.id)
        await hr_notify.notify_handover_sent(
            session,
            handover,
            recipient,
            items=len(items),
            by_name=user.display_name,
        )

    await session.commit()
    await session.refresh(handover)
    return await _detail(session, handover, viewer=employee)


@router.get("/handovers/{handover_id}", response_model=HandoverOut)
async def get_handover_api(
    handover_id: int, session: SessionDep, employee: EmployeeDep
) -> HandoverOut:
    handover = await _visible(session, handover_id, employee)
    return await _detail(session, handover, viewer=employee)


@router.post("/handovers/{handover_id}/accept", response_model=HandoverOut)
async def accept_handover(
    handover_id: int,
    body: HandoverAcceptIn,
    session: SessionDep,
    user: CurrentUser,
    employee: EmployeeDep,
) -> HandoverOut:
    handover = await _visible(session, handover_id, employee)
    try:
        await hr_handovers.accept(
            session, handover, actor=employee, note=body.note
        )
    except hr_handovers.HandoverError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    sender = (
        await session.get(Employee, handover.from_employee_id)
        if handover.from_employee_id
        else None
    )
    if sender is not None:
        await hr_notify.notify_handover_accepted(
            session, handover, sender, by_name=user.display_name
        )

    await session.commit()
    await session.refresh(handover)
    return await _detail(session, handover, viewer=employee)


@router.post("/handovers/{handover_id}/reject", response_model=HandoverOut)
async def reject_handover(
    handover_id: int,
    body: HandoverRejectIn,
    session: SessionDep,
    user: CurrentUser,
    employee: EmployeeDep,
) -> HandoverOut:
    handover = await _visible(session, handover_id, employee)
    try:
        await hr_handovers.reject(
            session, handover, actor=employee, reason=body.reason
        )
    except hr_handovers.HandoverError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    sender = (
        await session.get(Employee, handover.from_employee_id)
        if handover.from_employee_id
        else None
    )
    if sender is not None:
        await hr_notify.notify_handover_rejected(
            session, handover, sender, by_name=user.display_name
        )

    await session.commit()
    await session.refresh(handover)
    return await _detail(session, handover, viewer=employee)
