"""Свой домен организации (план: филиалы и домены, 06.11.2026).

Зачем. Сейчас у всех один адрес `*.pages.dev`: для сети это выглядит как
«какой-то бот», а не как приложение салона. Сотрудник должен открывать
`cabinet.salon.ru`, а платформенная ссылка остаётся запасной.

Почему домен подтверждается файлом, а не «просто сохраняется». Домен — это
чужое имя в интернете. Если принимать его на слово, первый же человек занял бы
`cabinet.sber.ru` и сломал вход настоящему владельцу. Поэтому у домена есть
токен, а контроль доказывается файлом по адресу `/.well-known/semitask-domain.txt`
на этом же домене: он одновременно проверяет, что домен указывает на нас и что
сертификат выпущен.

Почему проверка — HTTPS-запрос, а не DNS. CNAME настраивает владелец, но
резолвер в контейнере может кешировать и врать; HTTPS-запрос идёт туда же,
куда пойдёт браузер сотрудника, и проверяет ровно то, что нужно.

Почему `verified_at` сбрасывается при смене домена. Токен привязан к домену:
старая наклейка на прежнем адресе ничего не подтверждает.

Остаточный риск назван честно: литеральный приватный IP отсекается, но DNS
может указывать на внутренний адрес. Полная защита от SSRF требует резолва и
проверки адреса перед каждым соединением — это следующий шаг вместе с
исходящим прокси, как и у вебхуков.
"""

from __future__ import annotations

import ipaddress
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable
from urllib.parse import urlsplit

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.org_models import Organization

log = structlog.get_logger()

MAX_DOMAIN = 253
MIN_DOMAIN = 4
TOKEN_BYTES = 18
VERIFY_PATH = "/.well-known/semitask-domain.txt"
VERIFY_TIMEOUT = 8.0
# Префикс в файле, чтобы владелец мог положить туда ещё что-то своё.
VERIFY_PREFIX = "semitask-domain="

# Платформенные адреса: занять их клиенту нельзя — иначе он «присвоит» наш
# собственный вход и сломает его остальным.
RESERVED_SUFFIXES: tuple[str, ...] = ("pages.dev", "amvera.tech")

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")

# Подменяется в тестах: сеть в тестах не поднимаем.
Fetcher = Callable[[str], Awaitable[str]]


class DomainError(Exception):
    """Отказ по домену. Строка — код: перевод живёт на фронте."""


@dataclass(frozen=True)
class DomainState:
    domain: str | None
    token: str | None
    verified: bool
    checked_at: datetime | None
    #: Что именно создать на домене. Отдаём фронту, чтобы инструкция и
    #: проверка не разъехались.
    verify_path: str = VERIFY_PATH
    verify_prefix: str = VERIFY_PREFIX


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def normalize(raw: str) -> str:
    """Привести домен к виду `salon.ru` или отказать.

    Принимаем то, что человек копирует из панели регистратора: со схемой,
    путём и точкой на конце. Храним только имя — иначе `https://salon.ru/` и
    `salon.ru` стали бы двумя разными доменами.
    """
    value = (raw or "").strip().lower()
    if not value:
        raise DomainError("bad_domain")
    if "://" in value:
        value = (urlsplit(value).hostname or "").lower()
    value = value.split("/")[0].split("?")[0].split("#")[0].strip().rstrip(".")
    if not (MIN_DOMAIN <= len(value) <= MAX_DOMAIN):
        raise DomainError("bad_domain")
    # IP-литерал — не домен: клиенту нужен адрес, который он сможет
    # перенести к другому провайдеру, а сертификат на IP не выдаётся.
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise DomainError("bad_domain")
    try:
        ascii_value = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise DomainError("bad_domain") from exc
    labels = ascii_value.split(".")
    if len(labels) < 2:
        raise DomainError("bad_domain")
    for label in labels:
        if not _LABEL.fullmatch(label):
            raise DomainError("bad_domain")
    if labels[-1].isdigit() or len(labels[-1]) < 2:
        raise DomainError("bad_domain")
    if any(
        ascii_value == suffix or ascii_value.endswith("." + suffix)
        for suffix in RESERVED_SUFFIXES
    ):
        raise DomainError("domain_reserved")
    return ascii_value


def state(org: Organization) -> DomainState:
    return DomainState(
        domain=org.custom_domain or None,
        token=org.custom_domain_token or None,
        verified=org.custom_domain_verified_at is not None,
        checked_at=org.custom_domain_checked_at,
    )


async def set_domain(
    session: AsyncSession, org: Organization, raw: str
) -> DomainState:
    """Сохранить домен и выдать новый токен.

    Токен меняется только при смене домена: повторное сохранение того же
    адреса не должно обнулять уже подтверждённый контроль.
    """
    value = normalize(raw)
    taken = await session.scalar(
        select(Organization.id).where(
            Organization.custom_domain == value,
            Organization.id != org.id,
        )
    )
    if taken is not None:
        raise DomainError("domain_taken")
    if org.custom_domain != value:
        org.custom_domain = value
        org.custom_domain_token = new_token()
        org.custom_domain_verified_at = None
        org.custom_domain_checked_at = None
    elif not org.custom_domain_token:
        org.custom_domain_token = new_token()
    await session.commit()
    await session.refresh(org)
    return state(org)


async def clear(session: AsyncSession, org: Organization) -> DomainState:
    org.custom_domain = None
    org.custom_domain_token = None
    org.custom_domain_verified_at = None
    org.custom_domain_checked_at = None
    await session.commit()
    await session.refresh(org)
    return state(org)


async def _fetch_text(url: str) -> str:
    """Прочитать файл проверки. Отдельная функция — тест подменяет её."""
    async with httpx.AsyncClient(
        timeout=VERIFY_TIMEOUT, follow_redirects=False
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def verify_domain(
    session: AsyncSession,
    org: Organization,
    *,
    fetch: Fetcher | None = None,
) -> DomainState:
    """Проверить контроль над доменом файлом с токеном."""
    domain = org.custom_domain
    token = org.custom_domain_token
    if not domain or not token:
        raise DomainError("domain_not_set")
    url = f"https://{domain}{VERIFY_PATH}"
    try:
        text = await (fetch or _fetch_text)(url)
    except (httpx.HTTPError, OSError) as exc:
        raise DomainError("verify_failed") from exc
    if token not in text:
        raise DomainError("verify_mismatch")
    now = datetime.now(timezone.utc)
    org.custom_domain_verified_at = now
    org.custom_domain_checked_at = now
    await session.commit()
    await session.refresh(org)
    log.info("org.domain_verified", org_id=org.id, domain=domain)
    return state(org)
