"""Админка платформы: организации, тарифы, блокировки, оплаты (шаг 4.3).

Зачем отдельный роутер, а не ручки организации. У клиента своя админка
(`/api/org/*`), у платформы — своя: список всех клиентов, смена тарифа,
блокировка и подтверждение оплаты. Смешать их в одном префиксе значило бы
однажды забыть проверку и отдать владельцу салона список конкурентов.

Кто платформенный администратор. Тот, чей `telegram_id` есть в
`ADMIN_TG_IDS`/встроенной паре (`settings.staff_tg_id_set`) — то есть владелец
продукта, а не клиент. Роль `admin` внутри организации сюда НЕ подходит: она
выдаётся владельцу салона и снимается там же.

Почему `all_orgs()`. Тенантский фильтр добавляет `WHERE org_id = …` к каждой
выборке (см. `app/db/tenancy.py`), и без обхода платформа видела бы только
первую организацию. `all_orgs()` — единственное законное место такого обхода:
здесь данные всех клиентов действительно нужны вместе.

Почему подтверждение оплаты здесь, а не у клиента. `billing.mark_paid`
продлевает подписку и меняет тариф. Если бы его вызывала ручка организации,
владелец продлевал бы себе тариф одним кликом без денег. Поэтому кнопка
«подтвердить» живёт под платформенным админом.
"""

from __future__ import annotations

from typing import Annotated, NoReturn

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, SessionDep
from app.config import get_settings
from app.db.models import User
from app.db.org_models import OrgInvoice, Organization
from app.db.tenancy import all_orgs
from app.services import billing, monitoring, rum

log = structlog.get_logger()
router = APIRouter(tags=["platform"])

_STATUS: dict[str, int] = {
    "platform_admin_required": status.HTTP_403_FORBIDDEN,
    "org_not_found": status.HTTP_404_NOT_FOUND,
    "bad_plan": status.HTTP_400_BAD_REQUEST,
    "bad_date": status.HTTP_400_BAD_REQUEST,
    "invoice_not_found": status.HTTP_404_NOT_FOUND,
    "invoice_not_payable": status.HTTP_409_CONFLICT,
    "invoice_not_cancelable": status.HTTP_409_CONFLICT,
    "invoice_expired": status.HTTP_410_GONE,
}


def _fail(exc: Exception) -> NoReturn:
    code = str(exc)
    raise HTTPException(_STATUS.get(code, status.HTTP_400_BAD_REQUEST), detail=code)


async def require_platform_admin(user: CurrentUser) -> User:
    """Только владельцы продукта: Telegram-id из `ADMIN_TG_IDS`/встроенной пары.

    Клиентский `admin` не подходит: он живёт в `employees.role` и выдаётся
    владельцу салона. Отказ — 403 без подробностей, чтобы перебор id не
    подсказывал, кто здесь админ.
    """
    tg_id = user.telegram_id
    if tg_id is None or tg_id not in get_settings().staff_tg_id_set:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="platform_admin_required"
        )
    return user


PlatformDep = Annotated[User, Depends(require_platform_admin)]


class PlatformMeOut(BaseModel):
    is_platform_admin: bool


class PlatformOrgOut(BaseModel):
    id: int
    slug: str
    name: str
    industry: str
    is_active: bool
    plan: str
    plan_title: str
    seats_used: int
    seats_limit: int
    branches_used: int
    branches_limit: int
    trial_ends_at: str | None
    plan_ends_at: str | None
    trial_expired: bool
    subscription_expired: bool
    created_at: str | None


class PlatformOrgsOut(BaseModel):
    items: list[PlatformOrgOut]
    total: int


class PlatformOrgPatch(BaseModel):
    """Правка клиента платформой.

    `plan_ends_at`/`trial_ends_at` принимают ISO-дату или пустую строку: пустая
    означает «снять срок» (например, перевести на бессрочный тариф).
    """

    plan: str | None = Field(default=None, max_length=16)
    plan_ends_at: str | None = None
    trial_ends_at: str | None = None
    is_active: bool | None = None


class PlatformInvoiceOut(BaseModel):
    id: int
    org_id: int
    org_name: str
    number: str
    plan: str
    plan_title: str
    period: str
    amount: int
    currency: str
    status: str
    created_at: str | None
    expires_at: str
    paid_at: str | None
    period_start: str | None
    period_end: str | None


