"""Филиалы сети: головная организация и её филиалы (06.11.2026).

Зачем. Сеть салонов — это несколько коллективов с общими правилами, но разными
людьми, графиком и отчётами. Заводить владельцу вторую учётку, чтобы зайти в
соседний филиал, — неправильно: он один человек, и вход у него один.

Почему филиал — отдельная организация. Данные филиала (сотрудники, смены,
чек-листы) обязаны быть отдельными: иначе отчёт одного филиала смешается с
другим, а «уволен в одном — работает в другом» станет невозможно. Поэтому
филиал — полноценный тенант, а сеть — только связь между ними.

Почему выбор организации проверяется на сервере. Заголовок `X-Org-Id` — это
просьба, а не право. `can_switch` разрешает работу в организации, только если
у человека там уже есть профиль сотрудника или он владелец головной
организации сети. Прислать чужой номер бесполезно: сервер ответит 403.

Почему глубина дерева — один. «Филиал филиала» не даёт ничего, кроме
неоднозначных прав: непонятно, чей владелец сильнее. Глубина один покрывает
сеть салонов и остаётся проверяемой.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import Employee, HrShift
from app.db.models import User
from app.db.org_models import INDUSTRIES, Organization
from app.db.tenancy import all_orgs
from app.services import orgs

# Потолок филиалов: без него один владелец мог бы наплодить тысячи организаций
# и обойти лимиты тарифа, который считается по местам, а не по филиалам.
MAX_BRANCHES = 20


class BranchesError(Exception):
    """Отказ по филиалам. Строка — код, перевод живёт на фронте."""


@dataclass(frozen=True)
class TransferResult:
    """Итог перевода: откуда, куда и сколько смен переехало с человеком."""

    employee_id: int
    from_org_id: int
    to_org_id: int
    shifts_moved: int


async def root_of(session: AsyncSession, org: Organization) -> Organization:
    """Головная организация сети (сама организация, если она не филиал)."""
    if org.parent_org_id is None:
        return org
    parent = await session.get(Organization, org.parent_org_id)
    return parent or org


async def can_switch(session: AsyncSession, *, user_id: int, org_id: int) -> bool:
    """Может ли человек работать в этой организации.

    Два законных случая: он там сотрудник (профиль уже есть) или он владелец
    головной организации сети. Второе нужно, чтобы владелец заходил в новый
    филиал до того, как там появился его профиль.
    """
    with all_orgs():
        own = await session.scalar(
            select(Employee.id).where(
                Employee.user_id == user_id, Employee.org_id == org_id
            )
        )
        if own is not None:
            return True
        target = await session.get(Organization, org_id)
        if target is None or not target.is_active or target.deleted_at is not None:
            return False
        root_id = target.parent_org_id or target.id
        member = await orgs.member(session, org_id=root_id, user_id=user_id)
        return member is not None and member.role == "owner"


async def network(
    session: AsyncSession, *, root: Organization, user_id: int
) -> list[tuple[Organization, str]]:
    """Головная и филиалы — с ролью человека в каждой.

    Роль берётся из членства, а не из `employees`: владелец сети остаётся
    владельцем филиала, даже если его профиль сотрудника там ещё не создан.
    """
    rows = await session.scalars(
        select(Organization)
        .where(
            (Organization.id == root.id) | (Organization.parent_org_id == root.id)
        )
        .order_by(Organization.id)
    )
    result: list[tuple[Organization, str]] = []
    for org in rows:
        member = await orgs.member(session, org_id=org.id, user_id=user_id)
        result.append((org, member.role if member is not None else ""))
    return result


async def create_branch(
    session: AsyncSession,
    *,
    root: Organization,
    user: User,
    name: str,
    industry: str | None = None,
) -> Organization:
    """Завести филиал и сделать владельца его владельцем.

    Отрасль по умолчанию наследуется от головной: филиал салона — салон.
    """
    if root.parent_org_id is not None:
        raise BranchesError("branch_of_branch")
    clean = (name or "").strip()
    if len(clean) < 2:
        raise BranchesError("bad_name")
    count = await session.scalar(
        select(func.count(Organization.id)).where(
            Organization.parent_org_id == root.id
        )
    )
    if (count or 0) >= MAX_BRANCHES:
        raise BranchesError("branch_limit")

    clean_industry = industry or root.industry
    if clean_industry not in INDUSTRIES:
        clean_industry = root.industry

    base = orgs.slug_from_name(clean)
    branch: Organization | None = None
    for attempt in range(1, 50):
        slug = base if attempt == 1 else f"{base}-{attempt}"
        try:
            branch = await orgs.create_org(
                session, slug=slug, name=clean, industry=clean_industry
            )
            break
        except orgs.OrgsError as exc:
            if str(exc) != "slug_taken":
                raise BranchesError(str(exc)) from exc
    if branch is None:
        raise BranchesError("slug_taken")

    branch.parent_org_id = root.id
    await session.commit()
    await session.refresh(branch)

    # Членство — сразу: владелец должен увидеть филиал в переключателе, не
    # дожидаясь первого входа. Профиль сотрудника создастся лениво, когда он
    # действительно переключится (`ensure_employee`).
    await orgs.add_member(session, org_id=branch.id, user_id=user.id, role="owner")
    return branch


async def employees_for_transfer(
    session: AsyncSession, *, org: Organization
) -> list[tuple[Employee, str]]:
    """Кто может переехать: активные люди этой организации, без демо и теней."""
    rows = await session.execute(
        select(Employee, User.display_name)
        .join(User, User.id == Employee.user_id)
        .where(
            Employee.org_id == org.id,
            Employee.is_active.is_(True),
            Employee.fired_at.is_(None),
            Employee.is_demo.is_(False),
            Employee.is_simulation.is_(False),
        )
        .order_by(User.display_name)
    )
    return [(employee, name) for employee, name in rows.all()]


async def transfer_employee(
    session: AsyncSession,
    *,
    root: Organization,
    source_org: Organization,
    target_org: Organization,
    employee_id: int,
    actor: User,
    move_shifts: bool = True,
) -> TransferResult:
    """Перевести человека в другой филиал сети.

    Почему создаётся новый профиль, а не двигается `employees.org_id`. Прошлые
    смены — часть отчётов прежнего филиала: выручка и дисциплина считаются там,
    где человек работал. Перенос строки утащил бы всю его историю в чужой
    отчёт. Поэтому старый профиль остаётся (неактивным) со своей историей, а в
    новом филиале появляется его профиль с теми же должностью и ставкой.

    Будущие смены переезжают вместе с человеком: иначе он вышел бы на смену,
    которой нет в графике нового филиала. Смены до сегодня остаются на месте.

    Себя переводить нельзя: владелец сети и так заходит в любой филиал, а
    случайный перевод лишил бы его профиля в головной.
    """
    if target_org.id == source_org.id:
        raise BranchesError("same_org")
    if target_org.id != root.id and target_org.parent_org_id != root.id:
        raise BranchesError("org_not_in_network")
    if not target_org.is_active or target_org.deleted_at is not None:
        raise BranchesError("org_inactive")

    employee = await session.get(Employee, int(employee_id))
    if employee is None or employee.org_id != source_org.id:
        raise BranchesError("employee_not_found")
    if employee.user_id == actor.id:
        raise BranchesError("transfer_self")
    if employee.is_demo or employee.is_simulation:
        raise BranchesError("transfer_demo")

    with all_orgs():
        existing = await session.scalar(
            select(Employee.id).where(
                Employee.org_id == target_org.id,
                Employee.user_id == employee.user_id,
            )
        )
    if existing is not None:
        raise BranchesError("already_in_branch")

    shadow = Employee(
        user_id=employee.user_id,
        org_id=target_org.id,
        role=employee.role,
        position=employee.position,
        badge=employee.badge,
        badge_emoji=employee.badge_emoji,
        experience=employee.experience,
        rate_type=employee.rate_type,
        training_days=employee.training_days,
        hire_date=employee.hire_date,
        # Отдел принадлежит филиалу: чужой `department_id` показал бы человека
        # в подразделении, которого в новой организации нет.
        department_id=None,
    )
    session.add(shadow)
    await session.flush()

    moved = 0
    if move_shifts:
        result = await session.execute(
            update(HrShift)
            .where(
                HrShift.employee_id == employee.id,
                HrShift.day >= date.today(),
            )
            .values(employee_id=shadow.id, org_id=target_org.id)
        )
        moved = result.rowcount or 0

    employee.is_active = False
    await session.commit()
    await session.refresh(shadow)
    return TransferResult(
        employee_id=shadow.id,
        from_org_id=source_org.id,
        to_org_id=target_org.id,
        shifts_moved=moved,
    )
