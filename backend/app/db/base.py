from __future__ import annotations

import os
import ssl
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import structlog

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

class Base(DeclarativeBase):
    pass

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
# Проверять ли сертификат базы. `None` — ещё не решено: значение выясняется
# либо из env, либо пробой на старте (см. `probe_ssl_verification`), потому что
# движок создаётся лениво и менять SSL-контекст у живого пула нельзя.
_ssl_verify: bool | None = None

# Параметры DSN, которые понимает libpq/psycopg, но НЕ понимает asyncpg: он
# падает на них с `TypeError: connect() got an unexpected keyword argument`.
# Строка подключения из консоли Neon приходит именно такой
# (`...?sslmode=require&channel_binding=require`), поэтому её нельзя подавать
# в движок как есть — приложение не поднялось бы вообще.
_LIBPQ_ONLY_PARAMS = frozenset(
    {"sslmode", "channel_binding", "gssencmode", "target_session_attrs"}
)


def _normalize_url(url: str) -> str:
    """
    Превращает postgres:// в postgresql+asyncpg:// для совместимости со SQLAlchemy.

    Заодно выбрасывает libpq-параметры, которых asyncpg не знает (`sslmode`,
    `channel_binding` и родственные). Режим SSL наш код решает сам
    (`_ssl_enabled_for`), поэтому потерять тут нечего — а без этой чистки
    боевой DSN из консоли хостинга роняет контейнер на подключении.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    if "?" not in url:
        return url
    parts = urlsplit(url)
    if not parts.query:
        return url
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _LIBPQ_ONLY_PARAMS
    ]
    return urlunsplit(parts._replace(query=urlencode(kept)))

def _ssl_enabled_for(url: str) -> bool:
    """Нужен ли SSL для этого DSN.

    GHG10-ops: раньше SSL включался безусловно для любого asyncpg-URL — это
    следствие жизни на Neon. Российские managed-PostgreSQL (например, БД
    Amvera) могут отдавать соединение без SSL, и тогда переключение базы
    «молча не работало»: контейнер падал на подключении. Теперь это явный
    переключатель: `DB_SSL=require|disable|auto` (по умолчанию `auto` — SSL
    включён везде, кроме локальных хостов).
    """
    mode = os.getenv("DB_SSL", "auto").strip().lower()
    if mode == "disable":
        return False
    if mode == "require":
        return True
    host = url.split("@")[-1].split("/")[0].lower()
    return not ("localhost" in host or "127.0.0.1" in host or "::1" in host)


def ssl_verify_requested() -> bool:
    """Проверять ли сертификат базы (режим `DB_SSL_VERIFY`, по умолчанию `auto`).

    * `auto` — проверить; если сертификат действительно невалиден (локальная или
      самоподписанная managed-база), перейти в непроверенный режим с громкой
      ошибкой в логе (см. `probe_ssl_verification`);
    * `require`/`on`/`true` — только с проверкой (не пройдёт — не подключимся);
    * `off`/`disable`/`false` — без проверки, осознанный выбор для своей базы.
    """
    mode = os.getenv("DB_SSL_VERIFY", "auto").strip().lower()
    if mode in {"off", "disable", "disabled", "false", "no", "0"}:
        return False
    if mode in {"require", "required", "on", "true", "yes", "1"}:
        return True
    return True  # auto — начинаем с проверки, откатываемся только по факту


def ssl_verify_enabled() -> bool:
    """Проверять ли сертификат базы. Решается один раз за процесс."""
    global _ssl_verify
    if _ssl_verify is None:
        _ssl_verify = ssl_verify_requested()
    return _ssl_verify


def _ssl_context(verify: bool) -> ssl.SSLContext:
    """SSL-контекст для соединения с базой.

    До аудита 26.10.2026 контекст ВСЕГДА создавался с `CERT_NONE` и
    `check_hostname=False`: канал шифровался, но собеседник не проверялся — кто
    встал между контейнером и базой (провайдер, прокси, отравленный DNS), читал
    и подменял запросы и ответы. Проверка сертификата включена по умолчанию
    ради именно этого; исключение — явный `DB_SSL_VERIFY=off` и разовый откат
    в `auto`, если сертификат невалиден по факту.
    """
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


# Признаки того, что сорвалась именно ПРОВЕРКА сертификата, а не связь с базой.
# Разница принципиальная: невалидный сертификат — повод осознанно перейти в
# непроверенный режим, а таймаут или отказ в доступе — нет (иначе мы бы молча
# сняли защиту из-за сетевого блипа).
_CERT_ERROR_MARKERS = (
    "certificate verify failed",
    "self-signed certificate",
    "self signed certificate",
    "certificate_verify_failed",
    "sslcertverificationerror",
    "hostname mismatch",
    "doesn't match",
)


def _is_cert_error(exc: BaseException) -> bool:
    """Есть ли в цепочке исключений ошибка проверки сертификата."""
    seen: set[int] = set()
    cursor: BaseException | None = exc
    while cursor is not None and id(cursor) not in seen:
        seen.add(id(cursor))
        if isinstance(cursor, ssl.SSLCertVerificationError):
            return True
        text = f"{type(cursor).__name__}: {cursor}".lower()
        if any(marker in text for marker in _CERT_ERROR_MARKERS):
            return True
        cursor = cursor.__cause__ or cursor.__context__
    return False


def set_ssl_verify(value: bool) -> None:
    """Сменить режим проверки сертификата и пересоздать движок.

    Живому пулу SSL-контекст не поменять, поэтому движок выбрасывается целиком и
    создастся заново при следующем обращении (см. `get_engine`).
    """
    global _engine, _sessionmaker, _ssl_verify
    if _ssl_verify == value:
        return
    _ssl_verify = value
    if _engine is not None:
        _engine = None
        _sessionmaker = None


async def probe_ssl_verification() -> bool:
    """Пробная проверка сертификата на старте. Возвращает итоговый режим.

    Аудит 26.10.2026 (S-4): проверка сертификата базы была выключена жёстко
    (`CERT_NONE`), чтобы не упасть на сертификате managed-базы. Правильное
    решение — проверить и откатиться ТОЛЬКО если сертификат в самом деле
    невалиден, сообщив об этом в логе. Так боевые Neon/Amvera работают с
    проверкой, а своя самоподписанная база продолжает подниматься — но теперь
    это видно в логе, а не является общим поведением для всех.

    Вызывается из `lifespan` ДО первого обращения к базе. В режимах `require` и
    `off` ничего не делает: там решение принято человеком.
    """
    global _engine
    mode = (os.getenv("DB_SSL_VERIFY") or "auto").strip().lower()
    if mode not in {"", "auto"}:
        return ssl_verify_enabled()
    url = _normalize_url(get_settings().database_url)
    if "asyncpg" not in url or not _ssl_enabled_for(url):
        # SQLite/локальная база без SSL: проверять нечего.
        return ssl_verify_enabled()

    from sqlalchemy import text as sa_text
    from sqlalchemy.pool import NullPool

    probe = create_async_engine(
        url,
        connect_args={"ssl": _ssl_context(True), "command_timeout": 10},
        poolclass=NullPool,
    )
    try:
        async with probe.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — решаем по типу ошибки
        if _is_cert_error(exc):
            structlog.get_logger().error(
                "db.ssl_verify_fallback",
                host=url.split("@")[-1].split("/")[0],
                error=str(exc),
                hint="сертификат базы не прошёл проверку: соединение без проверки, "
                "тушить это можно через DB_SSL_VERIFY=require",
            )
            set_ssl_verify(False)
        else:
            # Не сеть и не сертификат — скорее всего база ещₑ не принимает нас.
            # Режим не меняем: ошибку покажет первый реальный запрос.
            structlog.get_logger().warning(
                "db.ssl_probe_inconclusive", error=str(exc)
            )
    else:
        structlog.get_logger().info("db.ssl_verified")
    finally:
        await probe.dispose()
    return ssl_verify_enabled()


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker, _ssl_verify
    if _engine is None:
        settings = get_settings()
        url = _normalize_url(settings.database_url)
        
        connect_args: dict[str, Any] = {}
        
        if "asyncpg" in url:
            if _ssl_enabled_for(url):
                connect_args["ssl"] = _ssl_context(ssl_verify_enabled())
            # Небольшой таймаут на выполнение команд, чтобы не висеть вечно
            connect_args["command_timeout"] = 60

        # Пул соединений настраивается только для сетевых баз. SQLite в
        # SQLAlchemy живёт на `NullPool` и на `pool_size`/`max_overflow`
        # падает с `TypeError` — а README обещает локальный запуск на SQLite.
        pool_kwargs: dict[str, Any] = {}
        if "sqlite" not in url:
            pool_kwargs = {
                "pool_pre_ping": True,  # живое ли соединение перед использованием
                "pool_size": 5,
                "max_overflow": 10,
                "pool_recycle": 300,  # пересоздаёт соединения каждые 5 минут
            }

        _engine = create_async_engine(
            url,
            connect_args=connect_args,
            **pool_kwargs,
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
        # Диагностика «куда мы на самом деле подключились» — без пароля и DSN:
        # по этой строке видно, Neon это, Amvera или локальная база.
        structlog.get_logger().info(
            "db.engine_created",
            host=url.split("@")[-1].split("/")[0],
            ssl="ssl" in connect_args,
            # Видно в логе контейнера: шифрование есть и сертификат проверяется?
            ssl_verify=ssl_verify_enabled() if "ssl" in connect_args else None,
        )
    return _engine

def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker

async def session_dep() -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
        finally:
            await session.close()