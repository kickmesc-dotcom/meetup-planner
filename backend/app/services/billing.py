"""Тарифы, лимиты, триал и счета организации (B2B_PLATFORM_PLAN, 4.1–4.2).

Зачем отдельный сервис, а не поле в модели. Тариф — это не только название:
из него следуют лимиты, срок триала, цена и решение «можно ли завести ещё
одного человека». Если бы каждый экран считал это сам, первый же новый экран
забыл бы проверку, и лимит стал бы обещанием в презентации, а не границей в
продукте.

Почему каталог в коде, а не таблица. Тарифов четыре, они меняются вместе с
продуктом и ревьюятся в диффе. Каталог в базе понадобится на шаге 4.3, когда
платформа будет править их руками; сейчас таблица дала бы ровно ту же
информацию плюс миграцию на каждую правку цены.

Почему цена здесь, а оплата — счётом. Платёжного провайдера подключает владелец
(нужны ключи мерчанта), и до этого продукт не должен врать кнопкой «Оплатить»,
которая ничего не делает. Счёт — документ, который существует независимо от
провайдера: номер, тариф, период, сумма, срок действия. Когда провайдер
появится, он будет закрывать те же счета, и история платежей не переедет.

Что считается местом. Живой сотрудник (не демо-профиль `[BOT]` и не теневой
профиль режима проверки) и каждое живое приглашение: ссылка уже обещает место,
и выписать двадцать ссылок при лимите десять — это обход лимита, а не забота
о людях. Демо места не занимает: витрина не должна отнимать у клиента
возможность позвать настоящую смену.

Что происходит по окончании триала или оплаченного срока. Существующие люди
продолжают работать, данные не пропадают; закрывается только рост — новые люди
и подразделения. Отобрать доступ у смены в разгар дня из-за даты в календаре
нельзя: это тот самый продукт, который «сломался сам».

Что делает оплата. Погашенный счёт продлевает срок подписки и ставит тариф из
счёта. Два оплаченных месяца подряд складываются, а не перезаписывают друг
друга: клиент, заплативший вперёд, не должен терять уже оплаченное время.
"""

from __future__ import annotations

import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import Department, Employee
from app.db.org_models import Organization, OrgInvoice

# Сколько дней даём новой организации до первого платежа. Две недели — это
# ровно один полный цикл «завели людей → прошли смену → увидели отчёт»: за
# меньший срок владелец не успевает дойти до ценности, за больший — забывает,
# что триал идёт.
TRIAL_DAYS = 14

# Сколько живёт выставленный счёт. Неделя — это срок, за который платёж по
# реквизитам реально доходит; бессрочный счёт через полгода «оплатили» бы по
# старой цене, и каталог разошёлся бы с деньгами.
INVOICE_TTL_DAYS = 7

# Периоды подписки в днях, а не в «месяцах»: 30 дней не ломаются на феврале.
# Год — 365, а не 12×30=360: иначе годовой тариф тихо укорачивал бы подписку.
PERIODS: dict[str, int] = {"month": 30, "year": 365}

PERIOD_TITLES: dict[str, str] = {"month": "Месяц", "year": "Год"}


class PlanError(Exception):
    """Отказ по тарифу. Строка — код: перевод живёт на фронте."""


class InvoiceError(Exception):
    """Отказ по счёту. Строка — код: перевод живёт на фронте."""


@dataclass(frozen=True)
class Plan:
    code: str
    title: str
    seats: int
    branches: int
    # Цена в целых рублях за период. Ноль у пробного: он не продаётся.
    price_month: int = 0
    price_year: int = 0
    # Триал — не «ещё один тариф», а состояние: он истекает и закрывает рост.
    trial: bool = False


# Порядок — от меньшего к большему: по нему строится список на экране тарифа.
#
# Цены — предложение владельцу, а не согласованный прайс: они живут одной
# таблицей именно для того, чтобы правка была в одном месте и в диффе. Год
# стоит десять месяцев: скидка за предоплату, а не «12 по цене 12».
PLANS: dict[str, Plan] = {
    "trial": Plan("trial", "Пробный", seats=10, branches=5, trial=True),
    "start": Plan("start", "Начало", seats=15, branches=5, price_month=2900, price_year=29_000),
    "business": Plan(
        "business", "Бизнес", seats=50, branches=15, price_month=7900, price_year=79_000
    ),
    "network": Plan(
        "network", "Сеть", seats=200, branches=60, price_month=19_900, price_year=199_000
    ),
}

DEFAULT_PLAN = "trial"
# Тариф существующих организаций: до шага 4.1 их никто не ограничивал, и
# внезапно истекающий триал у действующего клиента был бы поломкой, а не
# введением тарифов.
LEGACY_PLAN = "business"

# Статусы счёта. `expired` не хранится: это `pending` с прошедшим сроком, и
# хранить его значило бы держать фоновую задачу, которая переводит строки.
INVOICE_PENDING = "pending"
INVOICE_AWAITING = "awaiting"
INVOICE_PAID = "paid"
INVOICE_CANCELED = "canceled"
INVOICE_EXPIRED = "expired"

