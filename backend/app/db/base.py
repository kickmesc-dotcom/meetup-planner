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


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        url = _normalize_url(settings.database_url)
        
        connect_args: dict[str, Any] = {}
        
        if "asyncpg" in url:
            if _ssl_enabled_for(url):
                # Создаем SSL-контекст: Neon требует SSL, а сам сертификат
                # (managed-база) не всегда в системных корнях.
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                connect_args["ssl"] = ctx
            # Небольшой таймаут на выполнение команд, чтобы не висеть вечно
            connect_args["command_timeout"] = 60

        _engine = create_async_engine(
            url,
            pool_pre_ping=True,  # Проверяет живое ли соединение перед использованием
            pool_size=5,
            max_overflow=10,
            pool_recycle=300,    # Пересоздает соединения каждые 5 минут
            connect_args=connect_args,
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
        # Диагностика «куда мы на самом деле подключились» — без пароля и DSN:
        # по этой строке видно, Neon это, Amvera или локальная база.
        structlog.get_logger().info(
            "db.engine_created",
            host=url.split("@")[-1].split("/")[0],
            ssl="ssl" in connect_args,
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