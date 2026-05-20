"""Smart Proxy (P2/GHG5 Task 1; расширено в GHG6 P0).

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

GHG6 P0 добавляет:
- `selftest_send` — скрытая проверка getMe (+опц. echo в SELFTEST_CHAT_ID)
  с замером latency.
- `ping_proxy` — TCP-коннект через aiohttp_socks с тайм-аутом.
- `ping_all`, `delete_dead` — batch-операции на пулом.
- `parse_mtproto_blob` — парсер простыни из @ProxyMTProto.
- `notify_admins_about_proxy_down` — алёрт админам с rate-limit 1/час.
- `record_last_error` / `get_last_error` — хвост последней ошибки
  отправки (для UI).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING

import aiohttp
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProxyEntry
from app.services.admin_config import _get_value, _set_value

if TYPE_CHECKING:
    from aiogram import Bot

log = logging.getLogger(__name__)

PROXY_MODE_KEY = "proxy.mode"
PROXY_LAST_ERROR_KEY = "proxy.last_error"               # JSON
PROXY_LAST_ALERT_AT_KEY = "proxy.last_admin_alert_at"   # ISO datetime
PROXY_ADMIN_ALERTS_ENABLED_KEY = "proxy.admin_alerts_enabled"  # bool

# Лимит на размер пула (GHG6 PX10).
PROXY_POOL_MAX = 50

# Тайм-ауты для проверок и нотификаций.
PING_TIMEOUT_SEC = 6.0
SELFTEST_TIMEOUT_SEC = 15.0
ADMIN_ALERT_COOLDOWN_SEC = 60 * 60  # 1 час


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
) -> tuple[ProxyEntry, bool]:
    """Создать или обновить прокси по (server, port).

    Возвращает ``(row, created)`` — ``created=True`` если запись была добавлена,
    ``False`` если по (server, port) уже существовала и просто обновилась.
    """
    # GHG6 PX10: enforce pool limit на add (не на upsert существующего).
    existing = await session.scalar(
        select(ProxyEntry).where(
            ProxyEntry.server == server, ProxyEntry.port == port
        )
    )
    if existing is None:
        from sqlalchemy import func as _sqlfunc
        total = await session.scalar(select(_sqlfunc.count()).select_from(ProxyEntry))
        if (total or 0) >= PROXY_POOL_MAX:
            raise ValueError(f"proxy_pool_full:{PROXY_POOL_MAX}")
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
    return res.scalar_one(), existing is None


async def update_proxy(
    session: AsyncSession,
    proxy_id: int,
    *,
    enabled: bool | None = None,
    server: str | None = None,
    port: int | None = None,
    type_: str | None = None,
    secret: str | None = None,
    clear_secret: bool = False,
) -> ProxyEntry | None:
    row = await session.get(ProxyEntry, proxy_id)
    if row is None:
        return None
    if enabled is not None:
        row.enabled = enabled
        if not enabled:
            row.dead_until = None  # выключенные не «отдыхают»
    if server is not None:
        row.server = server
    if port is not None:
        row.port = port
    if type_ is not None:
        row.type = type_
    if clear_secret:
        row.secret = None
    elif secret is not None:
        row.secret = secret
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


# =============================================================================
# GHG6 P0: indicators, parser, ping/selftest, admin alerts
# =============================================================================


# --- PX5: парсер простыни из @ProxyMTProto ---

_PARSE_KV_RE = re.compile(
    r"^\s*(server|host|ip|address|port|secret|password|pass|type|protocol)\s*[:=]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# Маркеры типа в свободном тексте (заголовки блоков): "PROXY MTProto", "SOCKS5 proxy", "HTTP proxy".
_TYPE_HINT_RE = re.compile(r"\b(mtproto|socks5|socks|https?)\b", re.IGNORECASE)
# Ссылочный формат telegram-прокси: tg://proxy?server=X&port=Y&secret=Z (или ?user=&pass= для socks)
# а также https://t.me/proxy?... и https://t.me/socks?... Учитываем оба варианта.
_PROXY_URL_RE = re.compile(
    r"(?:tg://|https?://t\.me/)(proxy|socks)\?([^\s)<>\"']+)",
    re.IGNORECASE,
)


def _normalize_type_hint(s: str | None) -> str:
    """Приводит произвольную метку типа к одному из {mtproto, socks5, http}."""
    if not s:
        return "mtproto"
    v = s.strip().lower()
    if "mtproto" in v or v == "mt":
        return "mtproto"
    if "socks" in v:
        return "socks5"
    if "http" in v:
        return "http"
    return "mtproto"


@dataclass
class ProxyDraft:
    server: str
    port: int
    secret: str | None
    type: str = "mtproto"

    def to_dict(self) -> dict:
        return {
            "server": self.server,
            "port": self.port,
            "secret": self.secret,
            "type": self.type,
        }


def parse_mtproto_blob(text: str) -> list[ProxyDraft]:
    """Найти прокси в произвольной текстовой простыне.

    Логика проста: пробегаем по строкам, собираем `Server:` / `Port:` /
    `Secret:` (case-insensitive, разделитель `:` или `=`). Когда встретили
    повторный `Server:` (или дошли до конца) — закрываем текущую группу.

    Поддерживает форматы из инструкции:
        Server: 178.105.137.152
        Port: 443
        Secret: eeabf...
        @ProxyMTProto

        PROXY MTProto
        Server: mt.nowaboost.com
        Port: 853
        Secret: 4fd95a...
        @ProxyMTProto

    Возвращает список валидных черновиков (server+port обязательны).
    """
    if not text:
        return []
    drafts: list[ProxyDraft] = []
    seen: set[tuple[str, int]] = set()

    def _add(server: str, port_raw: str | int, secret: str | None, type_: str) -> None:
        s = (server or "").strip()
        if not s:
            return
        try:
            p = int(port_raw)
        except (ValueError, TypeError):
            return
        if not (1 <= p <= 65535):
            return
        key = (s, p)
        if key in seen:
            return
        seen.add(key)
        drafts.append(
            ProxyDraft(server=s, port=p, secret=(secret or None), type=type_)
        )

    # 1) Ссылочный формат tg://proxy / https://t.me/proxy|socks?... — самый частый
    # вариант пересылки прокси в телеге, его обязательно поддерживаем.
    from urllib.parse import parse_qs

    for m in _PROXY_URL_RE.finditer(text):
        kind = m.group(1).lower()  # "proxy" → mtproto, "socks" → socks5
        qs = parse_qs(m.group(2), keep_blank_values=False)
        server = (qs.get("server") or [""])[0]
        port = (qs.get("port") or [""])[0]
        secret = (qs.get("secret") or [None])[0]
        type_ = "socks5" if kind == "socks" else "mtproto"
        _add(server, port, secret, type_)

    # 2) KV-блоки вида "Server: X / Port: Y / Secret: Z".
    # Тип определяем по подсказке в ближайшей строке выше группы.
    lines = text.splitlines()
    current: dict[str, str] = {}
    current_type: str = "mtproto"
    last_hint_line = -1

    def _flush_kv() -> None:
        s = current.get("server")
        p_raw = current.get("port")
        if not s or not p_raw:
            current.clear()
            return
        type_ = _normalize_type_hint(current.get("type") or current.get("protocol")) \
            if (current.get("type") or current.get("protocol")) else current_type
        secret = current.get("secret") or current.get("password") or current.get("pass")
        _add(s, p_raw, secret, type_)
        current.clear()

    for idx, raw_line in enumerate(lines):
        line = raw_line.strip()
        # Подсказка типа: ищем в строках без `:` или с ключевыми словами (заголовки блоков).
        if line and not _PARSE_KV_RE.match(raw_line):
            hint = _TYPE_HINT_RE.search(line)
            if hint:
                current_type = _normalize_type_hint(hint.group(1))
                last_hint_line = idx
        m = _PARSE_KV_RE.match(raw_line)
        if not m:
            continue
        key = m.group(1).lower()
        value = m.group(2).strip()
        if key == "server" and current.get("server"):
            _flush_kv()
            # Сбрасываем тип к последней подсказке выше — иначе при двух
            # подряд блоках MTProto/SOCKS5 второй унаследует тип первого.
            if last_hint_line < idx - 6:
                current_type = "mtproto"
        # Нормализуем ключевые алиасы.
        if key in {"host", "ip", "address"}:
            key = "server"
        if key in {"password", "pass"}:
            key = "secret"
        if key == "protocol":
            key = "type"
        current[key] = value
    _flush_kv()
    return drafts


# --- PX2/PX3: ping ---


@dataclass
class PingResult:
    proxy_id: int
    ok: bool
    latency_ms: int | None
    error: str | None

    def to_dict(self) -> dict:
        return {
            "proxy_id": self.proxy_id,
            "ok": self.ok,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


def _proxy_connector_for_ping(rec: ProxyRecord) -> aiohttp.BaseConnector | None:
    """SOCKS5/HTTP — через aiohttp_socks. MTProto не годится для HTTP-пробы."""
    ptype = (rec.type or "").lower()
    if ptype not in {"socks5", "http"}:
        return None
    try:
        from aiohttp_socks import ProxyConnector, ProxyType as _PT
    except ImportError:
        log.warning("proxy.aiohttp_socks_missing_in_ping")
        return None
    pt = _PT.SOCKS5 if ptype == "socks5" else _PT.HTTP
    return ProxyConnector(
        proxy_type=pt,
        host=rec.server,
        port=rec.port,
        password=rec.secret if ptype == "socks5" else None,
        rdns=True,
    )


async def _http_probe(rec: ProxyRecord, *, timeout: float = PING_TIMEOUT_SEC) -> PingResult:
    """Пингуем `https://api.telegram.org/` (без токена — отдаст 404, но
    нам важен сам факт TCP-handshake'а через прокси)."""
    connector = _proxy_connector_for_ping(rec)
    if connector is None:
        # MTProto или ImportError — не можем достоверно проверить через HTTP.
        return PingResult(
            proxy_id=rec.id,
            ok=False,
            latency_ms=None,
            error="ping_not_supported_for_type:" + (rec.type or "?"),
        )
    started = time.monotonic()
    try:
        async with aiohttp.ClientSession(connector=connector, trust_env=False) as sess:
            async with asyncio.timeout(timeout):
                async with sess.get("https://api.telegram.org/") as resp:
                    await resp.read()
        latency_ms = int((time.monotonic() - started) * 1000)
        return PingResult(proxy_id=rec.id, ok=True, latency_ms=latency_ms, error=None)
    except asyncio.TimeoutError:
        return PingResult(proxy_id=rec.id, ok=False, latency_ms=None, error="timeout")
    except Exception as exc:  # noqa: BLE001
        return PingResult(
            proxy_id=rec.id,
            ok=False,
            latency_ms=None,
            error=f"{exc.__class__.__name__}: {exc}"[:200],
        )


def _record_from_row(row: ProxyEntry) -> ProxyRecord:
    return ProxyRecord(
        id=row.id,
        server=row.server,
        port=row.port,
        type=row.type,
        secret=row.secret,
        enabled=row.enabled,
        fail_count=row.fail_count,
        last_ok_at=row.last_ok_at,
        last_fail_at=row.last_fail_at,
        dead_until=row.dead_until,
    )


async def ping_proxy(session: AsyncSession, proxy_id: int) -> PingResult:
    row = await session.get(ProxyEntry, proxy_id)
    if row is None:
        return PingResult(proxy_id=proxy_id, ok=False, latency_ms=None, error="not_found")
    rec = _record_from_row(row)
    result = await _http_probe(rec)
    if result.ok:
        await mark_proxy_ok(session, rec)
    else:
        # Не помечаем dead на «ping_not_supported» — это не сбой, а нечего пинговать.
        if not (result.error or "").startswith("ping_not_supported"):
            await mark_proxy_failed(session, rec)
    return result


async def ping_all(session: AsyncSession) -> list[PingResult]:
    rows = await list_proxies(session)
    if not rows:
        return []
    sem = asyncio.Semaphore(5)

    async def _one(row: ProxyEntry) -> PingResult:
        async with sem:
            rec = _record_from_row(row)
            return await _http_probe(rec)

    results = await asyncio.gather(*[_one(r) for r in rows])
    # Применяем mark_ok / mark_failed по результатам — последовательно, чтобы не
    # ловить deadlock'и на одной сессии.
    for row, res in zip(rows, results, strict=True):
        rec = _record_from_row(row)
        if res.ok:
            await mark_proxy_ok(session, rec)
        elif not (res.error or "").startswith("ping_not_supported"):
            await mark_proxy_failed(session, rec)
    return list(results)


# --- PX4: cleanup ---


async def delete_dead(session: AsyncSession) -> int:
    """Удаляет прокси, которые были проверены и оказались мёртвыми.

    Критерий: `fail_count > 0` И `last_ok_at IS NULL` — то есть прокси
    ни разу не отвечал успехом, но как минимум один отказ был зафиксирован.
    Не трогает «свежие» (никогда не пинговавшиеся) и периодически живые.
    """
    rows = (
        await session.scalars(
            select(ProxyEntry).where(
                ProxyEntry.fail_count > 0, ProxyEntry.last_ok_at.is_(None)
            )
        )
    ).all()
    if not rows:
        return 0
    for r in rows:
        await session.delete(r)
    await session.commit()
    invalidate()
    log.info("proxy.delete_dead", extra={"count": len(rows)})
    return len(rows)


# --- PX1: selftest (скрытая отправка) ---


@dataclass
class SelftestResult:
    ok: bool
    mode_used: str
    proxy_id: int | None
    latency_ms: int | None
    error: str | None
    bot_active: bool  # True если бот вообще удалось дёрнуть (даже если send упал)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "mode_used": self.mode_used,
            "proxy_id": self.proxy_id,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "bot_active": self.bot_active,
        }