_PAYABLE = (INVOICE_PENDING, INVOICE_AWAITING)


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
    # Срок оплаченной подписки (шаг 4.2). Пусто у триала и у старых
    # организаций с «Бизнесом» без срока: у них подписка бессрочная.
    plan_ends_at: datetime | None = None
    plan_days_left: int | None = None
    subscription_expired: bool = False

    @property
    def seats_left(self) -> int:
        return max(0, self.seats_limit - self.seats_used)

    @property
    def branches_left(self) -> int:
        return max(0, self.branches_limit - self.branches_used)

    @property
    def can_add_people(self) -> bool:
        return not self.trial_expired and not self.subscription_expired and self.seats_left > 0

    @property
    def can_add_branches(self) -> bool:
        return (
            not self.trial_expired
            and not self.subscription_expired
            and self.branches_left > 0
        )


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


def payable_plans() -> list[Plan]:
    """Тарифы, которые можно купить. Пробный в витрину не попадает."""
    return [plan for plan in PLANS.values() if not plan.trial]


def price_for(code: str, period: str) -> int:
    """Цена тарифа за период. `InvoiceError`, если продать нельзя."""
    plan = PLANS.get((code or "").strip().lower())
    if plan is None:
        raise InvoiceError("bad_plan")
    if plan.trial:
        raise InvoiceError("plan_not_payable")
    if period not in PERIODS:
        raise InvoiceError("bad_period")
    return plan.price_year if period == "year" else plan.price_month


def trial_deadline(now: datetime | None = None) -> datetime:
    return (now or _now()) + timedelta(days=TRIAL_DAYS)


def _days_left(until: datetime | None, now: datetime) -> int | None:
    """Сколько суток осталось, с округлением вверх.

    Вверх, а не вниз: «остался 1 день» в последние часы честнее нуля, который
    читается как «уже закончился».
    """
    if until is None:
        return None
    return max(1, math.ceil((until - now).total_seconds() / 86400))


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
    now = _now()
    ends = _aware(org.trial_ends_at)
    paid_until = _aware(org.plan_ends_at)
    expired = bool(plan.trial and ends is not None and ends <= now)
    # Платная подписка истекает только если срок вообще был: у старых
    # организаций его нет, и «бессрочно» — это не «истекло вчера».
    subscription_expired = bool(paid_until is not None and paid_until <= now)
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
        trial_days_left=_days_left(ends, now) if plan.trial and not expired else None,
        trial_expired=expired,
        plan_ends_at=paid_until,
        plan_days_left=(
            _days_left(paid_until, now)
            if paid_until is not None and not subscription_expired
            else None
        ),
        subscription_expired=subscription_expired,
    )


def _check_entitlement(
    plan: Plan,
    trial_ends: datetime | None,
    paid_until: datetime | None,
    now: datetime,
) -> None:
    """Рост закрыт: либо кончился триал, либо кончилась оплата."""
    if plan.trial and trial_ends is not None and trial_ends <= now:
        raise PlanError("trial_expired")
    if paid_until is not None and paid_until <= now:
        raise PlanError("subscription_expired")


async def ensure_seats(session: AsyncSession, org_id: int, *, add: int = 1) -> None:
    """Проверить, что места есть, до создания человека или приглашения."""
    org = await session.get(Organization, org_id)
    if org is None:
        raise PlanError("org_missing")
    plan = plan_for(org.plan)
    _check_entitlement(
        plan, _aware(org.trial_ends_at), _aware(org.plan_ends_at), _now()
    )
    people, invites = await seats_used(session, org_id)
    if people + invites + max(1, add) > plan.seats:
        raise PlanError("seats_limit")


async def ensure_branches(session: AsyncSession, org_id: int, *, add: int = 1) -> None:
    """Проверить лимит подразделений до создания новых."""
    org = await session.get(Organization, org_id)
    if org is None:
        raise PlanError("org_missing")
    plan = plan_for(org.plan)
    _check_entitlement(
        plan, _aware(org.trial_ends_at), _aware(org.plan_ends_at), _now()
    )
    if await branches_used(session, org_id) + max(1, add) > plan.branches:
        raise PlanError("branches_limit")


def invoice_status(invoice: OrgInvoice, now: datetime | None = None) -> str:
    """Статус счёта с учётом срока: `pending` просроченный — это `expired`."""
    if invoice.status == INVOICE_PENDING:
        expires = _aware(invoice.expires_at)
        if expires is not None and expires <= (now or _now()):
            return INVOICE_EXPIRED
    return invoice.status


def _number(now: datetime) -> str:
    """Номер счёта: дата + случайный хвост.

    Не последовательный счётчик: он требует блокировки строки на каждый счёт и
    выдаёт чужому клиенту, сколько счетов выписано до него. Уникальность
    держит ограничение в базе.
    """
    return f"INV-{now:%Y%m%d}-{secrets.token_hex(3).upper()}"


