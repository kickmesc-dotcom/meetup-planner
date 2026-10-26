"""GHG10-ops: `/api/meta` — «паспорт» живого контейнера.

Зачем это нужно. Боевой хост Amvera регулярно отстаёт от кода (см.
`docs/AMVERA_BUILD_DIAGNOSTIC.md`), и раньше понять это можно было только
косвенно — диффом `openapi.json`. Здесь одним запросом отдаётся всё, что нужно,
чтобы отличить «старый код» от «нового кода на другой базе»:

- **отпечаток кода** (`code`): число роутов, хеш их списка, head миграций
  В КОДЕ и **маркер сборки** (`build`) — короткий commit sha (если контейнер
  умеет его прочитать) либо хеш исходников. Раньше отпечаток ловил только
  изменения СПИСКА роутов: правка логики без новых ручек (и без новых миграций)
  была невидима и «задеплоилось или нет?» оставалось гадать. `build` меняется
  от любой правки в `app/`. Сравнив его с ответом другого хоста или с локальным
  значением, сразу видно, на какой ревизии стоит контейнер;
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
import os
import subprocess
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
_build_cache: dict[str, Any] | None = None

# Возможности: имя -> (метод, путь). Наличие роута в приложении и есть ответ
# «умеет ли этот контейнер такую функцию». Список пополняется вместе с ручками,
# поэтому отпечаток не может разойтись с реальностью.
_FEATURE_ROUTES: dict[str, tuple[str, str]] = {
    "me.game": ("GET", "/api/me/game"),
    "me.game.profile": ("PATCH", "/api/me/game/profile"),
    # Э19: гостевой профиль по клику на аватарку на календаре.
    "game.player": ("GET", "/api/game/players/{user_id}"),
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


# Имена переменных, которыми хостинги отдают ревизию сборки. Порядок — от самой
# точной (полный sha коммита) к запасным. Если ни одной нет — считаем хеш
# исходников (см. `_source_hash`).
_BUILD_ENV_VARS: tuple[str, ...] = (
    "GIT_SHA",
    "COMMIT_SHA",
    "SOURCE_VERSION",
    "SOURCE_COMMIT",
    "HF_COMMIT_SHA",
    "RENDER_GIT_COMMIT",
    "GIT_COMMIT",
    "HEROKU_SLUG_COMMIT",
    "GITHUB_SHA",
    "BUILD_SHA",
)


def _source_hash(root: Path) -> str:
    """Хеш исходников `app/` — маркер, который меняется от любой правки кода.

    Считаем по отсортированным (относительный путь, содержимое) всех `.py`, плюс
    содержимое `alembic/versions/*.py`. Раскладку по путям берём, чтобы переезд
    файла тоже менял хеш. Читается один раз за процесс и кэшируется вызывающим.
    """
    digest = hashlib.sha256()
    targets = sorted((root / "app").rglob("*.py")) + sorted(
        (root / "alembic" / "versions").glob("*.py")
    )
    for path in targets:
        try:
            rel = path.relative_to(root).as_posix()
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        except OSError:  # noqa: PERF203 — один битый файл не должен ронять диагностику
            continue
    return digest.hexdigest()[:12]


def build_marker() -> dict[str, Any]:
    """Маркер версии кода: короткий commit sha или хеш исходников.

    Задача оператора: «деплой должно быть видно даже без изменения списка
    роутов». Отпечаток `fingerprint` ловит только новые ручки, поэтому здесь
    отдельный маркер:

    1. переменные окружения хостинга (полный sha → берём первые 12 символов);
    2. `git rev-parse --short HEAD`, если в образе есть `.git` и git;
    3. иначе — хеш исходников (`_source_hash`).

    `source` говорит, откуда взято значение: env / git / hash / none. Результат
    кэшируется на процесс: он не меняется до перезапуска контейнера, а именно
    перезапуск и означает новый деплой.
    """
    global _build_cache
    if _build_cache is not None:
        return _build_cache

    value: str | None = None
    source = "none"
    for name in _BUILD_ENV_VARS:
        raw = (os.environ.get(name) or "").strip()
        if raw:
            value = raw[:12]
            source = "env"
            break

    if value is None:
        root = Path(__file__).resolve().parents[2]
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            out = (proc.stdout or "").strip()
            if proc.returncode == 0 and out:
                value = out[:12]
                source = "git"
        except (OSError, subprocess.SubprocessError):  # noqa: BLE001
            value = None

    if value is None:
        try:
            value = _source_hash(Path(__file__).resolve().parents[2])
            source = "hash"
        except Exception as exc:  # noqa: BLE001 — диагностика не имеет права падать
            log.warning("meta.build_marker_failed", error=str(exc))
            value, source = None, "none"

    _build_cache = {"build": value, "source": source}
    return _build_cache


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


# ----------------------------------------------------------------- сеть ----

# Хосты, до которых бот обязан доходить. Порядок важен: первым Telegram.
_NET_TARGETS = (
    "api.telegram.org",
    "telegram-proxy2.esw1337.workers.dev",
    "api.github.com",
)


def _diag_token_ok(request: Request) -> bool:
    """Секрет вебхука как пропуск к диагностике.

    Значение знает только Telegram и мы (`TG_WEBHOOK_SECRET` уже лежит в
    заголовке `X-Telegram-Bot-Api-Secret-Token` у каждого апдейта), поэтому
    новый секрет заводить не нужно, а без токена ручка просто не существует
    (404) — чтобы не светить сетевым устройством хоста.
    """
    import hmac

    expected = (get_settings().tg_webhook_secret or "").strip()
    given = (request.headers.get("x-diag-token") or "").strip()
    if not expected or not given:
        return False
    return hmac.compare_digest(expected, given)


async def _tls_probe(host: str, budget_s: float = 6.0, *, sni: bool = True) -> dict[str, Any]:
    """Отдельно TLS: TCP открылся — а рукопожатие живое?

    Это третий уровень, который надо отделить от TCP и от HTTP: если TCP ок,
    а TLS вис — виноват не маршрут, а рукопожатие (сертификаты/прокси/DPI).
    """
    import asyncio
    import ssl

    if sni:
        ctx = ssl.create_default_context()
    else:
        # Без SNI и без проверки сертификата: рукопожатие должно дойти, даже
        # если фильтр рубит именно по имени в ClientHello.
        ctx = ssl._create_unverified_context()
    started = time.monotonic()
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                host, 443, ssl=ctx, server_hostname=host if sni else None
            ),
            timeout=budget_s,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__, "ms": int((time.monotonic() - started) * 1000)}
    try:
        version = writer.get_extra_info("ssl_object").version()
    except Exception:  # noqa: BLE001
        version = None
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "tls": version, "ms": int((time.monotonic() - started) * 1000)}


async def _tcp_probe(host: str, family: int, budget_s: float = 5.0) -> dict[str, Any]:
    """Сколько стоит открыть TCP-соединение ДО 443 конкретным семейством.

    Именно это отличает «сеть умерла совсем» от «IPv4 черная дыра, а IPv6
    живая» — таймаут на connect против «Network is unreachable».
    """
    import asyncio

    started = time.monotonic()
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, 443, family=family), timeout=budget_s
        )
    except Exception as exc:  # noqa: BLE001 — диагностика: важен класс
        return {
            "family": "ipv4" if family == 2 else "ipv6",
            "error": type(exc).__name__,
            "ms": int((time.monotonic() - started) * 1000),
        }
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001 — соединение уже не нужно
        pass
    return {
        "family": "ipv4" if family == 2 else "ipv6",
        "ok": True,
        "ms": int((time.monotonic() - started) * 1000),
    }


@router.get("/meta/net")
async def net_diag(request: Request) -> Any:
    """Что именно не так с сетью контейнера (24.10.2026).

    История: бот молчал, `aiohttp` к Telegram вис до таймаута по обоим путям
    (`BOT_API_SERVER` и напрямую), а `httpx` к `api.github.com` из того же
    контейнера отвечал 200. По логам это не различить — `http.client` и
    `asyncio` молчат о причине. Поэтому здесь всё сразу: DNS (какие адреса
    вообще есть), TCP-коннект по каждому семейству отдельно и оба HTTP-клиента
    на одном и том же хосте.

    Доступ — по секрету вебхука в `X-Diag-Token`.
    """
    import asyncio
    import socket

    from fastapi import HTTPException

    if not _diag_token_ok(request):
        raise HTTPException(status_code=404)

    loop = asyncio.get_running_loop()
    report: dict[str, Any] = {
        "hosts": {},
        "http": {},
        # То, что убрано из публичного `/api/meta` (S-12): версия СУБД, порт и имя
        # базы. Здесь они под секретом, потому что нужны для сверки контуров.
        "db": await _db_diagnostics(),
    }

    for host in _NET_TARGETS:
        entry: dict[str, Any] = {}
        try:
            infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            entry["dns"] = sorted(
                {
                    "ipv4" if family == socket.AF_INET else "ipv6"
                    for family, *_rest in infos
                }
            )
            # Адреса: подмена DNS выглядит именно так — TCP открывается до
            # чужого адреса, а дальше тишина.
            entry["addrs"] = sorted(
                {info[4][0] for info in infos if info[0] == socket.AF_INET}
            )[:4]
        except Exception as exc:  # noqa: BLE001
            entry["dns"] = {"error": type(exc).__name__}
        entry["tcp"] = [
            await _tcp_probe(host, socket.AF_INET),
            await _tcp_probe(host, socket.AF_INET6),
        ]
        entry["tls"] = await _tls_probe(host)
        entry["tls_no_sni"] = await _tls_probe(host, sni=False)
        report["hosts"][host] = entry

    # aiohttp — тем же клиентом, которым ходит бот (запрос без токена: нас
    # интересует дорога, а не ответ Bot API; 404 от Telegram — уже успех сети).
    import aiohttp

    for host in _NET_TARGETS:
        started = time.monotonic()
        try:
            timeout = aiohttp.ClientTimeout(total=6)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"https://{host}/") as resp:
                    report["http"][host] = {
                        "client": "aiohttp",
                        "status": resp.status,
                        "ms": int((time.monotonic() - started) * 1000),
                    }
        except Exception as exc:  # noqa: BLE001
            report["http"][host] = {
                "client": "aiohttp",
                "error": type(exc).__name__,
                "detail": str(exc)[:120],
                "ms": int((time.monotonic() - started) * 1000),
            }

    # httpx — базовая линия: он в этом контейнере работает (GitHub для
    # `/changelog`). Если он тоже упал, дело не в обработчике бота.
    try:
        import httpx

        started = time.monotonic()
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get("https://api.github.com/")
        report["http"]["httpx:api.github.com"] = {
            "client": "httpx",
            "status": resp.status_code,
            "ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001
        report["http"]["httpx:api.github.com"] = {
            "client": "httpx",
            "error": type(exc).__name__,
            "detail": str(exc)[:120],
        }

    return report


@router.get("/meta")
async def meta(request: Request) -> dict[str, Any]:
    """Паспорт живого контейнера: код, база, возможности.

    Берём именно `request.app`, а не модульный `app`: в тестах приложение
    создаётся заново через `create_app()`, и отпечаток должен отражать его,
    а не соседний инстанс.

    **Ручка публичная, поэтому в ответе нет ничего, что помогает выбирать цель
    для атаки** (аудит 26.10.2026, S-12). Убрано при правке: `db.port`,
    `db.name` и `db.server_version` — версия СУБД с точностью до патча это
    готовая подсказка «какую уязвимость пробовать», а нам она нужна только для
    диагностики. Остались те поля, по которым мы сами сверяем хосты: отпечаток
    кода, head миграций в коде и в БД, провайдер и адрес базы с маской
    (в маске нет ни идентификатора проекта, ни имени пользователя).
    Убранные поля отдаёт `/api/meta/net` — он требует секрет в `X-Diag-Token`.
    """
    fastapi_app: FastAPI = request.app
    target = db_target()
    snapshot = await _db_snapshot()
    return {
        "status": "ok",
        "code": {
            **code_fingerprint(fastapi_app),
            "alembic_head": _code_alembic_head(),
            **build_marker(),
        },
        "db": {
            "provider": target.get("provider"),
            "host": target.get("host"),
            "alembic_version": snapshot.get("alembic_version"),
            **(
                {"error": snapshot["error"]}
                if snapshot.get("error") is not None
                else {}
            ),
        },
        "features": available_features(fastapi_app),
    }


async def _db_diagnostics() -> dict[str, Any]:
    """Подробности о базе для диагностики: то, чего нет в публичном `/api/meta`.

    Доступ — только по секрету в `X-Diag-Token` (см. `_diag_token_ok`): порт,
    имя базы и версия сервера нужны, когда сверяешь, на какой именно контур
    смотрит контейнер (задача `switch-db.py`), а не посетителю приложения.
    Запрос к базе всё равно нужен один раз — берём его из того же кэша, что и
    `/api/meta` (`_db_snapshot`), поэтому диагностика не стоит лишнего запроса.
    """
    target = db_target()
    snapshot = await _db_snapshot()
    return {
        "port": target.get("port"),
        "name": target.get("name"),
        "server_version": snapshot.get("server_version"),
    }