async def selftest_send(bot: "Bot", *, session: AsyncSession | None = None) -> SelftestResult:
    """Замеряет latency на getMe через текущую сессию бота.

    Дополнительно: если задан env `SELFTEST_CHAT_ID` — шлёт туда короткое
    «ping» и сразу удаляет, чтобы реально проверить именно отправку.
    Никаких сообщений в основные чаты — это «скрытая» проверка.
    """
    selftest_chat_raw = os.getenv("SELFTEST_CHAT_ID")
    selftest_chat_id: int | None = None
    if selftest_chat_raw:
        try:
            selftest_chat_id = int(selftest_chat_raw)
        except ValueError:
            selftest_chat_id = None

    # Получаем текущий режим — для отображения в UI.
    mode_str = "unknown"
    if session is not None:
        mode_str = (await get_proxy_mode(session)).value
    else:
        # fallback — берём из state
        mode_str = _state.mode.value

    started = time.monotonic()
    proxy_id_after_call: int | None = None
    try:
        async with asyncio.timeout(SELFTEST_TIMEOUT_SEC):
            await bot.get_me()
            # Заберём id активного прокси из session, если он есть.
            sess = getattr(bot, "session", None)
            proxy_id_after_call = getattr(sess, "_active_proxy_id", None)

            if selftest_chat_id is not None:
                msg = await bot.send_message(chat_id=selftest_chat_id, text="🧪 ping")
                try:
                    await bot.delete_message(chat_id=selftest_chat_id, message_id=msg.message_id)
                except Exception:  # noqa: BLE001
                    pass
        latency_ms = int((time.monotonic() - started) * 1000)
        return SelftestResult(
            ok=True,
            mode_used=mode_str,
            proxy_id=proxy_id_after_call,
            latency_ms=latency_ms,
            error=None,
            bot_active=True,
        )
    except asyncio.TimeoutError:
        return SelftestResult(
            ok=False,
            mode_used=mode_str,
            proxy_id=proxy_id_after_call,
            latency_ms=None,
            error="timeout",
            bot_active=False,
        )
    except Exception as exc:  # noqa: BLE001
        err = f"{exc.__class__.__name__}: {exc}"[:300]
        # Если ошибка пришла от Telegram (Unauthorized/BadRequest) — бот сам жив.
        bot_active = exc.__class__.__name__ in {
            "TelegramUnauthorizedError",
            "TelegramBadRequest",
            "TelegramForbiddenError",
        }
        return SelftestResult(
            ok=False,
            mode_used=mode_str,
            proxy_id=proxy_id_after_call,
            latency_ms=None,
            error=err,
            bot_active=bot_active,
        )


