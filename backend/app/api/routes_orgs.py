"""Приглашения в организацию: ссылки, список, принятие (шаг 2.2).

Разделение прав намеренно простое и совпадает с интерфейсом:

* выписать и отозвать ссылку может тот, у кого есть админка (`AdminDep`);
* посмотреть приглашение может любой — токен и есть пропуск, но он показывает
  только название организации, роль и срок;
* принять — любой вошедший человек (сессия, Telegram или ссылка доступа).

Организация берётся из `current_org` (то есть из сотрудника), а не из тела
запроса: клиент не должен выбирать, в чей тенант писать приглашение.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Annotated, NoReturn

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import AdminDep, CurrentUser, SessionDep, current_org
from app.db.hr_models import Department, Employee
from app.db.models import User
from app.db.org_models import (
    INDUSTRIES,
    ORG_ROLES,
    Organization,
    OrganizationMember,
)
from app.services import (
    audit,
    billing,
    brand,
    branches,
    domains,
    hr_access,
    invitations,
    mail,
    orgs,
    privacy,
)

log = structlog.get_logger()
router = APIRouter(tags=["orgs"])

OrgDep = Annotated[Organization, Depends(current_org)]

# Код ошибки → HTTP-статус. Коды, а не тексты: перевод живёт на фронте, иначе
# одну и ту же форму пришлось бы переводить в двух местах.
_STATUS: dict[str, int] = {
    "bad_role": status.HTTP_400_BAD_REQUEST,
    "bad_email": status.HTTP_400_BAD_REQUEST,
    "bad_invite_ttl": status.HTTP_400_BAD_REQUEST,
    "invite_limit": status.HTTP_409_CONFLICT,
    "invite_already_accepted": status.HTTP_409_CONFLICT,
    "invite_invalid": status.HTTP_404_NOT_FOUND,
    "invite_not_found": status.HTTP_404_NOT_FOUND,
    "invite_expired": status.HTTP_410_GONE,
    "invite_used": status.HTTP_410_GONE,
    "invite_revoked": status.HTTP_410_GONE,
    "invite_email_mismatch": status.HTTP_403_FORBIDDEN,
    "org_inactive": status.HTTP_403_FORBIDDEN,
    "org_not_found": status.HTTP_404_NOT_FOUND,
    "org_missing": status.HTTP_404_NOT_FOUND,
    "bad_name": status.HTTP_400_BAD_REQUEST,
    "bad_slug": status.HTTP_400_BAD_REQUEST,
    "slug_taken": status.HTTP_409_CONFLICT,
    "bad_industry": status.HTTP_400_BAD_REQUEST,
    "member_not_found": status.HTTP_404_NOT_FOUND,
    "self_role_change": status.HTTP_400_BAD_REQUEST,
    "last_owner": status.HTTP_409_CONFLICT,
    # Тариф (шаг 4.1): лимит мест и подразделений — конфликт с
    # границей, а истёкший триал — «нужна оплата», не «ошибка ввода».
    "seats_limit": status.HTTP_409_CONFLICT,
    "branches_limit": status.HTTP_409_CONFLICT,
    "trial_expired": status.HTTP_402_PAYMENT_REQUIRED,
    # Оплата (шаг 4.2): неверный тариф/период — ошибка ввода, а
    # просроченный и уже оплаченный счёт — конфликт состояния, не 404.
    "subscription_expired": status.HTTP_402_PAYMENT_REQUIRED,
    "bad_plan": status.HTTP_400_BAD_REQUEST,
    "bad_period": status.HTTP_400_BAD_REQUEST,
    "plan_not_payable": status.HTTP_409_CONFLICT,
    "invoice_not_found": status.HTTP_404_NOT_FOUND,
    "invoice_expired": status.HTTP_410_GONE,
    "invoice_not_payable": status.HTTP_409_CONFLICT,
    "invoice_not_cancelable": status.HTTP_409_CONFLICT,
    # Бренд (шаг 4.4): цвет и логотип приходят из формы, поэтому это
    # ошибка ввода, а не конфликт состояния.
    "bad_color": status.HTTP_400_BAD_REQUEST,
    "bad_logo": status.HTTP_400_BAD_REQUEST,
    # Свой домен (06.11.2026): неверное имя — ошибка ввода, занятый
    # адрес — конфликт, а непрошедшая проверка — состояние домена.
    "bad_domain": status.HTTP_400_BAD_REQUEST,
    "domain_reserved": status.HTTP_400_BAD_REQUEST,
    "domain_taken": status.HTTP_409_CONFLICT,
    # Филиалы сети (06.11.2026): чужой филиал не открыть, глубже одного
    # уровня не построить, потолок — не ошибка ввода, а состояние тарифа.
    "branch_owner_required": status.HTTP_403_FORBIDDEN,
    "org_switch_denied": status.HTTP_403_FORBIDDEN,
    "branch_of_branch": status.HTTP_409_CONFLICT,
    "branch_limit": status.HTTP_409_CONFLICT,
    "domain_not_set": status.HTTP_409_CONFLICT,
    "verify_failed": status.HTTP_409_CONFLICT,
    "verify_mismatch": status.HTTP_409_CONFLICT,
    # Приватность (шаг 5.5): удаление требует точного кода организации —
    # опечатка не должна стирать клиента; повторный запрос и отмена
    # без запроса — конфликт состояния, а не ошибка ввода.
    "bad_confirm": status.HTTP_400_BAD_REQUEST,
    "already_deleting": status.HTTP_409_CONFLICT,
    "not_deleting": status.HTTP_409_CONFLICT,
    "owner_required": status.HTTP_403_FORBIDDEN,
}


def _fail(exc: Exception) -> NoReturn:
    code = str(exc)
    raise HTTPException(_STATUS.get(code, status.HTTP_400_BAD_REQUEST), detail=code)


# Подбор кода организации — это и есть «пароль» на вход. Ограничение попыток
# делает перебор названий невыгодным, при этом не мешает человеку, который
# просто опечатался. Счётчик в памяти процесса: одна реплика API, а при
# нескольких — попытки всё равно ограничены сетью и задержкой ответа.
_JOIN_WINDOW = 10 * 60.0
_JOIN_LIMIT = 8
_join_attempts: dict[int, list[float]] = {}


def _join_allowed(user_id: int) -> bool:
    now = time.monotonic()
    window = [t for t in _join_attempts.get(user_id, []) if now - t < _JOIN_WINDOW]
    if len(window) >= _JOIN_LIMIT:
        _join_attempts[user_id] = window
        return False
    window.append(now)
    _join_attempts[user_id] = window
    return True


class OrgCodeIn(BaseModel):
    """Точный код (slug) или точное название организации."""

    code: str = Field(min_length=1, max_length=120)


class OrgCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str | None = Field(default=None, max_length=64)
    industry: str = Field(default="restaurant", max_length=32)


class OrgOut(BaseModel):
    id: int
    slug: str
    name: str
    role: str


class PlanOut(BaseModel):
    """Тариф своей организации: лимиты, занятые места и срок триала."""

    code: str
    title: str
    seats_used: int
    seats_limit: int
    branches_used: int
    branches_limit: int
    invites_active: int
    trial_ends_at: str | None = None
    trial_days_left: int | None = None
    trial_expired: bool
    # Срок оплаченной подписки (шаг 4.2). Пусто у триала и у
    # организаций, оплаченных бессрочно.
    plan_ends_at: str | None = None
    plan_days_left: int | None = None
    subscription_expired: bool = False


class PlanPriceOut(BaseModel):
    """Тариф в витрине: что включено и сколько стоит."""

    code: str
    title: str
    seats: int
    branches: int
    price_month: int
    price_year: int


class InvoiceOut(BaseModel):
    """Счёт на оплату. `status` считает сервер, включая `expired`."""

    id: int
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


class BillingOut(BaseModel):
    plan: PlanOut
    prices: list[PlanPriceOut]
    invoices: list[InvoiceOut]
    invoice_ttl_days: int


class InvoiceIn(BaseModel):
    plan: str = Field(min_length=1, max_length=16)
    period: str = Field(default="month", max_length=8)


class BrandOut(BaseModel):
    """Бренд организации: что видит клиент вместо имени платформы."""

    name: str
    color: str
    logo_url: str | None
    bot_username: str | None
    is_custom: bool


class BrandPatch(BaseModel):
    """Правка бренда. Отсутствующее поле не меняется, пустое — сбрасывается."""

    name: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=9)
    logo_url: str | None = Field(default=None, max_length=500)


class OrgMemberOut(BaseModel):
    """Человек с доступом к организации.

    Две роли рядом не для красоты: `role` — уровень доступа к организации
    (знаете, кого приглашать владельцем), `hr_role` — что человек видит в
    приложении. Изменение первой меняет и вторую, иначе «назначил
    управляющим» осталось бы словами.
    """

    user_id: int
    name: str
    email: str | None
    role: str
    hr_role: str | None
    is_self: bool


class OrgMemberRoleIn(BaseModel):
    role: str = Field(min_length=1, max_length=16)


class InvitationIn(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    role: str = Field(default="staff", max_length=16)
    days: int = Field(default=invitations.INVITE_TTL_DAYS, ge=1, le=invitations.MAX_TTL_DAYS)
    # Необязательно: ссылка без должности — это нормальная «ссылка в чат смены».
    position: str | None = Field(default=None, max_length=120)
    department_id: int | None = None


class InvitationOut(BaseModel):
    id: int
    email: str | None
    role: str
    position: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    created_at: str | None
    expires_at: str
    # Ссылка отдаётся один раз — в ответе на создание. В списке её нет: токен
    # в базе только хешем, восстановить его нельзя (и не нужно).
    link: str | None = None
    mail_sent: bool = False


class InvitationPreview(BaseModel):
    org_name: str
    role: str
    email: str | None
    expires_at: str
    position: str | None = None
    department_name: str | None = None


class AcceptOut(BaseModel):
    ok: bool
    org_id: int
    org_name: str
    role: str


def _iso(value) -> str | None:  # noqa: ANN001
    return value.isoformat() if value is not None else None


async def _department_name(
    session: SessionDep, department_id: int | None
) -> str | None:
    if department_id is None:
        return None
    dept = await session.get(Department, department_id)
    return dept.name if dept is not None else None


async def _out(
    session: SessionDep,
    row,  # noqa: ANN001
    *,
    link: str | None = None,
    mail_sent: bool = False,
) -> InvitationOut:
    return InvitationOut(
        id=row.id,
        email=row.email,
        role=row.role,
        position=row.position,
        department_id=row.department_id,
        department_name=await _department_name(session, row.department_id),
        created_at=_iso(row.created_at),
        expires_at=_iso(row.expires_at) or "",
        link=link,
        mail_sent=mail_sent,
    )


def _org_out(org: Organization, role: str) -> OrgOut:
    return OrgOut(id=org.id, slug=org.slug, name=org.name, role=role)


@router.get("/org/current", response_model=OrgOut)
async def current_organization(
    session: SessionDep, user: CurrentUser, org: OrgDep
) -> OrgOut:
    """Своя организация: имя и код, который руководитель передаёт сотрудникам.

    Только про себя: список всех организаций платформы наружу не отдаётся ни
    этой ручкой, ни какой-либо другой.
    """
    row = await orgs.member(session, org_id=org.id, user_id=user.id)
    return _org_out(org, row.role if row is not None else "staff")


@router.post("/org/join", response_model=OrgOut)
async def join_organization(
    body: OrgCodeIn, session: SessionDep, user: CurrentUser
) -> OrgOut:
    """Присоединиться к существующей организации по коду или названию."""
    if not _join_allowed(user.id):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail="join_rate_limited"
        )
    try:
        org, role = await orgs.join_by_code(
            session, user=user, code=body.code
        )
    except orgs.OrgsError as exc:
        _fail(exc)
    log.info("orgs.join", org_id=org.id, user_id=user.id, role=role)
    return _org_out(org, role)


@router.post(
    "/org/create",
    response_model=OrgOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_own_organization(
    body: OrgCreateIn, session: SessionDep, user: CurrentUser
) -> OrgOut:
    """Руководитель заводит свою организацию и становится её владельцем.

    Проверять права не у кого: организации ещё нет. Роль `owner` выдаётся
    здесь же, поэтому дальше человек попадает в мастер настройки, а не в
    экран «тебя не пригласили».
    """
    if body.industry not in INDUSTRIES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="bad_industry"
        )
    try:
        org = await orgs.create_with_owner(
            session,
            user=user,
            name=body.name,
            industry=body.industry,
            slug=body.slug,
        )
    except orgs.OrgsError as exc:
        _fail(exc)
    log.info("orgs.created", org_id=org.id, user_id=user.id)
    return _org_out(org, "owner")


# Порядок в списке: владельцы, управляющие, остальные. Ровно тот же смысл,
# что у уровней доступа, — не алфавит по имени.
_ROLE_ORDER = {"owner": 0, "manager": 1, "staff": 2}


def _member_out(
    member: OrganizationMember,
    user: User | None,
    hr_role: str | None,
    *,
    me: int,
) -> OrgMemberOut:
    return OrgMemberOut(
        user_id=member.user_id,
        name=(user.display_name if user else "") or (user.email if user else "") or "—",
        email=user.email if user else None,
        role=member.role,
        hr_role=hr_role,
        is_self=member.user_id == me,
    )


@router.get("/org/plan", response_model=PlanOut)
async def organization_plan(
    session: SessionDep, org: OrgDep, _admin: AdminDep
) -> PlanOut:
    """Тариф своей организации.

    Только руководителю: цифры про людей и границы тарифа — не то, что
    нужно смене. Чужой тариф не запросить: организация берётся из
    сотрудника запроса, а не из параметров.
    """
    return await _plan_out(session, org)


def _invoice_out(invoice) -> InvoiceOut:  # noqa: ANN001
    return InvoiceOut(
        id=invoice.id,
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


async def _plan_out(session: SessionDep, org: OrgDep) -> PlanOut:
    state = await billing.state(session, org)
    return PlanOut(
        code=state.code,
        title=state.title,
        seats_used=state.seats_used,
        seats_limit=state.seats_limit,
        branches_used=state.branches_used,
        branches_limit=state.branches_limit,
        invites_active=state.invites_active,
        trial_ends_at=_iso(state.trial_ends_at),
        trial_days_left=state.trial_days_left,
        trial_expired=state.trial_expired,
        plan_ends_at=_iso(state.plan_ends_at),
        plan_days_left=state.plan_days_left,
        subscription_expired=state.subscription_expired,
    )


@router.get("/org/billing", response_model=BillingOut)
async def organization_billing(
    session: SessionDep, org: OrgDep, _admin: AdminDep
) -> BillingOut:
    """Витрина тарифов и история счетов своей организации.

    Только руководителю: суммы и счета — не то, что нужно смене. Чужую
    бухгалтерию запросить нельзя: организация берётся из сотрудника запроса.
    """
    rows = await billing.list_invoices(session, org.id)
    return BillingOut(
        plan=await _plan_out(session, org),
        prices=[
            PlanPriceOut(
                code=plan.code,
                title=plan.title,
                seats=plan.seats,
                branches=plan.branches,
                price_month=plan.price_month,
                price_year=plan.price_year,
            )
            for plan in billing.payable_plans()
        ],
        invoices=[_invoice_out(row) for row in rows],
        invoice_ttl_days=billing.INVOICE_TTL_DAYS,
    )


@router.post(
    "/org/invoices",
    response_model=InvoiceOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_org_invoice(
    body: InvoiceIn,
    session: SessionDep,
    user: CurrentUser,
    org: OrgDep,
    _admin: AdminDep,
) -> InvoiceOut:
    """Выставить счёт на тариф и период.

    Счёт не меняет тариф: подписка продлевается только подтверждённой
    оплатой (`billing.mark_paid`). Иначе «выставить счёт» было бы кнопкой
    бесплатного безлимита.
    """
    try:
        invoice = await billing.create_invoice(
            session,
            org,
            plan_code=body.plan,
            period=body.period,
            created_by_id=user.id,
        )
    except billing.InvoiceError as exc:
        _fail(exc)
    log.info(
        "billing.invoice_created",
        org_id=org.id,
        invoice_id=invoice.id,
        plan=invoice.plan,
        period=invoice.period,
        amount=invoice.amount,
    )
    return _invoice_out(invoice)


@router.post("/org/invoices/{invoice_id}/paid", response_model=InvoiceOut)
async def request_invoice_payment(
    invoice_id: int, session: SessionDep, org: OrgDep, _admin: AdminDep
) -> InvoiceOut:
    """«Я оплатил»: счёт ждёт подтверждения.

    Не продлевает подписку. Подтверждение приходит от платформы — иначе
    владелец продлевал бы тариф одним кликом без денег.
    """
    try:
        invoice = await billing.request_payment(session, org.id, invoice_id)
    except billing.InvoiceError as exc:
        _fail(exc)
    log.info("billing.invoice_payment_requested", org_id=org.id, invoice_id=invoice.id)
    return _invoice_out(invoice)


@router.post("/org/invoices/{invoice_id}/cancel", response_model=InvoiceOut)
async def cancel_org_invoice(
    invoice_id: int, session: SessionDep, org: OrgDep, _admin: AdminDep
) -> InvoiceOut:
    """Отменить неоплаченный счёт. Оплаченный не отменяется — это деньги."""
    try:
        invoice = await billing.cancel_invoice(session, org.id, invoice_id)
    except billing.InvoiceError as exc:
        _fail(exc)
    log.info("billing.invoice_canceled", org_id=org.id, invoice_id=invoice.id)
    return _invoice_out(invoice)


class DomainOut(BaseModel):
    domain: str | None
    token: str | None
    verified: bool
    checked_at: datetime | None
    verify_path: str
    verify_prefix: str


class DomainIn(BaseModel):
    domain: str = Field(min_length=3, max_length=253)


class BranchOut(BaseModel):
    """Организация сети: головная или филиал."""

    id: int
    slug: str
    name: str
    role: str
    is_root: bool
    is_current: bool


class BranchIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


async def _branch_root(
    session: SessionDep, org: Organization, user: User
) -> Organization:
    """Головная организация сети, если человек — её владелец.

    Проверка по членству, а не по роли сотрудника: владелец сети остаётся
    владельцем, даже когда он сейчас работает в филиале.
    """
    root = await branches.root_of(session, org)
    member = await orgs.member(session, org_id=root.id, user_id=user.id)
    if member is None or member.role != "owner":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="branch_owner_required"
        )
    return root


@router.get("/org/branches", response_model=list[BranchOut])
async def list_branches(
    session: SessionDep, org: OrgDep, user: CurrentUser, _admin: AdminDep
) -> list[BranchOut]:
    """Сеть: головная организация и её филиалы.

    Список видит только владелец сети: для остальных филиалы — отдельные
    клиенты, и их названия наружу не отдаются.
    """
    root = await _branch_root(session, org, user)
    rows = await branches.network(session, root=root, user_id=user.id)
    return [
        BranchOut(
            id=row.id,
            slug=row.slug,
            name=row.name,
            role=role,
            is_root=row.id == root.id,
            is_current=row.id == org.id,
        )
        for row, role in rows
    ]


@router.post(
    "/org/branches",
    response_model=BranchOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_branch(
    body: BranchIn,
    session: SessionDep,
    org: OrgDep,
    user: CurrentUser,
    _admin: AdminDep,
) -> BranchOut:
    """Завести филиал сети; владелец получает в нём членство `owner`."""
    root = await _branch_root(session, org, user)
    try:
        row = await branches.create_branch(
            session, root=root, user=user, name=body.name
        )
    except branches.BranchesError as exc:
        _fail(exc)
    await audit.record(
        session,
        org_id=root.id,
        action="org.branch_created",
        user=user,
        target_type="organization",
        target_id=row.id,
        details={"name": row.name, "branch_org_id": row.id},
    )
    await session.commit()
    log.info("orgs.branch_created", root_id=root.id, branch_id=row.id)
    return BranchOut(
        id=row.id,
        slug=row.slug,
        name=row.name,
        role="owner",
        is_root=False,
        is_current=False,
    )


def _domain_out(row: domains.DomainState) -> DomainOut:
    return DomainOut(
        domain=row.domain,
        token=row.token,
        verified=row.verified,
        checked_at=row.checked_at,
        verify_path=row.verify_path,
        verify_prefix=row.verify_prefix,
    )


@router.get("/org/domain", response_model=DomainOut)
async def current_domain(org: OrgDep, _admin: AdminDep) -> DomainOut:
    """Свой домен организации — только руководителю: это адрес входа."""
    return _domain_out(domains.state(org))


@router.put("/org/domain", response_model=DomainOut)
async def set_org_domain(
    body: DomainIn,
    session: SessionDep,
    org: OrgDep,
    user: CurrentUser,
    _admin: AdminDep,
) -> DomainOut:
    """Сохранить домен и выдать токен проверки.

    Домен не включается до подтверждения: иначе чужой человек занял бы
    адрес, который ему не принадлежит.
    """
    try:
        row = await domains.set_domain(session, org, body.domain)
    except domains.DomainError as exc:
        _fail(exc)
    await audit.record(
        session,
        org_id=org.id,
        action="org.domain_set",
        user=user,
        target_type="organization",
        target_id=org.id,
        details={"domain": row.domain},
    )
    await session.commit()
    log.info("orgs.domain_set", org_id=org.id, domain=row.domain)
    return _domain_out(row)


@router.post("/org/domain/verify", response_model=DomainOut)
async def verify_org_domain(
    session: SessionDep, org: OrgDep, user: CurrentUser, _admin: AdminDep
) -> DomainOut:
    """Проверить контроль файлом `/.well-known/semitask-domain.txt`."""
    try:
        row = await domains.verify_domain(session, org)
    except domains.DomainError as exc:
        _fail(exc)
    await audit.record(
        session,
        org_id=org.id,
        action="org.domain_verified",
        user=user,
        target_type="organization",
        target_id=org.id,
        details={"domain": row.domain},
    )
    await session.commit()
    return _domain_out(row)


@router.delete("/org/domain", response_model=DomainOut)
async def clear_org_domain(
    session: SessionDep, org: OrgDep, user: CurrentUser, _admin: AdminDep
) -> DomainOut:
    """Снять свой домен. Платформенная ссылка остаётся рабочей."""
    row = await domains.clear(session, org)
    await audit.record(
        session,
        org_id=org.id,
        action="org.domain_cleared",
        user=user,
        target_type="organization",
        target_id=org.id,
        details={},
    )
    await session.commit()
    log.info("orgs.domain_cleared", org_id=org.id)
    return _domain_out(row)


@router.get("/brand", response_model=BrandOut)
async def current_brand(org: OrgDep) -> BrandOut:
    """Бренд своей организации. Доступен любому вошедшему.

    Не только руководителю: имя и цвет видит каждый сотрудник, и если бы
    ручка была админской, у смены остался бы бренд платформы, а у владельца —
    свой. Организация берётся из сотрудника запроса, поэтому чужой бренд не
    запросить.
    """
    row = brand.from_org(org)
    return BrandOut(
        name=row.name,
        color=row.color,
        logo_url=row.logo_url,
        bot_username=row.bot_username,
        is_custom=row.is_custom,
    )


@router.patch("/org/brand", response_model=BrandOut)
async def update_brand(
    body: BrandPatch, session: SessionDep, org: OrgDep, _admin: AdminDep
) -> BrandOut:
    """Задать своё имя, цвет и логотип.

    Только руководителю: бренд видит вся команда, и менять его из-под смены
    нельзя. `name` обязателен, если передан: пустое имя — это не «бренд без
    имени», а забытое поле. Сбросить бренд целиком — `DELETE`.
    """
    try:
        row = await brand.update(
            session,
            org,
            name=body.name,
            color=body.color,
            logo_url=body.logo_url,
        )
    except brand.BrandError as exc:
        _fail(exc)
    log.info("orgs.brand_updated", org_id=org.id, custom=row.is_custom)
    return BrandOut(
        name=row.name,
        color=row.color,
        logo_url=row.logo_url,
        bot_username=row.bot_username,
        is_custom=row.is_custom,
    )


@router.delete("/org/brand", response_model=BrandOut)
async def reset_brand(session: SessionDep, org: OrgDep, _admin: AdminDep) -> BrandOut:
    """Сбросить бренд к имени организации. Цвет и логотип тоже уходят."""
    row = await brand.clear(session, org)
    log.info("orgs.brand_reset", org_id=org.id)
    return BrandOut(
        name=row.name,
        color=row.color,
        logo_url=row.logo_url,
        bot_username=row.bot_username,
        is_custom=row.is_custom,
    )


@router.get("/org/members", response_model=list[OrgMemberOut])
async def list_members(
    session: SessionDep, user: CurrentUser, org: OrgDep, _admin: AdminDep
) -> list[OrgMemberOut]:
    """Кто имеет доступ к организации и с какими правами.

    Только своя организация: `org` берётся из сотрудника запроса, а не из
    параметров — чужой список не запросить даже зная id.
    """
    members = list(
        await session.scalars(
            select(OrganizationMember).where(
                OrganizationMember.org_id == org.id
            )
        )
    )
    ids = [row.user_id for row in members]
    users = (
        {
            row.id: row
            for row in await session.scalars(
                select(User).where(User.id.in_(ids))
            )
        }
        if ids
        else {}
    )
    hr = (
        {
            row.user_id: row.role
            for row in await session.scalars(
                select(Employee).where(
                    Employee.org_id == org.id, Employee.user_id.in_(ids)
                )
            )
        }
        if ids
        else {}
    )
    def sort_key(row: OrganizationMember) -> tuple[int, str]:
        person = users.get(row.user_id)
        name = ((person.display_name if person else "") or "").lower()
        return (_ROLE_ORDER.get(row.role, 9), name)

    members.sort(key=sort_key)
    return [
        _member_out(row, users.get(row.user_id), hr.get(row.user_id), me=user.id)
        for row in members
    ]


@router.patch("/org/members/{member_user_id}", response_model=OrgMemberOut)
async def set_member_role(
    member_user_id: int,
    body: OrgMemberRoleIn,
    session: SessionDep,
    user: CurrentUser,
    org: OrgDep,
    _admin: AdminDep,
) -> OrgMemberOut:
    """Сменить уровень доступа человека в организации.

    Три запрета, без которых кнопка опасна:

    * нельзя менять свою роль — иначе один случайный клик снимает доступ у
      того, кто настраивает команду;
    * нельзя снять последнего владельца — организация осталась бы без хозяина;
    * роль должна быть из известного набора.

    Вместе с уровнем доступа меняется и HR-роль: `manager` → `aup`,
    `owner` → `admin`. Иначе человек с «управляющим» в списке не увидел бы
    админку, и правка выглядела бы сломанной.
    """
    if body.role not in ORG_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_role")
    if member_user_id == user.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="self_role_change"
        )
    target = await orgs.member(
        session, org_id=org.id, user_id=member_user_id
    )
    if target is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="member_not_found"
        )
    if target.role == "owner" and body.role != "owner":
        owners = await session.scalars(
            select(OrganizationMember).where(
                OrganizationMember.org_id == org.id,
                OrganizationMember.role == "owner",
            )
        )
        if len(list(owners)) <= 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="last_owner"
            )

    target.role = body.role
    employee = await hr_access.get_employee(session, member_user_id)
    if employee is not None and employee.org_id == org.id:
        hr_access.set_role(employee, hr_access.hr_role_for_org(body.role))
    await session.commit()
    await session.refresh(target)
    await audit.record(
        session,
        org_id=org.id,
        user=user,
        action="member.role_changed",
        target_type="user",
        target_id=member_user_id,
        details={"role": body.role},
    )
    await session.commit()
    target_user = await session.get(User, member_user_id)
    log.info(
        "orgs.member_role",
        org_id=org.id,
        user_id=member_user_id,
        role=body.role,
        by=user.id,
    )
    return _member_out(
        target,
        target_user,
        employee.role if employee is not None else None,
        me=user.id,
    )


@router.get("/org/invitations", response_model=list[InvitationOut])
async def list_invitations(
    session: SessionDep, org: OrgDep, _admin: AdminDep
) -> list[InvitationOut]:
    rows = await invitations.active(session, org.id)
    return [await _out(session, row) for row in rows]


@router.post(
    "/org/invitations",
    response_model=InvitationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    body: InvitationIn,
    session: SessionDep,
    user: CurrentUser,
    org: OrgDep,
    _admin: AdminDep,
) -> InvitationOut:
    if body.department_id is not None:
        dept = await session.get(Department, body.department_id)
        # Только свой отдел: чужой id создал бы приглашение в подразделение
        # другой организации, а человек получил бы доступ к чужой структуре.
        if dept is None or dept.org_id != org.id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="department_not_found"
            )
    try:
        row, token = await invitations.create(
            session,
            org_id=org.id,
            created_by_id=user.id,
            role=body.role,
            email=body.email,
            days=body.days,
            position=body.position,
            department_id=body.department_id,
        )
    except invitations.InvitationsError as exc:
        _fail(exc)

    link = invitations.invite_link(token)
    mail_sent = False
    if row.email:
        message = mail.invite_email(to=row.email, org_name=org.name, link=link)
        try:
            # Режим «лог» (транспорт не настроен) не считается отправкой:
            # интерфейс не должен обещать письмо, которого не будет.
            mail_sent = await mail.send(message) != "log"
        except mail.MailError as exc:
            # Ссылка уже создана: управляющий скопирует её вручную. Падать
            # всей ручкой из-за почтового провайдера нельзя.
            log.warning(
                "orgs.invite_mail_failed", error=str(exc), org_id=org.id
            )
    await audit.record(
        session,
        org_id=org.id,
        user=user,
        action="invitation.created",
        target_type="invitation",
        target_id=row.id,
        details={"role": row.role, "email": row.email},
    )
    await session.commit()
    return await _out(session, row, link=link, mail_sent=mail_sent)


@router.delete(
    "/org/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_invitation(
    invitation_id: int,
    session: SessionDep,
    user: CurrentUser,
    org: OrgDep,
    _admin: AdminDep,
) -> Response:
    try:
        await invitations.revoke(
            session, org_id=org.id, invitation_id=invitation_id
        )
    except invitations.InvitationsError as exc:
        _fail(exc)
    await audit.record(
        session,
        org_id=org.id,
        user=user,
        action="invitation.revoked",
        target_type="invitation",
        target_id=invitation_id,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/invitations/{token}", response_model=InvitationPreview)
async def preview_invitation(token: str, session: SessionDep) -> InvitationPreview:
    """Публично: что за организация зовёт, на какую роль и до какого срока."""
    try:
        row, org = await invitations.preview(session, token)
    except invitations.InvitationsError as exc:
        _fail(exc)
    return InvitationPreview(
        org_name=org.name,
        role=row.role,
        email=row.email,
        expires_at=_iso(row.expires_at) or "",
        position=row.position,
        department_name=await _department_name(session, row.department_id),
    )


@router.post("/invitations/{token}/accept", response_model=AcceptOut)
async def accept_invitation(
    token: str, session: SessionDep, user: CurrentUser
) -> AcceptOut:
    try:
        org, role = await invitations.accept(session, token=token, user=user)
    except invitations.InvitationsError as exc:
        _fail(exc)
    return AcceptOut(ok=True, org_id=org.id, org_name=org.name, role=role)


# ---------------------------------------------------------------------------
# Приватность (B2B_PLATFORM_PLAN, шаг 5.5)
#
# Клиент вправе забрать свои данные и уйти. Оба действия — только владельцу:
# выгрузка отдаёт людей с почтами, а удаление необратимо. Роль берём из
# членства в запросе (`org` из сотрудника), поэтому чужую организацию
# выгрузить нельзя даже зная её код.
# ---------------------------------------------------------------------------


class RetentionOut(BaseModel):
    """Сроки хранения. Те же числа, что в `docs/PRIVACY.md`."""

    audit_days: int
    deletion_grace_days: int
    fired_trash_days: int
    backup_artifact_days: int


class DeletionOut(BaseModel):
    deleted: bool
    deleted_at: str | None
    purge_after: str | None
    days_left: int | None


class PrivacyOut(BaseModel):
    # Код нужен экрану для подтверждения удаления: человек вводит его
    # руками, а не нажимает «да» в диалоге.
    slug: str
    retention: RetentionOut
    deletion: DeletionOut


class DeleteOrgIn(BaseModel):
    """Подтверждение кодом организации: «удалить» без кода слишком дёшево."""

    confirm: str = Field(min_length=1, max_length=120)


class AuditEventOut(BaseModel):
    id: int
    action: str
    actor_name: str | None
    target_type: str | None
    target_id: str | None
    details: str | None
    created_at: str | None


async def _require_owner(
    session: SessionDep, org: OrgDep, user: CurrentUser
) -> None:
    row = await orgs.member(session, org_id=org.id, user_id=user.id)
    if row is None or row.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="owner_required")


@router.get("/org/privacy", response_model=PrivacyOut)
async def organization_privacy(org: OrgDep, _admin: AdminDep) -> PrivacyOut:
    """Сроки хранения и состояние удаления — для экрана кабинета."""
    return PrivacyOut(
        slug=org.slug,
        retention=RetentionOut(**privacy.retention()),
        deletion=DeletionOut(**privacy.state(org)),
    )


@router.get("/org/export")
async def export_organization(
    session: SessionDep, user: CurrentUser, org: OrgDep, _admin: AdminDep
) -> JSONResponse:
    """Выгрузка структуры и людей организации в JSON-файл.

    `Cache-Control: no-store` здесь не формальность: в файле почты и имена,
    и промежуточный прокси не должен их кэшировать.
    """
    await _require_owner(session, org, user)
    data = await privacy.export_org(session, org)
    await audit.record(
        session,
        org_id=org.id,
        user=user,
        action="data.exported",
        target_type="organization",
        target_id=org.id,
        details={
            "members": len(data["members"]),
            "employees": len(data["employees"]),
        },
    )
    await session.commit()
    filename = f"org-{org.slug}-{datetime.now(timezone.utc):%Y%m%d}.json"
    return JSONResponse(
        data,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("/org", response_model=DeletionOut)
async def delete_organization(
    body: DeleteOrgIn,
    session: SessionDep,
    user: CurrentUser,
    org: OrgDep,
    _admin: AdminDep,
) -> DeletionOut:
    """Запросить удаление организации. Данные исчезнут через 30 дней."""
    await _require_owner(session, org, user)
    try:
        await privacy.request_deletion(
            session, org, confirm=body.confirm, user=user
        )
    except privacy.PrivacyError as exc:
        _fail(exc)
    log.info("orgs.delete_requested", org_id=org.id, by=user.id)
    return DeletionOut(**privacy.state(org))


@router.post("/org/restore", response_model=DeletionOut)
async def restore_organization(
    session: SessionDep,
    user: CurrentUser,
    org: OrgDep,
    _admin: AdminDep,
) -> DeletionOut:
    """Отменить запланированное удаление, пока срок не вышел."""
    await _require_owner(session, org, user)
    try:
        await privacy.cancel_deletion(session, org, user=user)
    except privacy.PrivacyError as exc:
        _fail(exc)
    log.info("orgs.delete_canceled", org_id=org.id, by=user.id)
    return DeletionOut(**privacy.state(org))


@router.get("/org/audit", response_model=list[AuditEventOut])
async def organization_audit(
    session: SessionDep,
    org: OrgDep,
    _admin: AdminDep,
    limit: int = 50,
) -> list[AuditEventOut]:
    """Кто и когда выгружал данные и менял доступы.

    Только руководителю: журнал показывает имена и действия коллег.
    """
    rows = await audit.events(session, org.id, limit=limit)
    return [
        AuditEventOut(
            id=row.id,
            action=row.action,
            actor_name=row.actor_name,
            target_type=row.target_type,
            target_id=row.target_id,
            details=row.details,
            created_at=_iso(row.created_at),
        )
        for row in rows
    ]
