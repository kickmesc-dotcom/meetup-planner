"""GHG10-ops: `/api/meta` — «паспорт» живого контейнера.

Зачем это нужно. Боевой хост Amvera регулярно отстаёт от кода (см.
`docs/AMVERA_BUILD_DIAGNOSTIC.md`), и раньше понять это можно было только
косвенно — диффом `openapi.json`. Здесь одним запросом отдаётся всё, что нужно,
чтобы отличить «старый код» от «нового кода на другой базе»:

- **отпечаток кода** (`code`): число роутов, хеш их списка и head миграций
  В КОДЕ. Сравнив с локальным значением (или с ответом другого хоста), сразу
  видно, на какой ревизии стоит контейнер;
- **куда контейнер пишет** (`db`): провайдер (neon / amvera / local / other),
  замаскированный хост, имя базы, версия миграций В БД и версия сервера;
- **возможности** (`features`): список ручек, которые реально есть в этом
  контейнере. Фронт по нему прячет функции, которых на отставшем бэкенде ещё
  нет, вместо того чтобы получать 404.

Почему роут открытый (как `/healthz`): это диагностика, а не данные. Секретов
здесь нет — пароль и полный DSN не отдаются никогда, хост маскируется
(остаётся первый сегмент + домен верхнего уровня).

Стоимость: один короткий SELECT к БД, результат кэшируется на `_DB_CACHE_TTL`
секунд — проектный бюджет запросов к Neon (см. комментарии в `scheduler.py`)
нам дороже, чем свежесть этого ответа.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import structlog
from fastapi import APIRouter, FastAPI, Request

from app.config import get_settings

log = structlog.get_logger()
router = APIRouter(tags=["meta"])

_DB_CACHE_TTL = 60.0
_db_cache: tuple[float, dict[str, Any]] | None = None
_head_cache: str | None = None

# Возможности: имя -> (метод, путь). Наличие роута в приложении и есть ответ
# «умеет ли этот контейнер такую функцию». Список пополняется вместе с ручками,
# поэтому отпечаток не может разойтись с реальностью.
_FEATURE_ROUTES: dict[str, tuple[str, str]] = {
    "me.game": ("GET", "/api/me/game"),
    "me.game.profile": ("PATCH", "/api/me/game/profile"),
    "game.achievements": ("GET", "/api/game/achievements"),
    "game.ranks": ("GET", "/api/game/ranks"),
    "game.music": ("GET", "/api/game/music/mine"),
    "game.music.like": ("POST", "/api/game/music/tracks/{track_id}/like"),
    "game.holidays": ("GET", "/api/game/holidays"),
    "game.donate": ("POST", "/api/game/donate"),
    "admin.game": ("GET", "/api/admin/game"),
    "admin.game.music": ("GET", "/api/admin/game/music"),
    "admin.game.social": ("GET", "/api/admin/game/social"),
}

# Ключи, которые считаем диагностически значимыми в отпечатке кода: служебные
# роуты документации (docs/openapi/redoc) в хеш не берём — они есть везде и
# только размывают сравнение.
_ROUTE_HASH_SKIP = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


def _iter_routes(app: FastAPI) -> list[tuple[str, str]]:
    """(METHOD, path) для всех зарегистрированных ручек, без служебных."""
    out: list[tuple[str, str]] = []
    for route in app.router.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if not path or path in _ROUTE_HASH_SKIP:
            continue
        for method in sorted(methods):
            if method in {"HEAD", "OPTIONS"}:
                continue
            out.append((method, path))
    return out


def code_fingerprint(app: FastAPI) -> dict[str, Any]:
    """Отпечаток кода: сравним локально и на любом хосте.

    Возвращает число роутов, число `/api`-роутов и короткий хеш их списка.
    Достаточно сравнить `fingerprint` двух хостов: равны — код один и тот же.
    """
    routes = sorted(_iter_routes(app))
    joined = "\n".join(f"{method} {path}" for method, path in routes)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
    return {
        "routes": len(routes),
        "api_routes": sum(1 for _, path in routes if path.startswith("/api")),
        "fingerprint": digest,
    }


def available_features(app: FastAPI) -> list[str]:
    """Какие из известных возможностей реально есть в этом контейнере."""
    routes = set(_iter_routes(app))
    return sorted(name for name, key in _FEATURE_ROUTES.items() if key in routes)


def _code_alembic_head() -> str | None:
    """Head миграций ИЗ КОДА (не из БД) — вторая половина отпечатка."""
    global _head_cache
    if _head_cache is not None:
        return _head_cache
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        root = Path(__file__).resolve().parents[2]
        cfg = Config(str(root / "alembic.ini"))
        cfg.set_main_option("script_location", str(root / "alembic"))
        _head_cache = ScriptDirectory.from_config(cfg).get_current_head()
    except Exception as exc:  # noqa: BLE001 — диагностика не имеет права падать
        log.warning("meta.alembic_head_failed", error=str(exc))
        _head_cache = None
    return _head_cache


def _mask_host(host: str | None) -> str | None:
    """`ep-cool-union-aszq9p4u.c-4.eu-central-1.aws.neon.tech` -> `ep-cool-union-…neon.tech`."""
    if not host:
        return None
    parts = host.split(".")
    if len(parts) < 2:
        return host
    head = parts[0][:14] + ("…" if len(parts[0]) > 14 else "")
    return f"{head}.{'.'.join(parts[-2:])}"


def _provider(host: str | None) -> str:
    host = (host or "").lower()
    if host.endswith(".neon.tech"):
        return "neon"
    if "amvera" in host:
        return "amvera"
    if host in {"localhost", "127.0.0.1", "::1", ""}:
        return "local"
    return "other"


def db_target() -> dict[str, Any]:
    """Куда настроен писать контейнер (по DSN) — без единого секрета."""
    settings = get_settings()
    try:
        parts = urlsplit(settings.database_url)
        host, port, name = parts.hostname, parts.port, (parts.path or "").lstrip("/")
    except Exception:  # noqa: BLE001
        host, port, name = None, None, ""
    return {
        "provider": _provider(host),
        "host": _mask_host(host),
        "port": port,
        "name": name or None,
    }


async def _db_snapshot() -> dict[str, Any]:
    """Версия миграций и сервера ИЗ БД. Кэшируется, чтобы не жечь бюджет Neon."""
    global _db_cache
    now = time.monotonic()
    if _db_cache is not None and now - _db_cache[0] < _DB_CACHE_TTL:
        return _db_cache[1]

    payload: dict[str, Any]
    try:
        from sqlalchemy import text

        from app.db.base import get_sessionmaker

        sm = get_sessionmaker()
        async with sm() as session:
            row = (
                await session.execute(
                    text(
                        "select (select version_num from alembic_version) as alembic_version, "
                        "current_setting('server_version') as server_version, "
                        "current_database() as db_name"
                    )
                )
            ).one()
        payload = {
            "alembic_version": row.alembic_version,
            "server_version": row.server_version,
            "name": row.db_name,
        }
    except Exception as exc:  # noqa: BLE001 — недоступная БД не должна ронять диагностику
        log.warning("meta.db_probe_failed", error=str(exc))
        payload = {"error": f"{type(exc).__name__}"}

    _db_cache = (now, payload)
    return payload


@router.get("/meta")
async def meta(request: Request) -> dict[str, Any]:
    """Паспорт живого контейнера: код, база, возможности.

    Берём именно `request.app`, а не модульный `app`: в тестах приложение
    создаётся заново через `create_app()`, и отпечаток должен отражать его,
    а не соседний инстанс.
    """
    fastapi_app: FastAPI = request.app
    db = {**db_target(), **await _db_snapshot()}
    return {
        "status": "ok",
        "code": {**code_fingerprint(fastapi_app), "alembic_head": _code_alembic_head()},
        "db": db,
        "features": available_features(fastapi_app),
    }
