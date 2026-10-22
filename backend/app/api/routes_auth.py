"""Вход по почте: регистрация, вход, выход, сброс (шаг 2.1).

Правила, которые видны именно здесь:

* `/auth/password/reset/request` всегда отвечает `ok`, даже если адреса нет:
  иначе ручка рассказывает, кто зарегистрирован;
* ошибки входа не различают «нет адреса» и «неверный пароль»;
* токен сессии показывается ровно один раз — в ответе на вход/регистрацию,
  дальше он живёт только у клиента, в базе лежит его SHA-256;
* смена пароля гасит все входы, включая тот, с которого её сделали.
"""

from __future__ import annotations

from typing import Annotated, NoReturn

import structlog
from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.schemas.user import UserOut
from app.services import accounts, mail

log = structlog.get_logger()
router = APIRouter(tags=["auth"])

# Коды, которые клиент показывает человеку как есть (перевод — на фронте).
_BAD_REQUEST = {
    "bad_email",
    "password_too_short",
    "password_too_long",
    "password_has_spaces",
    "reset_invalid",
    "reset_expired",
}


class RegisterIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=accounts.MAX_PASSWORD)
    display_name: str | None = Field(default=None, max_length=64)


class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=accounts.MAX_PASSWORD)


class SessionOut(BaseModel):
    token: str
    expires_at: str
    user: UserOut


class ResetRequestIn(BaseModel):
    email: str = Field(max_length=255)


class ResetConfirmIn(BaseModel):
    token: str = Field(min_length=10, max_length=128)
    password: str = Field(max_length=accounts.MAX_PASSWORD)


class DeviceOut(BaseModel):
    id: int
    created_at: str | None
    last_seen_at: str | None
    expires_at: str | None
    user_agent: str | None
    current: bool = False


def _iso(value) -> str | None:  # noqa: ANN001
    return value.isoformat() if value is not None else None


async def _session_response(
    session: AsyncSession, user, *, user_agent: str | None
) -> SessionOut:  # noqa: ANN001
    row, token = await accounts.create_session(
        session, user, user_agent=user_agent
    )
    return SessionOut(
        token=token,
        expires_at=_iso(row.expires_at) or "",
        user=UserOut.model_validate(user),
    )


def _raise_http(exc: accounts.AccountsError) -> NoReturn:
    code = str(exc)
    if code in _BAD_REQUEST:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=code)
    if code == "email_taken":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=code)
    if code in {"invalid_credentials", "password_not_set"}:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=code)
    raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=code)


@router.post(
    "/auth/register", response_model=SessionOut, status_code=status.HTTP_201_CREATED
)
async def register(
    body: RegisterIn,
    session: SessionDep,
    user_agent: Annotated[str | None, Header()] = None,
) -> SessionOut:
    try:
        user = await accounts.register(
            session,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
    except accounts.AccountsError as exc:
        _raise_http(exc)
    return await _session_response(session, user, user_agent=user_agent)


@router.post("/auth/login", response_model=SessionOut)
async def login(
    body: LoginIn,
    session: SessionDep,
    user_agent: Annotated[str | None, Header()] = None,
) -> SessionOut:
    try:
        user = await accounts.authenticate(
            session, email=body.email, password=body.password
        )
    except accounts.AccountsError as exc:
        _raise_http(exc)
    return await _session_response(session, user, user_agent=user_agent)


@router.post("/auth/logout")
async def logout(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    token = _bearer(authorization)
    if token:
        await accounts.revoke_token(session, token)
    return {"ok": True}


@router.post("/auth/logout-all")
async def logout_all(session: SessionDep, user: CurrentUser) -> dict[str, int]:
    return {"revoked": await accounts.revoke_all(session, user.id)}


@router.get("/auth/sessions", response_model=list[DeviceOut])
async def devices(
    session: SessionDep,
    user: CurrentUser,
    authorization: Annotated[str | None, Header()] = None,
) -> list[DeviceOut]:
    current_token = _bearer(authorization)
    current_hash = accounts.token_hash(current_token) if current_token else None
    rows = await accounts.active_sessions(session, user.id)
    return [
        DeviceOut(
            id=row.id,
            created_at=_iso(row.created_at),
            last_seen_at=_iso(row.last_seen_at),
            expires_at=_iso(row.expires_at),
            user_agent=row.user_agent,
            current=row.token_hash == current_hash,
        )
        for row in rows
    ]


@router.delete("/auth/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(
    session_id: int, session: SessionDep, user: CurrentUser
) -> Response:
    rows = await accounts.active_sessions(session, user.id)
    target = next((row for row in rows if row.id == session_id), None)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="session_not_found")
    await accounts.revoke(session, target)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/auth/password/reset/request")
async def request_reset(body: ResetRequestIn, session: SessionDep) -> dict[str, bool]:
    """Всегда `ok: true` — существование адреса не подтверждаем."""
    user, token = await accounts.request_reset(session, body.email)
    if user is None or token is None:
        return {"ok": True}
    message = mail.reset_email(
        to=user.email or "",
        link=accounts.reset_link(token),
        minutes=int(accounts.RESET_TTL.total_seconds() // 60),
    )
    try:
        await mail.send(message)
    except mail.MailError as exc:
        # Письмо не ушло, но человеку всё равно говорим «проверьте почту»:
        # иначе по ответу можно перебирать адреса. В журнале — причина.
        log.warning("auth.reset_mail_failed", error=str(exc), user_id=user.id)
    return {"ok": True}


@router.post("/auth/password/reset/confirm")
async def confirm_reset(body: ResetConfirmIn, session: SessionDep) -> dict[str, bool]:
    try:
        await accounts.confirm_reset(
            session, token=body.token, password=body.password
        )
    except accounts.AccountsError as exc:
        _raise_http(exc)
    return {"ok": True}


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()
