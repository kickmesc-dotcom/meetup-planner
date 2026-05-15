from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from typing import Any

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

def _normalize_url(url: str) -> str:
    """
    Превращает postgres:// в postgresql+asyncpg:// для совместимости со SQLAlchemy.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url

def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        url = _normalize_url(settings.database_url)
        
        connect_args: dict[str, Any] = {}
        
        if "asyncpg" in url:
            # Создаем SSL-контекст, который разрешает соединения с Neon
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