async def _open_same(
    session: AsyncSession, org_id: int, plan: str, period: str, now: datetime
) -> OrgInvoice | None:
    rows = await session.scalars(
        select(OrgInvoice).where(
            OrgInvoice.org_id == org_id,
            OrgInvoice.plan == plan,
            OrgInvoice.period == period,
            OrgInvoice.status.in_(list(_PAYABLE)),
        )
    )
    for row in rows:
        if invoice_status(row, now) != INVOICE_EXPIRED:
            return row
    return None


async def create_invoice(
    session: AsyncSession,
    org: Organization,
    *,
    plan_code: str,
    period: str,
    created_by_id: int | None = None,
    now: datetime | None = None,
) -> OrgInvoice:
    """Выставить счёт на тариф и период.

    Повторный клик по той же кнопке возвращает уже выставленный счёт, а не
    второй с тем же смыслом: два одинаковых документа в бухгалтерии клиента
    выглядят как двойное списание, даже когда денег никто не брал.
    """
    moment = now or _now()
    amount = price_for(plan_code, period)
    plan = PLANS[plan_code.strip().lower()]
    existing = await _open_same(session, org.id, plan.code, period, moment)
    if existing is not None:
        return existing
    invoice = OrgInvoice(
        org_id=org.id,
        number=_number(moment),
        plan=plan.code,
        period=period,
        amount=amount,
        currency="RUB",
        status=INVOICE_PENDING,
        expires_at=moment + timedelta(days=INVOICE_TTL_DAYS),
        created_by_user_id=created_by_id,
    )
    session.add(invoice)
    await session.commit()
    await session.refresh(invoice)
    return invoice


async def list_invoices(
    session: AsyncSession, org_id: int, *, limit: int = 20
) -> list[OrgInvoice]:
    """История счетов: свежие сверху — именно её ищет владелец."""
    rows = await session.scalars(
        select(OrgInvoice)
        .where(OrgInvoice.org_id == org_id)
        .order_by(OrgInvoice.created_at.desc(), OrgInvoice.id.desc())
        .limit(limit)
    )
    return list(rows)


async def get_invoice(
    session: AsyncSession, org_id: int, invoice_id: int
) -> OrgInvoice:
    invoice = await session.get(OrgInvoice, invoice_id)
    # Чужой счёт неотличим от несуществующего: id — не пропуск в другой тенант.
    if invoice is None or invoice.org_id != org_id:
        raise InvoiceError("invoice_not_found")
    return invoice


async def request_payment(
    session: AsyncSession,
    org_id: int,
    invoice_id: int,
    *,
    now: datetime | None = None,
) -> OrgInvoice:
    """Владелец нажал «я оплатил».

    Это не продление: подтверждение приходит от платформы. Иначе кнопка
    «оплатил» стала бы бесплатным безлимитом, и подписка продлевалась бы
    одним кликом без денег.
    """
    invoice = await get_invoice(session, org_id, invoice_id)
    status = invoice_status(invoice, now)
    if status == INVOICE_EXPIRED:
        raise InvoiceError("invoice_expired")
    if status not in _PAYABLE:
        raise InvoiceError("invoice_not_payable")
    invoice.status = INVOICE_AWAITING
    await session.commit()
    await session.refresh(invoice)
    return invoice


async def cancel_invoice(
    session: AsyncSession, org_id: int, invoice_id: int, *, now: datetime | None = None
) -> OrgInvoice:
    """Отменить неоплаченный счёт. Оплаченный не отменяется — это деньги."""
    invoice = await get_invoice(session, org_id, invoice_id)
    status = invoice_status(invoice, now)
    if status == INVOICE_EXPIRED:
        raise InvoiceError("invoice_expired")
    if status not in _PAYABLE:
        raise InvoiceError("invoice_not_cancelable")
    invoice.status = INVOICE_CANCELED
    await session.commit()
    await session.refresh(invoice)
    return invoice


async def mark_paid(
    session: AsyncSession,
    org: Organization,
    invoice: OrgInvoice,
    *,
    now: datetime | None = None,
) -> OrgInvoice:
    """Подтвердить оплату и продлить подписку.

    Вызывается платформой (админка — шаг 4.3) или платёжным провайдером, когда
    он появится. Внутри — единственное место, где меняются тариф и срок:
    вызывать его из ручки организации нельзя (см. `request_payment`).
    """
    moment = now or _now()
    if invoice.status not in _PAYABLE:
        raise InvoiceError("invoice_not_payable")
    if invoice.org_id != org.id:
        raise InvoiceError("invoice_not_found")
    # Продление считается от более позднего из «сейчас» и уже оплаченного
    # срока: заплативший вперёд не теряет оплаченные дни.
    current = _aware(org.plan_ends_at)
    start = moment if current is None or current <= moment else current
    end = start + timedelta(days=PERIODS.get(invoice.period, PERIODS["month"]))
    invoice.status = INVOICE_PAID
    invoice.paid_at = moment
    invoice.period_start = start
    invoice.period_end = end
    org.plan = invoice.plan
    org.plan_ends_at = end
    # Оплаченный тариф — не триал: дата окончания триала больше не значит
    # ничего и не должна закрывать рост.
    org.trial_ends_at = None
    await session.commit()
    await session.refresh(invoice)
    await session.refresh(org)
    return invoice
