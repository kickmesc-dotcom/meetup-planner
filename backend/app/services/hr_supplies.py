"""Расходники: остаток и движения.

Задача сервиса — сделать недостачу видимой до конца месяца, а не после него.
Для этого нужны три вещи, и ничего сверх:

1. **Позиция с остатком.** Одно число, которое видно всем.
2. **Движение с автором.** Кто взял, сколько и когда — это единственный ответ
   на спор «я не брал».
3. **Порог «мало».** Не автозаказ: система не знает поставщика и сроки, а
   ложная тревога быстро приучает игнорировать плашку.

Границы, которые здесь осознанны:

* Остаток не может уйти в минус. Списание больше остатка — отказ, а не
  «потом разберёмся»: отрицательный остаток делает все цифры бессмысленными.
* Приход делает руководитель (`AupDep` в роуте), списание — любой сотрудник.
  Именно он физически берёт расходник, и лишний экран вернул бы «сказал вслух».
* Позиции без отдела — общие для всей организации. Это нормальный случай
  (салфетки на всё заведение), а не ошибка данных.

Чего здесь нет и почему: партий, поставщиков, цен и сроков годности. Это
складская система, у неё свой учёт; полу-копия в боте только запутает.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import SUPPLY_IN, Department, Employee, Supply, SupplyMovement
from app.services import hr_ops, hr_settings

MAX_QUANTITY = Decimal("999999.99")


class SupplyError(Exception):
    """Код ошибки для клиента — как в остальных сервисах."""


@dataclass(frozen=True)
class SupplyRow:
    id: int
    name: str
    unit: str
    quantity: float
    min_quantity: float
    low: bool
    max_out_per_shift: float | None
    department_id: int | None
    department: str | None
    updated_at: datetime


@dataclass(frozen=True)
class MovementRow:
    id: int
    kind: str
    quantity: float
    comment: str | None
    employee_name: str | None
    is_inventory: bool
    created_at: datetime


def _number(value: object) -> Decimal:
    """Дробное из JSON/формы в Decimal с двумя знаками.

    `float` в Decimal напрямую даёт хвосты (`0.1` → `0.1000000000000000055`),
    поэтому идём через строку. Отрицательное и ноль отсекаются здесь же: это
    ошибка ввода, а не повод записать бессмысленное движение.
    """
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SupplyError("quantity_invalid") from exc
    if parsed <= 0:
        raise SupplyError("quantity_positive")
    if parsed > MAX_QUANTITY:
        raise SupplyError("quantity_too_large")
    return parsed.quantize(Decimal("0.01"))


def _non_negative(value: object) -> Decimal:
    """Фактический остаток: ноль допустим, отрицательное — нет."""
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SupplyError("quantity_invalid") from exc
    if parsed < 0:
        raise SupplyError("quantity_positive")
    if parsed > MAX_QUANTITY:
        raise SupplyError("quantity_too_large")
    return parsed.quantize(Decimal("0.01"))


def _visible(viewer: Employee, department_id: int | None) -> bool:
    return (
        hr_ops.viewer_scope(viewer) == "all"
        or department_id is None
        or department_id == viewer.department_id
    )


async def list_supplies(
    session: AsyncSession,
    *,
    viewer: Employee,
    include_inactive: bool = False,
) -> list[SupplyRow]:
    filters = [Supply.org_id == viewer.org_id]
    if not include_inactive:
        filters.append(Supply.is_active.is_(True))
    if hr_ops.viewer_scope(viewer) != "all" and viewer.department_id is not None:
        filters.append(
            or_(
                Supply.department_id.is_(None),
                Supply.department_id == viewer.department_id,
            )
        )
    elif hr_ops.viewer_scope(viewer) != "all":
        # Сотрудник без отдела видит только общие позиции: чужие отделы — нет.
        filters.append(Supply.department_id.is_(None))

    rows = (
        await session.execute(
            select(Supply, Department.name)
            .outerjoin(Department, Department.id == Supply.department_id)
            .where(*filters)
            .order_by(Supply.name, Supply.id)
        )
    ).all()
    return [
        SupplyRow(
            id=int(item.id),
            name=item.name,
            unit=item.unit,
            quantity=float(item.quantity),
            min_quantity=float(item.min_quantity),
            low=item.quantity <= item.min_quantity,
            max_out_per_shift=(
                float(item.max_out_per_shift)
                if item.max_out_per_shift is not None
                else None
            ),
            department_id=item.department_id,
            department=dept,
            updated_at=item.updated_at,
        )
        for item, dept in rows
    ]


async def create_supply(
    session: AsyncSession,
    *,
    viewer: Employee,
    name: str,
    unit: str = "шт",
    quantity: object = 0,
    min_quantity: object = 0,
    max_out_per_shift: object | None = None,
    department_id: int | None = None,
) -> SupplyRow:
    clean_name = name.strip()
    if not clean_name:
        raise SupplyError("name_required")
    if len(clean_name) > 160:
        raise SupplyError("name_too_long")
    start = Decimal("0") if quantity in (None, "", 0) else _number(quantity)
    threshold = Decimal("0") if min_quantity in (None, "", 0) else _number(min_quantity)
    if threshold > MAX_QUANTITY:
        raise SupplyError("quantity_too_large")

    item = Supply(
        org_id=viewer.org_id,
        name=clean_name,
        unit=(unit or "шт").strip()[:16] or "шт",
        quantity=start,
        min_quantity=threshold,
        max_out_per_shift=(
            None if max_out_per_shift in (None, "") else _number(max_out_per_shift)
        ),
        department_id=department_id,
    )
    session.add(item)
    await session.flush()
    if start > 0:
        session.add(
            SupplyMovement(
                org_id=viewer.org_id,
                supply_id=item.id,
                kind=SUPPLY_IN,
                quantity=start,
                comment="Начальный остаток",
                employee_id=viewer.id,
            )
        )
    await session.commit()
    await session.refresh(item)

    dept = None
    if item.department_id is not None:
        dept = await session.get(Department, item.department_id)
    return SupplyRow(
        id=int(item.id),
        name=item.name,
        unit=item.unit,
        quantity=float(item.quantity),
        min_quantity=float(item.min_quantity),
        low=item.quantity <= item.min_quantity,
        max_out_per_shift=(
            float(item.max_out_per_shift) if item.max_out_per_shift is not None else None
        ),
        department_id=item.department_id,
        department=dept.name if dept else None,
        updated_at=item.updated_at,
    )


async def update_supply(
    session: AsyncSession,
    *,
    viewer: Employee,
    supply_id: int,
    name: str | None = None,
    unit: str | None = None,
    min_quantity: object | None = None,
    max_out_per_shift: object | None = None,
    is_active: bool | None = None,
) -> SupplyRow:
    item = await _get(session, viewer, supply_id)
    if name is not None:
        clean = name.strip()
        if not clean:
            raise SupplyError("name_required")
        item.name = clean[:160]
    if unit is not None:
        item.unit = (unit or "шт").strip()[:16] or "шт"
    if min_quantity is not None:
        item.min_quantity = (
            Decimal("0") if min_quantity in ("", 0) else _number(min_quantity)
        )
    if max_out_per_shift is not None:
        item.max_out_per_shift = (
            None if max_out_per_shift in ("", 0) else _number(max_out_per_shift)
        )
    if is_active is not None:
        item.is_active = is_active
    await session.commit()
    await session.refresh(item)
    dept = await session.get(Department, item.department_id) if item.department_id else None
    return SupplyRow(
        id=int(item.id),
        name=item.name,
        unit=item.unit,
        quantity=float(item.quantity),
        min_quantity=float(item.min_quantity),
        low=item.quantity <= item.min_quantity,
        max_out_per_shift=(
            float(item.max_out_per_shift) if item.max_out_per_shift is not None else None
        ),
        department_id=item.department_id,
        department=dept.name if dept else None,
        updated_at=item.updated_at,
    )


@dataclass(frozen=True)
class MoveResult:
    supply: SupplyRow
    movement: MovementRow
    # Стало «мало» именно этим движением: повод для push, но не для каждого
    # списания, иначе плашка «мало» превратится в шум.
    crossed_low: bool


@dataclass(frozen=True)
class CountResult:
    supply: SupplyRow
    delta: float
    movement: MovementRow | None


@dataclass(frozen=True)
class DiscrepancyRow:
    supply_id: int
    supply_name: str
    unit: str
    delta: float
    comment: str | None
    employee_name: str | None
    created_at: datetime


async def _row(session: AsyncSession, item: Supply) -> SupplyRow:
    dept = await session.get(Department, item.department_id) if item.department_id else None
    return SupplyRow(
        id=int(item.id),
        name=item.name,
        unit=item.unit,
        quantity=float(item.quantity),
        min_quantity=float(item.min_quantity),
        low=item.quantity <= item.min_quantity,
        max_out_per_shift=(
            float(item.max_out_per_shift) if item.max_out_per_shift is not None else None
        ),
        department_id=item.department_id,
        department=dept.name if dept else None,
        updated_at=item.updated_at,
    )


async def _used_today(session: AsyncSession, item: Supply) -> Decimal:
    """Сколько уже списали за сегодня по времени заведения.

    Считаем по движениям, а не по счётчику в позиции: иначе после пересчёта
    лимит сбрасывался бы вместе с остатком, и ограничение обходилось бы
    инвентаризацией.
    """
    moment = hr_settings.local_now()
    start = datetime.combine(moment.date(), time.min, tzinfo=moment.tzinfo)
    value = await session.scalar(
        select(func.coalesce(func.sum(SupplyMovement.quantity), 0)).where(
            SupplyMovement.supply_id == item.id,
            SupplyMovement.kind == "out",
            SupplyMovement.is_inventory.is_(False),
            SupplyMovement.created_at >= start,
        )
    )
    return Decimal(str(value or 0))


async def move(
    session: AsyncSession,
    *,
    viewer: Employee,
    supply_id: int,
    kind: str,
    quantity: object,
    comment: str | None = None,
) -> MoveResult:
    if kind not in (SUPPLY_IN, "out"):
        raise SupplyError("kind_invalid")
    item = await _get(session, viewer, supply_id)
    amount = _number(quantity)
    was_low = item.quantity <= item.min_quantity

    if kind == SUPPLY_IN:
        item.quantity = item.quantity + amount
    else:
        if item.quantity < amount:
            raise SupplyError("not_enough")
        if item.max_out_per_shift is not None:
            used = await _used_today(session, item)
            if used + amount > item.max_out_per_shift:
                raise SupplyError("limit_exceeded")
        item.quantity = item.quantity - amount

    movement = SupplyMovement(
        org_id=viewer.org_id,
        supply_id=item.id,
        kind=kind,
        quantity=amount,
        comment=(comment or "").strip()[:300] or None,
        employee_id=viewer.id,
    )
    session.add(movement)
    await session.commit()
    await session.refresh(item)
    await session.refresh(movement)

    crossed_low = (
        not was_low and item.quantity <= item.min_quantity and kind == "out"
    )
    return MoveResult(
        supply=await _row(session, item),
        movement=MovementRow(
            id=int(movement.id),
            kind=movement.kind,
            quantity=float(movement.quantity),
            comment=movement.comment,
            employee_name=None,
            is_inventory=movement.is_inventory,
            created_at=movement.created_at,
        ),
        crossed_low=crossed_low,
    )


async def count_supply(
    session: AsyncSession,
    *,
    viewer: Employee,
    supply_id: int,
    quantity: object,
    comment: str | None = None,
) -> CountResult:
    """Сверка: записать фактический остаток и движение-расхождение.

    Сознательно не отказывает, когда факт больше учёта: недостача и излишек —
    одинаково повод для записи. Отказ был бы только у нуля в позиции, которая
    уже пуста, — это не расхождение, а ничего не произошло.
    """
    item = await _get(session, viewer, supply_id)
    fact = _non_negative(quantity)
    delta = fact - item.quantity
    if delta == 0:
        return CountResult(supply=await _row(session, item), delta=0.0, movement=None)

    kind = SUPPLY_IN if delta > 0 else "out"
    item.quantity = fact
    note = (comment or "").strip()[:250]
    movement = SupplyMovement(
        org_id=viewer.org_id,
        supply_id=item.id,
        kind=kind,
        quantity=abs(delta),
        comment=("Инвентаризация" + (f": {note}" if note else ""))[:300],
        is_inventory=True,
        employee_id=viewer.id,
    )
    session.add(movement)
    await session.commit()
    await session.refresh(item)
    await session.refresh(movement)
    return CountResult(
        supply=await _row(session, item),
        delta=float(delta),
        movement=MovementRow(
            id=int(movement.id),
            kind=movement.kind,
            quantity=float(movement.quantity),
            comment=movement.comment,
            employee_name=None,
            is_inventory=True,
            created_at=movement.created_at,
        ),
    )


async def discrepancies(
    session: AsyncSession, *, viewer: Employee, days: int = 30
) -> list[DiscrepancyRow]:
    """Расхождения по инвентаризациям за период: где учёт разошёлся с фактом."""
    from app.db.models import User

    moment = hr_settings.local_now()
    since = datetime.combine(
        moment.date() - timedelta(days=max(1, min(days, 180)) - 1),
        time.min,
        tzinfo=moment.tzinfo,
    )
    filters = [
        SupplyMovement.org_id == viewer.org_id,
        SupplyMovement.is_inventory.is_(True),
        SupplyMovement.created_at >= since,
    ]
    if hr_ops.viewer_scope(viewer) != "all" and viewer.department_id is not None:
        filters.append(
            or_(
                Supply.department_id.is_(None),
                Supply.department_id == viewer.department_id,
            )
        )
    rows = (
        await session.execute(
            select(SupplyMovement, Supply, User.display_name)
            .join(Supply, Supply.id == SupplyMovement.supply_id)
            .outerjoin(Employee, Employee.id == SupplyMovement.employee_id)
            .outerjoin(User, User.id == Employee.user_id)
            .where(*filters)
            .order_by(SupplyMovement.created_at.desc())
            .limit(100)
        )
    ).all()
    out: list[DiscrepancyRow] = []
    for movement, item, name in rows:
        delta = float(movement.quantity) * (1 if movement.kind == SUPPLY_IN else -1)
        out.append(
            DiscrepancyRow(
                supply_id=int(item.id),
                supply_name=item.name,
                unit=item.unit,
                delta=delta,
                comment=movement.comment,
                employee_name=name,
                created_at=movement.created_at,
            )
        )
    return out


async def history(
    session: AsyncSession, *, viewer: Employee, supply_id: int, limit: int = 50
) -> list[MovementRow]:
    await _get(session, viewer, supply_id)
    from app.db.models import User

    rows = (
        await session.execute(
            select(SupplyMovement, User.display_name)
            .outerjoin(Employee, Employee.id == SupplyMovement.employee_id)
            .outerjoin(User, User.id == Employee.user_id)
            .where(SupplyMovement.supply_id == supply_id)
            .order_by(SupplyMovement.created_at.desc(), SupplyMovement.id.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).all()
    return [
        MovementRow(
            id=int(m.id),
            kind=m.kind,
            quantity=float(m.quantity),
            comment=m.comment,
            employee_name=name,
            is_inventory=m.is_inventory,
            created_at=m.created_at,
        )
        for m, name in rows
    ]


async def _get(session: AsyncSession, viewer: Employee, supply_id: int) -> Supply:
    item = await session.get(Supply, supply_id)
    if item is None or item.org_id != viewer.org_id or not _visible(viewer, item.department_id):
        raise SupplyError("supply_not_found")
    return item


__all__ = [
    "MovementRow",
    "SupplyError",
    "SupplyRow",
    "create_supply",
    "history",
    "list_supplies",
    "move",
    "update_supply",
]
