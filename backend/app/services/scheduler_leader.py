"""GHG11(5): single-writer для планировщика — один лидер на общую БД.

Проблема (H1): Amvera и HuggingFace Space крутят ОДИН и тот же код против ОДНОЙ
Neon. APScheduler стартует в lifespan КАЖДОГО процесса, а `max_instances=1`
защищает только внутри процесса — не между инстансами. Две живые реплики
независимо стреляют ежедневными cron-джобами (автолох, фразы, чухан, ДР,
праздники) → дубли постов в чат.

Решение: лиз на лидерство в уже существующей таблице `admin_config` (миграция не
нужна). Инстанс держит лиз живым heartbeat'ом; кто не лидер — планировщик не
стартует. Если лидер умер (перестал обновлять лиз дольше TTL), второй инстанс
забирает лидерство и поднимает планировщик. Ровно один активный писатель в любой
момент.

Забор/продление атомарны: строка берётся `SELECT … FOR UPDATE`, поэтому две
одновременные попытки сериализуются на БД и не могут обе стать лидером.

Все операции best-effort: при сбое БД вызывающий код (см. `scheduler.py`) не
теряет текущий статус лидера, чтобы секундный блип Neon не ронял джобы.
"""
from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminConfig

log = structlog.get_logger()

# Ключ в `admin_config`. Значение — JSON `{"owner": str, "at": iso8601}`.
LEASE_KEY = "scheduler.leader"
# Сколько секунд лиз считается живым без heartbeat'а. Должно быть с запасом
# больше интервала продления (см. SCHEDULER_LEASE_RENEW_SECONDS в scheduler.py),
# чтобы сетевой лаг не приводил к «двум лидерам».
DEFAULT_TTL_SECONDS = 300


def instance_id() -> str:
    """Идентификатор процесса-инстанса: hostname+pid (уникален для реплики)."""
    return f"{socket.gethostname()}:{os.getpid()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def encode(owner: str, at: datetime) -> str:
    """Сериализовать лиз в значение `admin_config`."""
    return json.dumps({"owner": owner, "at": at.isoformat()})


def decode(raw: str | None) -> tuple[str | None, datetime | None]:
    """Разобрать значение лиза. Кривое/пустое → (None, None) — считаем свободным."""
    try:
        data = json.loads(raw or "{}")
        owner = data.get("owner")
        at_raw = data.get("at")
        at = datetime.fromisoformat(at_raw) if at_raw else None
        if at is not None and at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        return (owner if isinstance(owner, str) else None), at
    except (ValueError, TypeError):
        return None, None


def lease_is_free(
    owner: str | None,
    at: datetime | None,
    me: str,
    now: datetime,
    ttl_seconds: float,
) -> bool:
    """Чистое решение: можем ли мы взять лиз (без БД — тестируется отдельно).

    Лиз либо наш (продление), либо никем не занят, либо просрочен (лидер умер).
    """
    if owner is None or at is None:
        return True
    if owner == me:
        return True
    return at < now - timedelta(seconds=ttl_seconds)


async def acquire_or_renew(
    session: AsyncSession, me: str, *, ttl_seconds: float = DEFAULT_TTL_SECONDS
) -> bool:
    """Попытаться стать лидером или продлить своё лидерство.

    `True` — мы лидер (в этом вызове лидерство подтверждено). `False` — лидер
    кто-то другой. Атомарно за счёт `SELECT … FOR UPDATE` на строке лиз а.
    """
    now = _now()
    row = await session.get(AdminConfig, LEASE_KEY, with_for_update=True)
    if row is None:
        session.add(AdminConfig(key=LEASE_KEY, value=encode(me, now)))
        await session.commit()
        return True
    owner, at = decode(row.value)
    if lease_is_free(owner, at, me, now, ttl_seconds):
        row.value = encode(me, now)
        await session.commit()
        return True
    await session.rollback()
    return False


async def release(session: AsyncSession, me: str) -> None:
    """Отпустить лиз (graceful shutdown) — второй инстанс подхватит сразу."""
    row = await session.get(AdminConfig, LEASE_KEY, with_for_update=True)
    if row is None:
        return
    owner, _ = decode(row.value)
    if owner != me:
        await session.rollback()
        return
    await session.delete(row)
    await session.commit()
    log.info("scheduler_leader.released", owner=me)