class PlatformInvoicesOut(BaseModel):
    items: list[PlatformInvoiceOut]
    total: int
    awaiting: int


class PlatformPlanOut(BaseModel):
    """Тариф в админке: коды и цены приходят с сервера, а не из констант фронта."""

    code: str
    title: str
    seats: int
    branches: int
    price_month: int
    price_year: int


class PlatformSummaryOut(BaseModel):
    organizations: int
    active: int
    on_trial: int
    expired: int
    awaiting_invoices: int
    unpaid_amount: int
    plans: list[PlatformPlanOut]


def _iso(value) -> str | None:  # noqa: ANN001
    return value.isoformat() if value is not None else None


def _parse_date(raw: str, *, allow_empty: bool = True):  # noqa: ANN201
    """ISO-дата из админки. Пустая строка — «снять срок»."""
    text = (raw or "").strip()
    if not text:
        if allow_empty:
            return None
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_date")
    try:
        from datetime import UTC, datetime

        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_date") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


async def _org_out(session: SessionDep, org: Organization) -> PlatformOrgOut:
    state = await billing.state(session, org)
    return PlatformOrgOut(
        id=org.id,
        slug=org.slug,
        name=org.name,
        industry=org.industry,
        is_active=org.is_active,
        plan=org.plan,
        plan_title=state.title,
        seats_used=state.seats_used,
        seats_limit=state.seats_limit,
        branches_used=state.branches_used,
        branches_limit=state.branches_limit,
        trial_ends_at=_iso(org.trial_ends_at),
        plan_ends_at=_iso(org.plan_ends_at),
        trial_expired=state.trial_expired,
        subscription_expired=state.subscription_expired,
        created_at=_iso(org.created_at),
    )


async def _invoice_out(session: SessionDep, invoice: OrgInvoice) -> PlatformInvoiceOut:
    org = await session.get(Organization, invoice.org_id)
    return PlatformInvoiceOut(
        id=invoice.id,
        org_id=invoice.org_id,
        org_name=org.name if org is not None else "—",
        number=invoice.number,
        plan=invoice.plan,
        plan_title=billing.plan_for(invoice.plan).title,
        period=invoice.period,
        amount=invoice.amount,
        currency=invoice.currency,
        status=billing.invoice_status(invoice),
        created_at=_iso(invoice.created_at),
        expires_at=_iso(invoice.expires_at) or "",
        paid_at=_iso(invoice.paid_at),
        period_start=_iso(invoice.period_start),
        period_end=_iso(invoice.period_end),
    )


@router.get("/platform/rum")
async def platform_rum(_admin: PlatformDep) -> dict:
    """Core Web Vitals с реальных устройств: p75/p95 по платформе за 24 часа.

    Источник — `POST /api/telemetry/vitals`, который пишет фронт. Экран
    платформы читает ту же сводку, поэтому цифры в приложении и в CI
    (Lighthouse) можно сравнивать напрямую.
    """
    return rum.rum.snapshot()


@router.get("/platform/me", response_model=PlatformMeOut)
async def platform_me(user: CurrentUser) -> PlatformMeOut:
    """Платформенный админ я или клиент. Отвечает всем вошедшим."""
    return PlatformMeOut(
        is_platform_admin=bool(
            user.telegram_id is not None
            and user.telegram_id in get_settings().staff_tg_id_set
        )
    )


@router.get("/platform/summary", response_model=PlatformSummaryOut)
async def platform_summary(
    session: SessionDep, _admin: PlatformDep
) -> PlatformSummaryOut:
    """Сводка по всем клиентам: сколько на триале, истекает и ждёт денег."""
    with all_orgs():
        orgs = list(await session.scalars(select(Organization)))
        invoices = list(
            await session.scalars(
                select(OrgInvoice).where(
                    OrgInvoice.status.in_([billing.INVOICE_PENDING, billing.INVOICE_AWAITING])
                )
            )
        )
    on_trial = expired = awaiting = 0
    unpaid = 0
    for org in orgs:
        state_plan = billing.plan_for(org.plan)
        if state_plan.trial:
            if await _is_expired(org.trial_ends_at):
                expired += 1
            else:
                on_trial += 1
        elif await _is_expired(org.plan_ends_at):
            expired += 1
    for invoice in invoices:
        if billing.invoice_status(invoice) != billing.INVOICE_EXPIRED:
            awaiting += 1
            unpaid += invoice.amount
    return PlatformSummaryOut(
        organizations=len(orgs),
        active=sum(1 for org in orgs if org.is_active),
        on_trial=on_trial,
        expired=expired,
        awaiting_invoices=awaiting,
        unpaid_amount=unpaid,
        plans=[
            PlatformPlanOut(
                code=plan.code,
                title=plan.title,
                seats=plan.seats,
                branches=plan.branches,
                price_month=plan.price_month,
                price_year=plan.price_year,
            )
            for plan in billing.PLANS.values()
        ],
    )


