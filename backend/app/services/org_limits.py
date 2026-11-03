"""Лимиты и квоты организации (B2B_PLATFORM_PLAN, шаг 5.3).

Зачем отдельный сервис. Лимит частоты из `app/api/guards.py` считает по адресу
посетителя. Для публичных ручек это правильно, для рабочих — нет: за одним
офисным NAT сидит целая смена, и клиент с сотней людей получал бы тот же
потолок, что и клиент с пятью. И наоборот: один клиент, разогнавший скрипт,
занимал бы общий API — ровно то, что шаг обязан исключить.

Поэтому здесь два ограничения, и они отвечают на разные вопросы:

* **частота** — сколько запросов в минуту может позволить себе организация.
  Считается после аутентификации, когда организация уже известна; тариф задаёт
  потолок (`Plan.api_rpm`). Ключ — организация, а не IP: перебор адресов
  (`X-Forwarded-For`) не даёт обойти лимит и не наказывает соседей по офису;
* **объём медиа** — сколько байтов фото организация занимает в базе
  (`Plan.storage_mb`). Диск и база — общий ресурс контейнера: одна организация,
  заливающая снимки, не должна приближать отказ остальным.

Почему проверка в зависимостях (`deps.current_user`/`current_employee`), а не в
middleware. В middleware организация ещё неизвестна: её даёт подпись `initData`
или сессия в базе. Разбирать их второй раз значило бы делать ту же работу
дважды на каждом запросе и получить второй источник правды о том, кто пришёл.
Зависимость организацию уже знает, поэтому проверка стоит там. Один запрос
проверяется один раз — за это отвечает флаг `_checked` (см. `begin_request`).

Почему счётчики в памяти. API — один процесс (Amvera), как и у лимитов
периметра. При нескольких репликах потолок станет «на реплику»; честный общий
счёт потребует внешнего хранилища (Redis или таблица) и делается вместе с
горизонтальным масштабированием, а не побочным эффектом.

Почему при недоступной базе запрос пропускаем. Лимит защищает от перегрузки, но
сам не должен становиться отказом: если тариф не прочитался, работаем по
минимальному потолку (`FALLBACK_RPM`), а не по нулю.
"""

from __future__ import annotations

import math
import os
import time
from contextvars import ContextVar

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.guards import SlidingWindowLimiter
from app.db.org_models import ALL_ORGS, Organization
from app.services import billing

log = structlog.get_logger()

# Окно частоты. Минута — привычная клиенту единица и достаточный отрезок, чтобы
# всплеск «обновляю экран в цикле» не растягивался в отказ на весь день.
WINDOW_SEC = 60.0

# Сколько живёт закэшированный тариф. Минута: смена тарифа после оплаты должна
# применяться сразу, а лишний SELECT на каждый запрос не нужен — поле меняется
# раз в месяц.
PLAN_TTL_SEC = 60.0

# Потолок, когда тариф прочитать не удалось. Равен пробному: без базы мы не
# знаем, кому что обещали, и разумнее не пускать больше минимального.
FALLBACK_RPM = 300


class QuotaExceeded(Exception):
    """Место в хранилище кончилось.

    Отдельное исключение, а не `HTTPException`: сервис не знает, каким кодом
    это показывать. `hr_media` переводит его в `MediaError("storage_full")`, а
    роутер — в `413`.
    """

    def __init__(self, used_bytes: int, limit_bytes: int) -> None:
        super().__init__("storage_full")
        self.used_bytes = used_bytes
        self.limit_bytes = limit_bytes


_LIMITER = SlidingWindowLimiter(max_keys=5000)
# org_id -> (момент истечения, код тарифа). Момент по `monotonic`: системные
# часы могут прыгнуть, и кэш тогда либо вечный, либо пустой.
_PLAN_CACHE: dict[int, tuple[float, str]] = {}
# «В этом запросе лимит уже считался». Ставится в начале запроса middleware'ом
# (`main.tenant_scope`) и читается проверками в зависимостях.
_CHECKED: ContextVar[bool] = ContextVar("org_rate_checked", default=False)


