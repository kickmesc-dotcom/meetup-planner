"""Вебхуки организации: события наружу, подпись, повторы (шаг 6.1).

Зачем вебхуки, если есть публичный API. Интегратору нужно не «спросить про
людей раз в час», а узнать сразу: новый сотрудник появился, смена изменилась.
Опрос раз в час — это часовое опоздание в CRM и лишние запросы, которые
упираются в лимит частоты.

Почему доставка отложенная, а не в момент события. Приёмник может лежать, а
запрос человека не должен ждать чужой сервер: событие сохраняется в очередь и
уходит из планировщика. Повтор отправляет тот же снимок тела (`payload`), а не
пересобранные данные — иначе интегратор получил бы «сотрудник создан» с уже
изменённой должностью.

Почему подпись HMAC. URL вебхука — не секрет: он может утечь из логов
приёмника. Подпись `X-SemiTask-Signature` доказывает, что тело отправили мы и
его не подменили по дороге.

Почему https обязателен. По http тело события (имена людей) идёт открытым
текстом, а подпись не защищает от прослушивания. Исключение — локальная
разработка интегратора и тесты, включаемые явно `WEBHOOK_ALLOW_HTTP=1`.

Остаточный риск, названный честно: хост проверяется на литеральный приватный
IP, но DNS может указывать на внутренний адрес. Полная защита от SSRF требует
резолва и проверки адреса перед каждым соединением; это следующий шаг вместе с
исходящим прокси, а не то, что можно тихо считать сделанным.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.org_models import WebhookDelivery, WebhookEndpoint

log = structlog.get_logger()

# События, которые мы действительно шлём. Список закрытый: интегратор
# подписывается на известные имена, а не на «всё, что когда-нибудь появится».
EVENTS: tuple[str, ...] = (
    "employee.created",
    "employee.updated",
    "employee.deactivated",
)

# Сколько попыток и с каким промежутком. Суммарно около девяти часов: за это
# время приёмник либо поднимется, либо интегратор уже узнал о проблеме из
# журнала доставок.
MAX_ATTEMPTS = 5
BACKOFF_SEC: tuple[int, ...] = (60, 300, 1800, 7200, 21600)

# Журнал доставок — не архив. Месяц отвечает на вопрос «что мы слали на той
# неделе» и не растёт бесконечно.
DELIVERY_RETENTION_DAYS = 30

REQUEST_TIMEOUT_SEC = 10.0
MAX_ERROR_LEN = 300


class WebhookError(Exception):
    """Ошибка настройки вебхука: URL или событие не годятся."""


def http_allowed() -> bool:
    return (os.getenv("WEBHOOK_ALLOW_HTTP") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def validate_url(url: str) -> str:
    """Проверить адрес приёмника. Возвращает нормализованный URL."""
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WebhookError("url_invalid")
    if parsed.scheme == "http" and not http_allowed():
        raise WebhookError("url_https_required")
    if parsed.username or parsed.password:
        # Учётные данные в URL попадают в журнал доставок и в наши логи.
        raise WebhookError("url_credentials")
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        if not http_allowed():
            raise WebhookError("url_private")
    else:
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            addr = None
        if addr is not None and (
            addr.is_private or addr.is_loopback or addr.is_link_local
        ):
            raise WebhookError("url_private")
    return raw


def normalize_events(events: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not events:
        return EVENTS
    cleaned: list[str] = []
    for raw in events:
        code = (raw or "").strip()
        if not code:
            continue
        if code not in EVENTS:
            raise WebhookError(f"unknown_event:{code}")
        if code not in cleaned:
            cleaned.append(code)
    if not cleaned:
        return EVENTS
    return tuple(cleaned)


def events_of(endpoint: WebhookEndpoint) -> tuple[str, ...]:
    return tuple(part for part in (endpoint.events or "").split(",") if part)


def sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def add_endpoint(
    session: AsyncSession,
    *,
    org_id: int,
    url: str,
    events: list[str] | tuple[str, ...] | None = None,
    user: User | None = None,
) -> tuple[WebhookEndpoint, str]:
    """Завести приёмник. Секрет возвращается один раз — как ключ API."""
    clean_url = validate_url(url)
    chosen = normalize_events(events)
    secret = secrets.token_urlsafe(32)
    endpoint = WebhookEndpoint(
        org_id=org_id,
        url=clean_url,
        secret=secret,
        events=",".join(chosen),
        created_by_user_id=user.id if user is not None else None,
    )
    session.add(endpoint)
    await session.flush()
    return endpoint, secret


async def endpoints(session: AsyncSession, org_id: int) -> list[WebhookEndpoint]:
    rows = await session.scalars(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.org_id == org_id)
        .order_by(WebhookEndpoint.id.desc())
    )
    return list(rows)


async def get_endpoint(
    session: AsyncSession, org_id: int, endpoint_id: int
) -> WebhookEndpoint | None:
    row = await session.get(WebhookEndpoint, endpoint_id)
    if row is None or row.org_id != org_id:
        return None
    return row


async def update_endpoint(
    session: AsyncSession,
    endpoint: WebhookEndpoint,
    *,
    url: str | None = None,
    events: list[str] | tuple[str, ...] | None = None,
    is_active: bool | None = None,
) -> WebhookEndpoint:
    if url is not None and url.strip() != endpoint.url:
        endpoint.url = validate_url(url)
        # Адрес сменился — прежние неудачи к новому приёмнику не относятся.
        endpoint.failures = 0
        endpoint.last_status_code = None
    if events is not None:
        endpoint.events = ",".join(normalize_events(events))
    if is_active is not None:
        endpoint.is_active = is_active
    await session.flush()
    return endpoint


async def delete_endpoint(
    session: AsyncSession, org_id: int, endpoint_id: int
) -> bool:
    row = await get_endpoint(session, org_id, endpoint_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def deliveries(
    session: AsyncSession, org_id: int, *, limit: int = 50
) -> list[WebhookDelivery]:
    capped = max(1, min(int(limit), 200))
    rows = await session.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.org_id == org_id)
        .order_by(WebhookDelivery.id.desc())
        .limit(capped)
    )
    return list(rows)


async def emit(
    session: AsyncSession,
    *,
    org_id: int,
    event: str,
    data: dict[str, Any],
    now: datetime | None = None,
) -> int:
    """Поставить событие в очередь для всех подписанных приёмников.

    Коммитит вызывающий: событие должно уехать вместе с изменением, а не
    раньше него. Иначе интегратор узнает о сотруднике, которого откатили.
    """
    if event not in EVENTS:
        return 0
    moment = now or datetime.now(timezone.utc)
    subscribed = await session.scalars(
        select(WebhookEndpoint).where(
            WebhookEndpoint.org_id == org_id,
            WebhookEndpoint.is_active.is_(True),
        )
    )
    body = json.dumps(
        {
            "event": event,
            "org_id": org_id,
            "sent_at": moment.isoformat(),
            "data": data,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    queued = 0
    for endpoint in subscribed:
        if event not in events_of(endpoint):
            continue
        session.add(
            WebhookDelivery(
                org_id=org_id,
                endpoint_id=endpoint.id,
                event=event,
                payload=body,
                status="pending",
                attempts=0,
                next_attempt_at=moment,
            )
        )
        queued += 1
    if queued:
        await session.flush()
    return queued


async def _post(
    url: str, body: bytes, headers: dict[str, str]
) -> tuple[int | None, str | None]:
    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SEC, follow_redirects=False
        ) as client:
            response = await client.post(url, content=body, headers=headers)
        return response.status_code, None
    except Exception as exc:  # noqa: BLE001 - чужая сеть не должна ронять tick
        return None, f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LEN]


async def flush(
    session: AsyncSession, *, now: datetime | None = None, limit: int = 50
) -> dict[str, int]:
    """Отправить созревшие доставки. Возвращает счётчики для лога."""
    moment = now or datetime.now(timezone.utc)
    rows = list(
        await session.scalars(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status == "pending",
                WebhookDelivery.next_attempt_at <= moment,
            )
            .order_by(WebhookDelivery.id)
            .limit(max(1, min(int(limit), 200)))
        )
    )
    sent = retried = failed = 0
    for delivery in rows:
        endpoint = await session.get(WebhookEndpoint, delivery.endpoint_id)
        if endpoint is None or not endpoint.is_active:
            delivery.status = "failed"
            delivery.error = "endpoint_inactive"[:MAX_ERROR_LEN]
            failed += 1
            continue
        body = delivery.payload.encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SemiTaskBot-Webhooks/1",
            "X-SemiTask-Event": delivery.event,
            "X-SemiTask-Delivery": str(delivery.id),
            "X-SemiTask-Signature": sign(endpoint.secret, body),
        }
        code, error = await _post(endpoint.url, body, headers)
        endpoint.last_attempt_at = moment
        endpoint.last_status_code = code
        delivery.response_code = code
        delivery.attempts += 1
        if code is not None and 200 <= code < 300:
            delivery.status = "sent"
            delivery.delivered_at = moment
            delivery.error = None
            endpoint.failures = 0
            sent += 1
            continue
        endpoint.failures = (endpoint.failures or 0) + 1
        delivery.error = (error or f"http_{code}")[:MAX_ERROR_LEN]
        if delivery.attempts >= MAX_ATTEMPTS:
            delivery.status = "failed"
            failed += 1
        else:
            delay = BACKOFF_SEC[min(delivery.attempts - 1, len(BACKOFF_SEC) - 1)]
            delivery.next_attempt_at = moment + timedelta(seconds=delay)
            retried += 1
    if sent or retried or failed:
        log.info(
            "webhooks.flush_done", sent=sent, retried=retried, failed=failed
        )
    return {"sent": sent, "retried": retried, "failed": failed}


async def prune(session: AsyncSession, *, now: datetime | None = None) -> int:
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=DELIVERY_RETENTION_DAYS)
    result = await session.execute(
        delete(WebhookDelivery).where(WebhookDelivery.created_at < cutoff)
    )
    await session.commit()
    return int(result.rowcount or 0)


__all__ = [
    "BACKOFF_SEC",
    "DELIVERY_RETENTION_DAYS",
    "EVENTS",
    "MAX_ATTEMPTS",
    "WebhookError",
    "add_endpoint",
    "delete_endpoint",
    "deliveries",
    "emit",
    "endpoints",
    "events_of",
    "flush",
    "get_endpoint",
    "normalize_events",
    "prune",
    "sign",
    "update_endpoint",
    "validate_url",
]
