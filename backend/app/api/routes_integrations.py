"""Управление ключами API и вебхуками из кабинета (шаг 6.1).

Зачем только владелец. Ключ открывает данные всех людей организации, а вебхук
отправляет их на внешний адрес. Управляющий, который может править смены, не
должен иметь возможность выписать доступ наружу: это решение уровня владельца,
как выгрузка и удаление (шаг 5.5).

Почему секрет и токен показываются один раз. В базе лежат только хеши; если
показать их повторно, хранить хеш не имело бы смысла. Потерянный ключ
выпускается заново, отозванный перестаёт работать сразу.

Почему журнал доставок читается здесь же. Интегратор звонит «вебхуки не
приходят», и руководитель должен ответить за один экран: что отправляли, когда,
какой код вернул приёмник. Без этого разбор начинается с чужой стороны.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, OrgDep, SessionDep
from app.db.models import User
from app.services import api_keys, audit, orgs, webhooks

router = APIRouter(tags=["integrations"])


class ApiKeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreatedOut(BaseModel):
    key: ApiKeyOut
    # Единственный раз, когда ключ виден целиком.
    token: str


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[str] | None = None


class WebhookOut(BaseModel):
    id: int
    url: str
    events: list[str]
    is_active: bool
    created_at: datetime
    last_attempt_at: datetime | None
    last_status_code: int | None
    failures: int


class WebhookCreatedOut(BaseModel):
    webhook: WebhookOut
    secret: str


class WebhookIn(BaseModel):
    url: str = Field(min_length=4, max_length=2000)
    events: list[str] | None = None


class WebhookPatchIn(BaseModel):
    url: str | None = Field(default=None, max_length=2000)
    events: list[str] | None = None
    is_active: bool | None = None


class DeliveryOut(BaseModel):
    id: int
    endpoint_id: int
    event: str
    status: str
    attempts: int
    response_code: int | None
    error: str | None
    created_at: datetime
    delivered_at: datetime | None


async def _owner(session: AsyncSession, org, user: User) -> None:
    row = await orgs.member(session, org_id=org.id, user_id=user.id)
    if row is None or row.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="owner_required")


def _key_out(key) -> ApiKeyOut:
    return ApiKeyOut(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        scopes=list(api_keys.scopes_of(key)),
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
    )


def _hook_out(hook) -> WebhookOut:
    return WebhookOut(
        id=hook.id,
        url=hook.url,
        events=list(webhooks.events_of(hook)),
        is_active=hook.is_active,
        created_at=hook.created_at,
        last_attempt_at=hook.last_attempt_at,
        last_status_code=hook.last_status_code,
        failures=hook.failures,
    )


def _hook_error(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ---------------------------------------------------------------------------
# Ключи API
# ---------------------------------------------------------------------------


@router.get("/org/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(
    session: SessionDep, org: OrgDep, user: CurrentUser
) -> list[ApiKeyOut]:
    await _owner(session, org, user)
    rows = await api_keys.for_org(session, org.id)
    return [_key_out(row) for row in rows]


@router.post(
    "/org/api-keys", response_model=ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED
)
async def create_api_key(
    payload: ApiKeyIn, session: SessionDep, org: OrgDep, user: CurrentUser
) -> ApiKeyCreatedOut:
    await _owner(session, org, user)
    try:
        key, token = await api_keys.create(
            session,
            org_id=org.id,
            name=payload.name,
            scopes=payload.scopes,
            user=user,
        )
    except api_keys.ApiKeyError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    await audit.record(
        session,
        org_id=org.id,
        action="api_key.created",
        user=user,
        target_type="api_key",
        target_id=key.id,
        details={"name": key.name, "scopes": list(api_keys.scopes_of(key))},
    )
    await session.commit()
    await session.refresh(key)
    return ApiKeyCreatedOut(key=_key_out(key), token=token)


@router.delete("/org/api-keys/{key_id}", response_model=ApiKeyOut)
async def revoke_api_key(
    key_id: int, session: SessionDep, org: OrgDep, user: CurrentUser
) -> ApiKeyOut:
    await _owner(session, org, user)
    key = await api_keys.revoke(session, org.id, key_id)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="key_not_found")
    await audit.record(
        session,
        org_id=org.id,
        action="api_key.revoked",
        user=user,
        target_type="api_key",
        target_id=key.id,
        details={"name": key.name},
    )
    await session.commit()
    await session.refresh(key)
    return _key_out(key)


# ---------------------------------------------------------------------------
# Вебхуки
# ---------------------------------------------------------------------------


@router.get("/org/webhooks", response_model=list[WebhookOut])
async def list_webhooks(
    session: SessionDep, org: OrgDep, user: CurrentUser
) -> list[WebhookOut]:
    await _owner(session, org, user)
    rows = await webhooks.endpoints(session, org.id)
    return [_hook_out(row) for row in rows]


@router.post(
    "/org/webhooks",
    response_model=WebhookCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook(
    payload: WebhookIn, session: SessionDep, org: OrgDep, user: CurrentUser
) -> WebhookCreatedOut:
    await _owner(session, org, user)
    try:
        hook, secret = await webhooks.add_endpoint(
            session,
            org_id=org.id,
            url=payload.url,
            events=payload.events,
            user=user,
        )
    except webhooks.WebhookError as exc:
        raise _hook_error(exc) from exc
    await audit.record(
        session,
        org_id=org.id,
        action="webhook.created",
        user=user,
        target_type="webhook",
        target_id=hook.id,
        details={"url": hook.url, "events": list(webhooks.events_of(hook))},
    )
    await session.commit()
    await session.refresh(hook)
    return WebhookCreatedOut(webhook=_hook_out(hook), secret=secret)


@router.patch("/org/webhooks/{hook_id}", response_model=WebhookOut)
async def patch_webhook(
    hook_id: int,
    payload: WebhookPatchIn,
    session: SessionDep,
    org: OrgDep,
    user: CurrentUser,
) -> WebhookOut:
    await _owner(session, org, user)
    hook = await webhooks.get_endpoint(session, org.id, hook_id)
    if hook is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="webhook_not_found")
    try:
        await webhooks.update_endpoint(
            session,
            hook,
            url=payload.url,
            events=payload.events,
            is_active=payload.is_active,
        )
    except webhooks.WebhookError as exc:
        raise _hook_error(exc) from exc
    await audit.record(
        session,
        org_id=org.id,
        action="webhook.updated",
        user=user,
        target_type="webhook",
        target_id=hook.id,
        details={
            "url": hook.url,
            "events": list(webhooks.events_of(hook)),
            "is_active": hook.is_active,
        },
    )
    await session.commit()
    await session.refresh(hook)
    return _hook_out(hook)


@router.delete("/org/webhooks/{hook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_webhook(
    hook_id: int, session: SessionDep, org: OrgDep, user: CurrentUser
) -> None:
    await _owner(session, org, user)
    hook = await webhooks.get_endpoint(session, org.id, hook_id)
    removed = await webhooks.delete_endpoint(session, org.id, hook_id)
    if not removed or hook is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="webhook_not_found")
    await audit.record(
        session,
        org_id=org.id,
        action="webhook.deleted",
        user=user,
        target_type="webhook",
        target_id=hook_id,
        details={"url": hook.url},
    )
    await session.commit()


@router.get("/org/webhooks/deliveries", response_model=list[DeliveryOut])
async def webhook_deliveries(
    session: SessionDep,
    org: OrgDep,
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[DeliveryOut]:
    await _owner(session, org, user)
    rows = await webhooks.deliveries(session, org.id, limit=limit)
    return [
        DeliveryOut(
            id=row.id,
            endpoint_id=row.endpoint_id,
            event=row.event,
            status=row.status,
            attempts=row.attempts,
            response_code=row.response_code,
            error=row.error,
            created_at=row.created_at,
            delivered_at=row.delivered_at,
        )
        for row in rows
    ]


__all__ = ["router"]
