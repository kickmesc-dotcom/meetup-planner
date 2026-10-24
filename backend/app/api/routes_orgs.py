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
from typing import Annotated, NoReturn

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.deps import AdminDep, CurrentUser, SessionDep, current_org
from app.db.org_models import INDUSTRIES, Organization
from app.services import invitations, mail, orgs

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


class InvitationIn(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    role: str = Field(default="staff", max_length=16)
    days: int = Field(default=invitations.INVITE_TTL_DAYS, ge=1, le=invitations.MAX_TTL_DAYS)


class InvitationOut(BaseModel):
    id: int
    email: str | None
    role: str
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


class AcceptOut(BaseModel):
    ok: bool
    org_id: int
    org_name: str
    role: str


def _iso(value) -> str | None:  # noqa: ANN001
    return value.isoformat() if value is not None else None


def _out(
    row, *, link: str | None = None, mail_sent: bool = False
) -> InvitationOut:  # noqa: ANN001
    return InvitationOut(
        id=row.id,
        email=row.email,
        role=row.role,
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


@router.get("/org/invitations", response_model=list[InvitationOut])
async def list_invitations(
    session: SessionDep, org: OrgDep, _admin: AdminDep
) -> list[InvitationOut]:
    rows = await invitations.active(session, org.id)
    return [_out(row) for row in rows]


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
    try:
        row, token = await invitations.create(
            session,
            org_id=org.id,
            created_by_id=user.id,
            role=body.role,
            email=body.email,
            days=body.days,
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
    return _out(row, link=link, mail_sent=mail_sent)


@router.delete(
    "/org/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_invitation(
    invitation_id: int, session: SessionDep, org: OrgDep, _admin: AdminDep
) -> Response:
    try:
        await invitations.revoke(
            session, org_id=org.id, invitation_id=invitation_id
        )
    except invitations.InvitationsError as exc:
        _fail(exc)
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
