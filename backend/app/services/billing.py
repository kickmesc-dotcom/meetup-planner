"""Тарифы организации: границы «сколько можно» (B2B_PLATFORM_PLAN, 4.1).

Зачем отдельный сервис, а не поле в модели. Тариф — это не только название:
из него следуют лимиты, срок триала и решение «можно ли завести ещё одного
человека». Если бы каждый экран считал это сам, первый же новый экран забыл бы
проверку, и лимит стал бы обещанием в презентации, а не границей в продукте.

Почему каталог в коде, а не таблица. Тарифов четыре, они меняются вместе с
продуктом и ревьюятся в диффе. Каталог в базе понадобится на шаге 4.3, когда
платформа будет править их руками; сейчас таблица дала бы ровно ту же
информацию плюс миграцию на каждую правку цены.

Почему нет цен. Деньги появляются на шаге 4.2 (оплата и счета). Придуманная
цена в интерфейсе хуже её отсутствия: клиент увидит сумму, которой нельзя
заплатить, и решит, что продукт недоделан. Здесь только границы и срок.

Что считается местом. Живой сотрудник (не демо-профиль `[BOT]` и не теневой
профиль режима проверки) и каждое живое приглашение: ссылка уже обещает место,
и выписать двадцать ссылок при лимите десять — это обход лимита, а не забота
о людях. Демо места не занимает: витрина не должна отнимать у клиента
возможность позвать настоящую смену.

Что происходит по окончании триала. Существующие люди продолжают работать,
данные не пропадают; закрывается только рост — новые люди и подразделения.
Отобрать доступ у смены в разгар дня из-за даты в календаре нельзя: это тот
самый продукт, который «сломался сам».
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import Department, Employee
from app.db.org_models import Organization

# Сколько дней даём новой организации до первого платежа. Две недели — это
# ровно один полный цикл «завели людей → прошли смену → увидели отчёт»: за
# меньший срок владелец не успевает дойти до ценности, за больший — забывает,
# что триал идёт.
TRIAL_DAYS = 14


class PlanError(Exception):
    """Отказ по тарифу. Строка — код: перевод живёт на фронте."""


@dataclass(frozen=True)
class Plan:
    code: str
    title: str
    seats: int
    branches: int
    # Триал — не «ещё один тариф», а состояние: он истекает и закрывает рост.
    trial: bool = False


# Порядок — от меньшего к большему: по нему строится список на экране тарифа.
PLANS: dict[str, Plan] = {
    "trial": Plan("trial", "Пробный", seats=10, branches=5, trial=True),
    "start": Plan("start", "Начало", seats=15, branches=5),
    "business": Plan("business", "Бизнес", seats=50, branches=15),
    "network": Plan("network", "Сеть", seats=200, branches=60),
}

DEFAULT_PLAN = "trial"
# Тариф существующих организаций: до шага 4.1 их никто не ограничивал, и
# внезапно истекающий триал у действующего клиента был бы поломкой, а не
# введением тарифов.
LEGACY_PLAN = "business"


@dataclass(frozen=True)
class PlanState:
    """Чем тариф является для конкретной организации прямо сейчас."""

    code: str
    title: str
    seats_limit: int
    seats_used: int
    branches_limit: int
    branches_used: int
    invites_active: int
    trial_ends_at: datetime | None
    trial_days_left: int | None
    trial_expired: bool

    @property
    def seats_left(self) -> int:
        return max(0, self.seats_limit - self.seats_used)

    @property
    def branches_left(self) -> int:
        return max(0, self.branches_limit - self.branches_used)

    @property
    def can_add_people(self) -> bool:
        return not self.trial_expired and self.seats_left > 0

    @property
    def can_add_branches(self) -> bool:
        return not self.trial_expired and self.branches_left > 0


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    """sqlite отдаёт naive-время, Postgres — aware; сравнивать их нельзя."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def plan_for(code: str | None) -> Plan:
    """Неизвестный тариф — не повод падать: считаем пробным."""
    return PLANS.get((code or "").strip().lower(), PLANS[DEFAULT_PLAN])


def trial_deadline(now: datetime | None = None) -> datetime:
    return (now or _now()) + timedelta(days=TRIAL_DAYS)


async def seats_used(session: AsyncSession, org_id: int) -> tuple[int, int]:
    """Сколько мест занято: (живые люди, живые приглашения).

    Демо-профили и теневые профили проверки не считаются: они не работают
    смену и не должны оплачиваться клиентом.
    """
    from app.services import invitations

    people = await session.scalar(
        select(func.count(Employee.id)).where(
            Employee.org_id == org_id,
            Employee.is_demo.is_(False),
            Employee.is_simulation.is_(False),
        )
    )
    active = await invitations.active(session, org_id)
    return int(people or 0), len(active)


async def branches_used(session: AsyncSession, org_id: int) -> int:
    """Активные подразделения. Погашенные лимит не занимают."""
    count = await session.scalar(
        select(func.count(Department.id)).where(
            Department.org_id == org_id,
            Department.is_active.is_(True),
        )
    )
    return int(count or 0)


async def state(session: AsyncSession, org: Organization) -> PlanState:
    """Полная картина тарифа: что включено, сколько занято, сколько осталось."""
    plan = plan_for(org.plan)
    people, invites = await seats_used(session, org.id)
    branches = await branches_used(session, org.id)
    ends = _aware(org.trial_ends_at)
    now = _now()
    expired = bool(plan.trial and ends is not None and ends <= now)
    days_left: int | None = None
    if plan.trial and ends is not None and not expired:
        # Округление вверх: «остался 1 день» в последние часы честнее нуля,
        # который читается как «уже закончился».
        days_left = max(1, math.ceil((ends - now).total_seconds() / 86400))
    return PlanState(
        code=plan.code,
        title=plan.title,
        seats_limit=plan.seats,
        # Приглашение уже обещает место, поэтому показываем его вместе с людьми.
        seats_used=people + invites,
        branches_limit=plan.branches,
        branches_used=branches,
        invites_active=invites,
        trial_ends_at=ends,
        trial_days_left=days_left,
        trial_expired=expired,
    )


def _check_trial(plan: Plan, expires: datetime | None, now: datetime) -> None:
    if plan.trial and expires is not None and expires <= now:
        raise PlanError("trial_expired")


async def ensure_seats(
    session: AsyncSession, org_id: int, *, add: int = 1
) -> None:
    """Проверить, что места есть, до создания человека или приглашения."""
    org = await session.get(Organization, org_id)
    if org is None:
        raise PlanError("org_missing")
    plan = plan_for(org.plan)
    _check_trial(plan, _aware(org.trial_ends_at), _now())
    people, invites = await seats_used(session, org_id)
    if people + invites + max(1, add) > plan.seats:
        raise PlanError("seats_limit")


async def ensure_branches(
    session: AsyncSession, org_id: int, *, add: int = 1
) -> None:
    """Проверить лимит подразделений до создания новых."""
    org = await session.get(Organization, org_id)
    if org is None:
        raise PlanError("org_missing")
    plan = plan_for(org.plan)
    _check_trial(plan, _aware(org.trial_ends_at), _now())
    if await branches_used(session, org_id) + max(1, add) > plan.branches:
        raise PlanError("branches_limit")
