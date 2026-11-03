from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.db.base import (
    Base,
    _normalize_url,
    _ssl_context,
    _ssl_enabled_for,
    ssl_verify_enabled,
)
import app.db.models  # noqa: F401  registers all tables

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", _normalize_url(get_settings().database_url))


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _connect_args(url: str) -> dict:
    """SSL по тому же правилу, что у приложения (`DB_SSL`).

    Раньше здесь стоял безусловный `ssl: True` для любого asyncpg-DSN —
    следствие жизни на Neon. На базе без SSL (локальный Postgres для
    проверки восстановления, self-hosted managed-PG) миграции падали на
    «rejected SSL upgrade», то есть проверить откат было негде. Теперь
    режим решает `_ssl_enabled_for`: `DB_SSL=disable` выключает SSL,
    `auto` включает его для всего, кроме localhost.
    """
    if "asyncpg" not in url:
        return {}
    if not _ssl_enabled_for(url):
        return {}
    return {"ssl": _ssl_context(ssl_verify_enabled())}


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = config.get_main_option("sqlalchemy.url")
    connectable = async_engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=_connect_args(cfg["sqlalchemy.url"]),
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