# --- PX9: last error tail (для UI) ---


async def record_last_error(
    session: AsyncSession,
    *,
    message: str,
    mode_used: str,
    proxy_id: int | None,
) -> None:
    payload = {
        "at": datetime.now(timezone.utc).isoformat(),
        "message": message[:500],
        "mode_used": mode_used,
        "proxy_id": proxy_id,
    }
    await _set_value(session, PROXY_LAST_ERROR_KEY, json.dumps(payload, ensure_ascii=False))


async def get_last_error(session: AsyncSession) -> dict | None:
    raw = await _get_value(session, PROXY_LAST_ERROR_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


async def clear_last_error(session: AsyncSession) -> None:
    await _set_value(session, PROXY_LAST_ERROR_KEY, "")


# --- PX7: admin alerts ---


async def get_alerts_enabled(session: AsyncSession) -> bool:
    raw = await _get_value(session, PROXY_ADMIN_ALERTS_ENABLED_KEY)
    if raw is None:
        return True
    return raw.lower() in {"1", "true", "yes", "on"}


async def set_alerts_enabled(session: AsyncSession, enabled: bool) -> None:
    await _set_value(
        session, PROXY_ADMIN_ALERTS_ENABLED_KEY, "true" if enabled else "false"
    )


async def get_last_alert_at(session: AsyncSession) -> datetime | None:
    raw = await _get_value(session, PROXY_LAST_ALERT_AT_KEY)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


async def notify_admins_about_proxy_down(
    bot: "Bot", session: AsyncSession, reason: str
) -> bool:
    """Шлёт в личку каждому ADMIN_TG_IDS, но не чаще ADMIN_ALERT_COOLDOWN_SEC.

    Возвращает True, если хотя бы одно сообщение реально ушло.
    """
    if not await get_alerts_enabled(session):
        return False
    last_at = await get_last_alert_at(session)
    now = datetime.now(timezone.utc)
    if last_at is not None:
        # last_at может быть naive — нормализуем в utc
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        if (now - last_at).total_seconds() < ADMIN_ALERT_COOLDOWN_SEC:
            log.info("proxy.alert_skipped_cooldown", extra={"reason": reason})
            return False
    from app.config import get_settings as _gs

    admin_ids = list(_gs().admin_tg_id_set)
    if not admin_ids:
        return False
    text = (
        "⚠️ <b>Прокси-проблема</b>\n"
        f"<i>{reason}</i>\n\n"
        "Меньше — не чаще раза в час. Выключить нотификации можно в админке Mini App "
        "(Прокси → 🔔 уведомления админу)."
    )
    sent_any = False
    for admin_id in admin_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=text, parse_mode="HTML")
            sent_any = True
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "proxy.alert_send_failed",
                extra={"admin_id": admin_id, "err": exc.__class__.__name__},
            )
    if sent_any:
        await _set_value(session, PROXY_LAST_ALERT_AT_KEY, now.isoformat())
    return sent_any


# --- PX6: периодический самотест (вызывается из scheduler.py) ---


async def proxy_health_tick(bot: "Bot") -> None:
    """Раз в env.PROXY_HEALTH_INTERVAL_SEC: запускаем selftest_send. Если в режиме
    ALWAYS_ON и все прокси умерли — алёртим админам."""
    from app.db.base import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as db:
        result = await selftest_send(bot, session=db)
        if not result.ok:
            mode = await get_proxy_mode(db)
            if mode is ProxyMode.ALWAYS_ON:
                await ensure_loaded(db)
                now = datetime.now(timezone.utc)
                alive = sum(1 for p in _state.pool if p.is_alive(now))
                if alive == 0:
                    await notify_admins_about_proxy_down(
                        bot,
                        db,
                        reason=(
                            f"Selftest упал ({result.error}), а в режиме ALWAYS_ON "
                            "ни одного живого прокси."
                        ),
                    )
            await record_last_error(
                db,
                message=result.error or "unknown",
                mode_used=result.mode_used,
                proxy_id=result.proxy_id,
            )
        log.info(
            "proxy.health_tick",
            extra={
                "ok": result.ok,
                "latency_ms": result.latency_ms,
                "mode": result.mode_used,
            },
        )