def quota_disabled() -> bool:
    """Выключатель для нагрузочных проб: `ORG_QUOTA_OFF=1`."""
    return (os.getenv("ORG_QUOTA_OFF") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def begin_request() -> None:
    """Новый запрос: лимит ещё не считался."""
    _CHECKED.set(False)


def reset_org_limits() -> None:
    """Забыть счётчики и кэш тарифов. Тесты и диагностика."""
    _LIMITER.clear()
    _PLAN_CACHE.clear()
    _CHECKED.set(False)


async def plan_code(session: AsyncSession, org_id: int) -> str | None:
    """Тариф организации с минутным кэшем.

    `None` — тариф неизвестен (база недоступна). Это не ошибка запроса: вызывающая
    сторона подставит `FALLBACK_RPM`.
    """
    now = time.monotonic()
    cached = _PLAN_CACHE.get(org_id)
    if cached is not None and cached[0] > now:
        return cached[1]
    try:
        org = await session.get(Organization, org_id)
    except Exception:  # noqa: BLE001 - лимит не должен ронять запрос
        log.warning("quota.plan_read_failed", org_id=org_id)
        return cached[1] if cached is not None else None
    code = (org.plan if org is not None else None) or billing.DEFAULT_PLAN
    _PLAN_CACHE[org_id] = (now + PLAN_TTL_SEC, code)
    return code


def rpm_for(code: str | None) -> int:
    """Потолок запросов в минуту для тарифа."""
    if code is None:
        return FALLBACK_RPM
    return max(1, billing.plan_for(code).api_rpm)


def forget_plan(org_id: int) -> None:
    """Сбросить кэш тарифа одной организации (после смены тарифа).

    Вызывается там, где тариф меняется (оплата счёта): иначе клиент, только что
    оплативший тариф выше, минуту жил бы со старым потолком и получал `429`.
    """
    _PLAN_CACHE.pop(org_id, None)


async def enforce_rate(
    session: AsyncSession, org_id: int | None, *, path: str | None = None
) -> None:
    """Проверить частоту запросов организации.

    `429` с `Retry-After` и `X-RateLimit-*`: клиент должен понимать, что это
    ограничение тарифа, а не поломка, и знать, когда повторить.
    """
    if quota_disabled() or org_id is None or org_id == ALL_ORGS or _CHECKED.get():
        return
    # Флаг ставим ДО обращения к базе: два вызова в одном запросе (пользователь,
    # затем сотрудник) не должны считаться дважды и вдвое снижать лимит.
    _CHECKED.set(True)
    code = await plan_code(session, org_id)
    limit = rpm_for(code)
    wait = _LIMITER.check(f"org:{org_id}", limit=limit, window=WINDOW_SEC)
    if wait is None:
        return
    seconds = max(1, math.ceil(wait))
    log.warning(
        "quota.org_rate_limited",
        org_id=org_id,
        plan=code,
        limit=limit,
        path=path,
        retry_after=seconds,
    )
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"org_rate_limited:{seconds}",
        headers={
            "Retry-After": str(seconds),
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(seconds),
        },
    )


async def storage_used(session: AsyncSession, org_id: int) -> int:
    """Сколько байтов медиа занято организацией.

    Через `all_orgs()`: тенантский фильтр добавил бы `org_id = текущая`
    к явному условию, и вопрос «сколько занято у ЭТОЙ организации» при
    вызове из контекста другой вернул бы ноль. Явный `where` здесь и
    есть ограничение выборки — второй фильтр только мешает.
    """
    from app.db.hr_models import MediaBlob
    from app.db.tenancy import all_orgs

    with all_orgs():
        total = await session.scalar(
            select(func.coalesce(func.sum(MediaBlob.size), 0)).where(
                MediaBlob.org_id == org_id
            )
        )
    return int(total or 0)


async def storage_limit_bytes(session: AsyncSession, org_id: int) -> int | None:
    """Потолок хранилища в байтах. `None` — считать не по чему."""
    code = await plan_code(session, org_id)
    if code is None:
        return None
    limit_mb = billing.plan_for(code).storage_mb
    if limit_mb <= 0:
        return None
    return limit_mb * 1024 * 1024


async def ensure_storage(
    session: AsyncSession, org_id: int | None, add_bytes: int
) -> None:
    """Проверить квоту до записи блоба.

    До записи, а не после: отказ после `INSERT` всё равно оставил бы блоб в
    базе (и в счётчике), то есть квота не работала бы вовсе.
    """
    if quota_disabled() or org_id is None or org_id == ALL_ORGS or add_bytes <= 0:
        return
    limit = await storage_limit_bytes(session, org_id)
    if limit is None:
        return
    used = await storage_used(session, org_id)
    if used + add_bytes > limit:
        log.warning(
            "quota.storage_full",
            org_id=org_id,
            used_bytes=used,
            limit_bytes=limit,
            add_bytes=add_bytes,
        )
        raise QuotaExceeded(used, limit)