async def _is_expired(value) -> bool:  # noqa: ANN001
    from datetime import UTC, datetime

    if value is None:
        return False
    moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return moment <= datetime.now(UTC)


@router.get("/platform/orgs", response_model=PlatformOrgsOut)
async def platform_orgs(
    session: SessionDep,
    _admin: PlatformDep,
    q: str = Query("", max_length=120),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> PlatformOrgsOut:
    """Клиенты платформы: тариф, занятые места, сроки и блокировка.

    Поиск по имени и коду: поддержка ищет «Салон на Ленина» или `salon-lenina`,
    а не помнит id. Свежие — сверху, потому что новый клиент требует внимания.
    """
    with all_orgs():
        query = select(Organization)
        term = q.strip()
        if term:
            like = f"%{term}%"
            query = query.where(
                or_(Organization.name.ilike(like), Organization.slug.ilike(like))
            )
        total = await session.scalar(
            select(func.count()).select_from(query.subquery())
        )
        rows = list(
            await session.scalars(
                query.order_by(Organization.id.desc()).limit(limit).offset(offset)
            )
        )
        items = [await _org_out(session, org) for org in rows]
    return PlatformOrgsOut(items=items, total=int(total or 0))


@router.patch("/platform/orgs/{org_id}", response_model=PlatformOrgOut)
async def platform_patch_org(
    org_id: int,
    body: PlatformOrgPatch,
    session: SessionDep,
    admin: PlatformDep,
) -> PlatformOrgOut:
    """Сменить тариф, срок или заблокировать клиента.

    Блокировка (`is_active=False`) закрывает вход сразу: `current_org` отдаёт
    403 на следующем же запросе, а не после истечения сессии.

    Смена тарифа на платный без срока (`plan_ends_at=""`) — осознанное
    действие для бессрочных договоров; для продажи по счёту срок ставит
    `mark_paid`, и трогать его руками не нужно.
    """
    with all_orgs():
        org = await session.get(Organization, org_id)
        if org is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="org_not_found")
        if body.plan is not None:
            code = body.plan.strip().lower()
            if code not in billing.PLANS:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_plan")
            org.plan = code
            # Платный тариф больше не триал: дата окончания триала иначе
            # закрыла бы рост уже после оплаты.
            if code != "trial" and body.trial_ends_at is None:
                org.trial_ends_at = None
        if body.trial_ends_at is not None:
            org.trial_ends_at = _parse_date(body.trial_ends_at)
        if body.plan_ends_at is not None:
            org.plan_ends_at = _parse_date(body.plan_ends_at)
        if body.is_active is not None:
            org.is_active = body.is_active
        await session.commit()
        await session.refresh(org)
        log.info(
            "platform.org_patched",
            org_id=org.id,
            plan=org.plan,
            is_active=org.is_active,
            by=admin.id,
        )
        return await _org_out(session, org)


