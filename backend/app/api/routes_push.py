"""Web push: подписка браузера и проверка доставки (шаг 2.4).

Ручки намеренно маленькие: подписаться, отписаться, узнать ключ, получить
тестовое уведомление. Никакого «списка всех устройств организации» — подписка
принадлежит человеку и устройству, а не админке.

Почему подписка требует `EmployeeDep`, а не просто входа. Подписка тенантная:
без организации сервер не смог бы отфильтровать, кому в каком клиенте слать
уведомления, а `org_id` в таблице обязателен (страж схемы). Профиль сотрудника
как раз и даёт организацию — и заодно отсекает аккаунт без членства.

Общий браузер. Если на одном устройстве вошли под другим аккаунтом, новая
подписка перепривязывается к нему: иначе прежний человек продолжал бы получать
уведомления чужой смены.
"""

from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.deps import EmployeeDep, SessionDep
from app.db.tenancy import all_orgs
from app.db.push_models import PushSubscription
from app.services import web_push

log = structlog.get_logger()

router = APIRouter(tags=["push"])


class PushConfigOut(BaseModel):
    """Что нужно браузеру, чтобы подписаться. Публичный ключ — не секрет."""

    enabled: bool
    public_key: str


class PushKeysIn(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class PushSubscribeIn(BaseModel):
    # Endpoint — URL push-сервиса; у Chrome бывает 400+ символов.
    endpoint: str = Field(min_length=10, max_length=2000)
    keys: PushKeysIn
    user_agent: str | None = Field(default=None, max_length=500)


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)


class PushStatusOut(BaseModel):
    ok: bool = True
    sent: int = 0


@router.get("/push/config", response_model=PushConfigOut)
async def push_config(_: EmployeeDep) -> PushConfigOut:
    """Включён ли push и с каким ключом подписываться.

    Пустой ключ — штатное состояние «ещё не настроено»: приложение просто не
    показывает переключатель, а не ломается на `applicationServerKey`.
    """
    from app.config import get_settings

    return PushConfigOut(
        enabled=web_push.enabled(), public_key=get_settings().vapid_public_key
    )


@router.post("/push/subscriptions", response_model=PushStatusOut)
async def subscribe_push(
    body: PushSubscribeIn, session: SessionDep, employee: EmployeeDep
) -> PushStatusOut:
    """Сохранить (или обновить) подписку этого браузера."""
    if not web_push.enabled():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="push_disabled")
    digest = web_push.endpoint_hash(body.endpoint)
    # Endpoint уникален глобально, а строка могла остаться от прежней
    # организации того же браузера. Без `all_orgs()` выборка её не увидит и
    # вставка упадёт на уникальном индексе.
    with all_orgs():
        row = await session.scalar(
            select(PushSubscription).where(PushSubscription.endpoint_hash == digest)
        )
    if row is None:
        row = PushSubscription(
            org_id=employee.org_id,
            user_id=employee.user_id,
            endpoint=body.endpoint,
            endpoint_hash=digest,
        )
        session.add(row)
    # Перепривязка на текущего человека: устройство могло сменить владельца.
    row.user_id = employee.user_id
    row.org_id = employee.org_id
    row.p256dh = body.keys.p256dh
    row.auth = body.keys.auth
    row.user_agent = body.user_agent
    await session.commit()
    log.info("push.subscribed", user_id=employee.user_id, device=digest[:8])
    return PushStatusOut()


@router.delete("/push/subscriptions", response_model=PushStatusOut)
async def unsubscribe_push(
    body: PushUnsubscribeIn, session: SessionDep, employee: EmployeeDep
) -> PushStatusOut:
    """Убрать подписку этого браузера. Повторный вызов — не ошибка."""
    await session.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint_hash == web_push.endpoint_hash(body.endpoint),
            PushSubscription.user_id == employee.user_id,
        )
    )
    await session.commit()
    log.info("push.unsubscribed", user_id=employee.user_id)
    return PushStatusOut()


@router.post("/push/test", response_model=PushStatusOut)
async def test_push(session: SessionDep, employee: EmployeeDep) -> PushStatusOut:
    """Проверочное уведомление на свои устройства — чтобы человек убедился сам.

    Без этого «включил и тишина» невозможно отличить от «браузер не доставляет»:
    тест показывает, что цепочка сервер → push-сервис → service worker жива.
    """
    if not web_push.enabled():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="push_disabled")
    subs = await web_push.subscriptions_for(session, [employee.user_id])
    if not subs:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="push_not_subscribed")
    sent = await web_push.send(
        session,
        subscriptions=subs,
        title="SemiTaskBot на связи",
        body="Уведомления включены. Напоминания о сроках придут сюда.",
        url="/",
        tag="push-test",
    )
    await session.commit()
    return PushStatusOut(sent=sent)


class PushDeviceOut(BaseModel):
    id: int
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime | None


@router.get("/push/subscriptions", response_model=list[PushDeviceOut])
async def list_push_subscriptions(
    session: SessionDep, employee: EmployeeDep
) -> list[PushDeviceOut]:
    """Устройства текущего человека: по ним видно, куда реально уходит push.

    Нужен профилю: «включено, но не приходит» чаще всего значит, что подписка
    осталась на старом телефоне.
    """
    subs = await web_push.subscriptions_for(session, [employee.user_id])
    return [
        PushDeviceOut(
            id=int(sub.id),
            user_agent=sub.user_agent,
            created_at=sub.created_at,
            last_seen_at=sub.last_seen_at,
        )
        for sub in subs
    ]
