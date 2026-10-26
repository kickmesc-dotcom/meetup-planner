"""Web push: доставка уведомлений без Telegram (B2B_PLATFORM_PLAN, шаг 2.4).

Зачем. До сих пор напоминание о сроке доходило двумя путями: колокольчик в
приложении (виден, только когда человек его открыл) и личка в Telegram (есть
не у всех — вход по почте как раз для тех, у кого Telegram нет). Push
закрывает дыру: телефон показывает уведомление, даже если приложение закрыто.

Как это работает, коротко:

1. Браузер подписывается на push и отдаёт `endpoint` + два ключа шифрования.
2. Сервер шифрует payload ключами подписки и подписывает запрос ключом VAPID.
3. Push-сервис (FCM, Mozilla, Apple) будит service worker, тот показывает
   уведомление.

Почему без фонового демона. Отправка — обычный HTTPS-запрос из процесса API
и планировщика; отдельного воркера и очереди нет. Пока клиентов единицы,
это дешевле и надёжнее, чем инфраструктура ради инфраструктуры.

Что важно для вызывающего:

* без ключей VAPID сервис молчит (`enabled()` == False) — деградация тихая;
* мёртвая подписка (404/410 от push-сервиса) удаляется сразу: иначе каждая
  отправка тратила бы время на устройство, которого больше нет;
* ошибки отправки не пробрасываются: недоставленный push не должен ронять
  тик планировщика или ручку API.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.hr_models import Employee
from app.db.push_models import PushSubscription

log = structlog.get_logger()

# Так push-сервисы отвечают на удалённую подписку (приложение удалено,
# разрешение отозвано, браузер переустановлен).
GONE_STATUSES = frozenset({404, 410})


def enabled() -> bool:
    """Настроена ли пара VAPID. Без неё подписываться бессмысленно."""
    settings = get_settings()
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def endpoint_hash(endpoint: str) -> str:
    """Стабильный ключ подписки: endpoint длинный, индекс — короткий."""
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


# Куда серверу разрешено ходить по адресу из подписки.
#
# Почему это вообще проверяется (аудит 26.10.2026, S-8). `endpoint` задаёт
# клиент, а запрос по нему делает СЕРВЕР (`pywebpush`) — из контейнера, с нашими
# исходящими адресами и заголовками. Без проверки подписка на
# `http://169.254.169.254/…` или на внутренний адрес хостинга превращает сервер
# в инструмент разведки чужой сети (SSRF). Список хостов намеренно белый:
# это три публичных push-сервиса, которые реально используются браузерами.
ALLOWED_PUSH_HOSTS: tuple[str, ...] = (
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "push.services.mozilla.com",
    "web.push.apple.com",
    "push.apple.com",
    ".notify.windows.com",
    ".push.apple.com",
    ".googleapis.com",
    ".mozilla.com",
    ".windows.com",
    ".microsoft.com",
)


def endpoint_is_allowed(endpoint: str) -> bool:
    """Годится ли адрес push-подписки для серверного запроса.

    Разрешаем: только `https`, без логина/пароля в URL, без своего порта, с
    публичным хостом по DNS-имени (без IP-литералов вообще — адрес вида
    `https://10.0.0.5/` не должен проходить, даже если кто-то выпустил на него
    сертификат) и только из белого списка push-сервисов.
    """
    raw = (endpoint or "").strip()
    if len(raw) > 2000:
        return False
    parts = urlsplit(raw)
    if parts.scheme != "https":
        return False
    if parts.username or parts.password:
        return False
    if parts.port not in (None, 443):
        return False
    host = (parts.hostname or "").strip().strip(".").lower()
    if not host or not parts.path:
        return False
    # IP-литерал (в том числе `[::1]`) — отказ: push-сервисы по IP не живут.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return False
    return any(
        host == allowed.lstrip(".") if not allowed.startswith(".") else host.endswith(allowed)
        for allowed in ALLOWED_PUSH_HOSTS
    )


@dataclass(frozen=True)
class PushPayload:
    """То, что увидит человек. Текст короткий: уведомление, а не отчёт."""

    title: str
    body: str
    url: str = "/"
    tag: str | None = None

    def as_json(self) -> str:
        data: dict[str, str] = {"title": self.title, "body": self.body, "url": self.url}
        if self.tag:
            # Одинаковый tag заменяет предыдущее уведомление, а не копит их:
            # пять напоминаний об одной задаче не нужны.
            data["tag"] = self.tag
        return json.dumps(data, ensure_ascii=False)


async def subscriptions_for(
    session: AsyncSession, user_ids: list[int]
) -> list[PushSubscription]:
    """Живые подписки этих пользователей в текущей организации."""
    if not user_ids:
        return []
    rows = await session.scalars(
        select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))
    )
    return list(rows.all())


async def subscribed_user_ids(
    session: AsyncSession, user_ids: list[int]
) -> set[int]:
    """У кого есть хотя бы одно устройство с push (для выбора канала доставки)."""
    return {int(sub.user_id) for sub in await subscriptions_for(session, user_ids)}


def _send_one(sub: PushSubscription, payload: str) -> int | None:
    """Отправить одно сообщение. Возвращает HTTP-статус отказа или None.

    Выполняется в потоке: `pywebpush` синхронный (requests + шифрование).
    Импорт внутри функции — чтобы хост без пакета поднимался, а не падал.
    """
    from pywebpush import WebPushException, webpush

    settings = get_settings()
    info = {
        "endpoint": sub.endpoint,
        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
    }
    try:
        webpush(
            subscription_info=info,
            data=payload,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            timeout=15,
        )
        return None
    except WebPushException as exc:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        log.info("push.rejected", status=status, endpoint=sub.endpoint_hash[:8])
        return int(status) if status else 0
    except Exception as exc:  # noqa: BLE001 — push не имеет права ронять тик
        log.warning("push.failed", error=exc.__class__.__name__)
        return -1


async def send(
    session: AsyncSession,
    *,
    subscriptions: list[PushSubscription],
    title: str,
    body: str,
    url: str = "/",
    tag: str | None = None,
) -> int:
    """Разослать уведомление. Возвращает число доставленных.

    Мёртвые подписки удаляются. `last_seen_at` обновляется пачкой, без коммита:
    вызывающий и так коммитит свою транзакцию (уведомления в приложении уже
    добавлены в неё).
    """
    if not subscriptions or not enabled():
        return 0
    # Проверка на отправке, а не только на подписке: строки могли быть заведены
    # до проверки адреса, а схема «сервер сам ходит по строке из базы» требует
    # одного и того же правила в обоих местах (аудит 26.10.2026, S-8).
    subscriptions = [sub for sub in subscriptions if endpoint_is_allowed(sub.endpoint)]
    if not subscriptions:
        return 0
    payload = PushPayload(title=title, body=body, url=url, tag=tag).as_json()
    results = await asyncio.gather(
        *(asyncio.to_thread(_send_one, sub, payload) for sub in subscriptions)
    )
    sent = 0
    dead: list[PushSubscription] = []
    alive_ids: list[int] = []
    for sub, status in zip(subscriptions, results, strict=True):
        if status is None:
            sent += 1
            alive_ids.append(int(sub.id))
        elif status in GONE_STATUSES:
            dead.append(sub)
    for sub in dead:
        await session.delete(sub)
    if alive_ids:
        await session.execute(
            update(PushSubscription)
            .where(PushSubscription.id.in_(alive_ids))
            .values(last_seen_at=datetime.now(UTC))
        )
    if dead or sent:
        log.info("push.sent", sent=sent, dead=len(dead))
    return sent


async def send_to_employees(
    session: AsyncSession,
    employees: list[Employee],
    *,
    title: str,
    body: str,
    url: str = "/",
    tag: str | None = None,
) -> int:
    """Разослать всем устройствам этих сотрудников (теневые — пропускаем)."""
    if not enabled():
        return 0
    recipients = [e for e in employees if not e.is_simulation]
    subs = await subscriptions_for(session, [e.user_id for e in recipients])
    return await send(
        session, subscriptions=subs, title=title, body=body, url=url, tag=tag
    )


def is_gone(status: int | None) -> bool:
    """Публичная проверка для тестов: считать ли ответ признаком мёртвой подписки."""
    return status in GONE_STATUSES