@router.get("/platform/invoices", response_model=PlatformInvoicesOut)
async def platform_invoices(
    session: SessionDep,
    _admin: PlatformDep,
    invoice_status: str = Query("", alias="status", max_length=16),
    limit: int = Query(50, ge=1, le=200),
) -> PlatformInvoicesOut:
    """Счета всех клиентов. Ожидающие подтверждения — сверху.

    Статус `awaiting` — это «клиент нажал „я оплатил“»: деньги, скорее всего,
    уже пришли, и задержка здесь выглядит как «оплатил, а доступ не включили».
    """
    with all_orgs():
        query = select(OrgInvoice)
        wanted = invoice_status.strip()
        if wanted:
            query = query.where(OrgInvoice.status == wanted)
        rows = list(
            await session.scalars(
                query.order_by(OrgInvoice.created_at.desc(), OrgInvoice.id.desc()).limit(limit)
            )
        )
        items = [await _invoice_out(session, row) for row in rows]
        open_rows = [
            row
            for row in await session.scalars(
                select(OrgInvoice).where(
                    OrgInvoice.status.in_([billing.INVOICE_PENDING, billing.INVOICE_AWAITING])
                )
            )
            if billing.invoice_status(row) != billing.INVOICE_EXPIRED
        ]
    # «Ждут» считаем по всем открытым, а не по отфильтрованной выборке: бейдж
    # на экране не должен зависеть от того, какой фильтр сейчас выбран.
    open_rows.sort(key=lambda row: (row.status != billing.INVOICE_AWAITING, row.id))
    return PlatformInvoicesOut(items=items, total=len(items), awaiting=len(open_rows))


@router.post("/platform/invoices/{invoice_id}/confirm", response_model=PlatformInvoiceOut)
async def platform_confirm_invoice(
    invoice_id: int, session: SessionDep, admin: PlatformDep
) -> PlatformInvoiceOut:
    """Подтвердить оплату и продлить подписку клиента."""
    with all_orgs():
        invoice = await session.get(OrgInvoice, invoice_id)
        if invoice is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="invoice_not_found")
        org = await session.get(Organization, invoice.org_id)
        if org is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="org_not_found")
        try:
            await billing.mark_paid(session, org, invoice)
        except billing.InvoiceError as exc:
            _fail(exc)
        log.info(
            "platform.invoice_confirmed",
            org_id=org.id,
            invoice_id=invoice.id,
            amount=invoice.amount,
            by=admin.id,
        )
        return await _invoice_out(session, invoice)


@router.post("/platform/invoices/{invoice_id}/cancel", response_model=PlatformInvoiceOut)
async def platform_cancel_invoice(
    invoice_id: int, session: SessionDep, admin: PlatformDep
) -> PlatformInvoiceOut:
    """Отменить счёт клиента (выписан по ошибке или оплачен иначе)."""
    with all_orgs():
        invoice = await session.get(OrgInvoice, invoice_id)
        if invoice is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="invoice_not_found")
        try:
            await billing.cancel_invoice(session, invoice.org_id, invoice.id)
        except billing.InvoiceError as exc:
            _fail(exc)
        log.info(
            "platform.invoice_canceled",
            org_id=invoice.org_id,
            invoice_id=invoice.id,
            by=admin.id,
        )
        return await _invoice_out(session, invoice)


class MonitoringTopPathOut(BaseModel):
    path: str
    count: int


class MonitoringTopErrorOut(BaseModel):
    path: str
    status: int
    count: int


class MonitoringLastErrorOut(BaseModel):
    at: str
    method: str
    path: str
    status: int
    duration_ms: float


class PlatformMonitoringOut(BaseModel):
    """Сводка по последним минутам: объём, ошибки, скорость, причина алерта."""

    window_seconds: int
    requests: int
    errors: int
    error_rate: float
    p50_ms: float
    p95_ms: float
    slowest_ms: float
    top_paths: list[MonitoringTopPathOut]
    top_errors: list[MonitoringTopErrorOut]
    last_error: MonitoringLastErrorOut | None
    alert: str | None


@router.get("/platform/monitoring", response_model=PlatformMonitoringOut)
async def platform_monitoring(_admin: PlatformDep) -> PlatformMonitoringOut:
    """Что происходит с API прямо сейчас.

    Только для платформенного админа: цифры про все организации сразу — не то,
    что должен видеть клиент, и уж точно не публичная ручка. Счётчики живут в
    памяти процесса, поэтому после перезапуска окно начинается заново — это
    ожидаемо и описано в `docs/MONITORING.md`.
    """
    data = monitoring.snapshot()
    return PlatformMonitoringOut(
        window_seconds=data.window_seconds,
        requests=data.requests,
        errors=data.errors,
        error_rate=round(data.error_rate, 4),
        p50_ms=round(data.p50_ms, 1),
        p95_ms=round(data.p95_ms, 1),
        slowest_ms=round(data.slowest_ms, 1),
        top_paths=data.top_paths,
        top_errors=data.top_errors,
        last_error=data.last_error,
        alert=data.alert,
    )
