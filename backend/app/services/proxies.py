"""Smart Proxy (P2/GHG5 Task 1).

Хранит пул прокси в таблице proxy_entries и режим работы в admin_config.
ProxyManager — синглтон, кэширующий пул на короткое время (TTL) и
обслуживающий AiohttpSession-фолбэк в `app.bot.dispatcher`.

Принципы:
- При `AUTO_FALLBACK` сначала пробуем direct (без прокси). Если последний
  direct-запрос упал — следующий запрос идёт через ближайший «живой»
  прокси из пула. На каждый запрос — максимум 3 попытки, между
  переключениями минимум 5 с.
- «Умер» прокси: после ошибки запоминаем `dead_until = now + cooldown`
  (env `PROXY_DEAD_COOLDOWN_MIN`, default 10 мин). Пока `dead_until` в
  будущем — прокси пропускается.
- Hot-reload: `set_proxy_mode` инвалидирует синглтон, и следующий
  запрос подхватит новый режим/пул из БД.

Прокси-парсер из каналов (P-4) отложен — добавляется ручное
наполнение через admin API + env-bootstrap.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProxyEntry
from app.services.admin_config import _get_value, _set_value

log = logging.getLogger(__name__)

PROXY_MODE_KEY = "proxy.mode"


class ProxyMode(str, Enum):
    ALWAYS_ON = "always_on"        # каждый запрос через прокси
    ALWAYS_OFF = "always_off"      # direct, прокси не используем
    AUTO_FALLBACK = "auto_fallback"  # direct, при ошибке — прокси


DEFAULT_MODE = ProxyMode.AUTO_FALLBACK

# --- Constants (env-tunable) ---

def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


PROXY_DEAD_COOLDOWN_MIN = _env_int("PROXY_DEAD_COOLDOWN_MIN", 10)
MAX_ATTEMPTS_PER_REQUEST = _env_int("PROXY_MAX_ATTEMPTS", 3)
MIN_SWITCH_INTERVAL_SEC = float(_env_int("PROXY_MIN_SWITCH_INTERVAL_SEC", 5))


@dataclass
class ProxyRecord:
    id: int
    server: str
    port: int
    type: str
    secret: str | None
    enabled: bool
    fail_count: int
    last_ok_at: datetime | None
    last_fail_at: datetime | None
    dead_until: datetime | None

    def is_alive(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        return self.dead_until is None or self.dead_until <= now

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "server": self.server,
            "port": self.port,
            "type": self.type,
            "secret": self.secret,
            "enabled": self.enabled,
            "fail_count": self.fail_count,
            "last_ok_at": self.last_ok_at.isoformat() if self.last_ok_at else None,
            "last_fail_at": self.last_fail_at.isoformat() if self.last_fail_at else None,
            "dead_until": self.dead_until.isoformat() if self.dead_until else None,
        }


# --- ProxyManager singleton ---


@dataclass
class _State:
    mode: ProxyMode = DEFAULT_MODE
    pool: list[ProxyRecord] = field(default_factory=list)
    loaded_at: float = 0.0
    # Курсор внутри пула — простой round-robin.
    cursor: int = 0
    # Время последнего переключения direct → proxy (или между прокси) на
    # любом запросе. Защищает от гиперактивных свитчей.
    last_switch_at: float = 0.0


_state = _State()
_lock = asyncio.Lock()

POOL_TTL_SECONDS = 30.0


def _is_state_fresh() -> bool:
    return _state.loaded_at > 0 and (time.monotonic() - _state.loaded_at) < POOL_TTL_SECONDS


async def get_proxy_mode(session: AsyncSession) -> ProxyMode:
    raw = await _get_value(session, PROXY_MODE_KEY)
    if raw is None:
        return DEFAULT_MODE
    try:
        return ProxyMode(raw)
    except ValueError:
        return DEFAULT_MODE


async def set_proxy_mode(session: AsyncSession, mode: ProxyMode) -> None:
    await _set_value(session, PROXY_MODE_KEY, mode.value)
    invalidate()


def invalidate() -> None:
    """Сбросить кэш — следующий запрос перечитает БД."""
    _state.loaded_at = 0.0
    log.info("proxy.cache_invalidated")


async def _load_pool(session: AsyncSession) -> None:
    mode = await get_proxy_mode(session)
    rows = (
        await session.scalars(
            select(ProxyEntry).where(ProxyEntry.enabled.is_(True)).order_by(ProxyEntry.id)
        )
    ).all()
    pool = [
        ProxyRecord(
            id=r.id,
            server=r.server,
            port=r.port,
            type=r.type,
            secret=r.secret,
            enabled=r.enabled,
            fail_count=r.fail_count,
            last_ok_at=r.last_ok_at,
            last_fail_at=r.last_fail_at,
            dead_until=r.dead_until,
        )
        for r in rows
    ]
    _state.mode = mode
    _state.pool = pool
    _state.loaded_at = time.monotonic()
    log.info("proxy.pool_loaded", extra={"mode": mode.value, "count": len(pool)})


async def ensure_loaded(session: AsyncSession) -> None:
    if _is_state_fresh():
        return
    async with _lock:
        if _is_state_fresh():
            return
        await _load_pool(session)


def get_state_snapshot() -> dict:
    return {
        "mode": _state.mode.value,
        "pool_size": len(_state.pool),
        "alive": sum(1 for p in _state.pool if p.is_alive(datetime.now(timezone.utc))),
        "loaded_at": _state.loaded_at,
    }


def pick_next_alive() -> ProxyRecord | None:
    """Round-robin по живым прокси. Не дёргает БД."""
    if not _state.pool:
        return None
    now = datetime.now(timezone.utc)
    n = len(_state.pool)
    for i in range(n):
        idx = (_state.cursor + i) % n
        rec = _state.pool[idx]
        if rec.is_alive(now):
            _state.cursor = (idx + 1) % n
            return rec
    return None


def can_switch() -> bool:
    return (time.monotonic() - _state.last_switch_at) >= MIN_SWITCH_INTERVAL_SEC


def mark_switch() -> None:
    _state.last_switch_at = time.monotonic()


async def mark_proxy_failed(session: AsyncSession, rec: ProxyRecord) -> None:
    """Помечаем прокси как «умерший» на cooldown."""
    cd = timedelta(minutes=PROXY_DEAD_COOLDOWN_MIN)
    now = datetime.now(timezone.utc)
    row = await session.get(ProxyEntry, rec.id)
    if row is None:
        return
    row.fail_count = (row.fail_count or 0) + 1
    row.last_fail_at = now
    row.dead_until = now + cd
    await session.commit()
    # Обновим in-memory копию.
    for r in _state.pool:
        if r.id == rec.id:
            r.fail_count = row.fail_count
            r.last_fail_at = row.last_fail_at
            r.dead_until = row.dead_until
            break
    log.info(
        "proxy.marked_dead",
        extra={"proxy_id": rec.id, "until": row.dead_until.isoformat()},
    )


async def mark_proxy_ok(session: AsyncSession, rec: ProxyRecord) -> None:
    row = await session.get(ProxyEntry, rec.id)
    if row is None:
        return
    now = datetime.now(timezone.utc)
    row.last_ok_at = now
    row.dead_until = None
    row.fail_count = 0
    await session.commit()
    for r in _state.pool:
        if r.id == rec.id:
            r.last_ok_at = now
            r.dead_until = None
            r.fail_count = 0
            break


# --- CRUD ---


async def list_proxies(session: AsyncSession) -> list[ProxyEntry]:
    rows = (await session.scalars(select(ProxyEntry).order_by(ProxyEntry.id))).all()
    return list(rows)


async def upsert_proxy(
    session: AsyncSession,
    *,
    server: str,
    port: int,
    type_: str = "mtproto",
    secret: str | None = None,
    enabled: bool = True,
) -> ProxyEntry:
    stmt = (
        pg_insert(ProxyEntry)
        .values(server=server, port=port, type=type_, secret=secret, enabled=enabled)
        .on_conflict_do_update(
            constraint="uq_proxy_server_port",
            set_={"type": type_, "secret": secret, "enabled": enabled},
        )
        .returning(ProxyEntry)
    )
    res = await session.execute(stmt)
    await session.commit()
    invalidate()
    return res.scalar_one()


async def update_proxy(
    session: AsyncSession, proxy_id: int, *, enabled: bool | None = None
) -> ProxyEntry | None:
    row = await session.get(ProxyEntry, proxy_id)
    if row is None:
        return None
    if enabled is not None:
        row.enabled = enabled
        if not enabled:
            row.dead_until = None  # выключенные не «отдыхают»
    await session.commit()
    invalidate()
    return row


async def delete_proxy(session: AsyncSession, proxy_id: int) -> bool:
    row = await session.get(ProxyEntry, proxy_id)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    invalidate()
    return True


# --- env-bootstrap ---


async def bootstrap_from_env(session: AsyncSession) -> int:
    """Подхватывает PROXIES_BOOTSTRAP_JSON — список dict-ов.

    Формат: `[{"server":"1.2.3.4","port":443,"type":"mtproto","secret":"deadbeef"}]`.
    Существующие записи (по server+port) обновляются. Возвращает количество
    добавленных/обновлённых записей.
    """
    raw = os.getenv("PROXIES_BOOTSTRAP_JSON")
    if not raw:
        return 0
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        log.warning("proxy.bootstrap_bad_json")
        return 0
    if not isinstance(data, list):
        return 0
    added = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        server = item.get("server")
        port = item.get("port")
        if not isinstance(server, str) or not isinstance(port, int):
            continue
        type_ = item.get("type", "mtproto")
        if type_ not in ("mtproto", "socks5", "http"):
            type_ = "mtproto"
        secret = item.get("secret")
        if secret is not None and not isinstance(secret, str):
            secret = None
        enabled = bool(item.get("enabled", True))
        await upsert_proxy(
            session,
            server=server,
            port=int(port),
            type_=type_,
            secret=secret,
            enabled=enabled,
        )
        added += 1
    if added:
        log.info("proxy.bootstrap_loaded", extra={"count": added})
    return added
