"""Миграции под блокировкой: два контейнера, одна база (аудит 26.10.2026, S-14).

Что было не так. Контейнеров два — Amvera (боевой контур) и HF Space (стенд), и
оба при старте выполняют `alembic upgrade head` против ОДНОЙ базы
(`Dockerfile: CMD … alembic upgrade head && uvicorn …`). Пока миграции
применяются секундами, шанс столкновения мал, но он не нулевой: два одновременных
DDL за одну схему — это либо «таблица уже существует» в одном контейнере (и он не
поднимается), либо, что хуже, две записи в `alembic_version` и разошедшееся
представление о текущей ревизии.

Как теперь. Перед миграциями процесс берёт advisory-lock в Postgres
(`pg_try_advisory_lock`, неблокирующий) и ждёт освобождения, а не наступает.
Второй контейнер просто подождёт, пока первый применит миграции, и продолжит
старт — с уже актуальной схемой.

Почему advisory-lock, а не таблица. Это блокировка уровня сервера: она снимается
автоматически вместе с соединением, поэтому «вечно залипшего» лока не бывает —
упавший контейнер не блокирует базу навсегда. Отдельной таблицы и миграции для
неё не нужно.

Что если ждать пришлось слишком долго (`DB_MIGRATE_LOCK_WAIT_SECONDS`, по
умолчанию 5 минут). Миграции НЕ применяются, процесс завершается с ошибкой, а
оркестратор перезапускает контейнер: пустить второй набор DDL «на всякий случай»
— это ровно тот сценарий, который мы и убираем.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import structlog

log = structlog.get_logger()

# Постоянное число: `pg_advisory_lock` принимает произвольный ключ, и нам важно
# лишь то, чтобы он был один и тот же во всех процессах. Значение — из головы,
# его не с чем спутать.
MIGRATIONS_LOCK_KEY = 771144
DEFAULT_WAIT_SECONDS = 300.0
# Как часто пробовать взять лок, пока его держит другой контейнер.
RETRY_INTERVAL_SECONDS = 2.0


def wait_seconds() -> float:
    """Сколько ждать лок. `DB_MIGRATE_LOCK_WAIT_SECONDS=off` — ждать бесконечно."""
    raw = (os.getenv("DB_MIGRATE_LOCK_WAIT_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_WAIT_SECONDS
    if raw.lower() in {"off", "none", "false", "0"}:
        return float("inf")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_WAIT_SECONDS


def root() -> Path:
    """Каталог приложения (`/app` в контейнере): там лежат `alembic.ini`."""
    return Path(__file__).resolve().parents[2]


def alembic_config():  # noqa: ANN201 - объект alembic.config.Config
    """Конфигурация alembic с абсолютными путями: не зависим от текущего каталога."""
    from alembic.config import Config

    config = Config(str(root() / "alembic.ini"))
    config.set_main_option("script_location", str(root() / "alembic"))
    return config


def run_upgrade() -> None:
    """Применить миграции до head. Синхронно — alembic так и устроен."""
    from alembic import command

    command.upgrade(alembic_config(), "head")


def asyncpg_dsn(url: str) -> str:
    """DSN для чистого asyncpg: схема без `+asyncpg` и без query-параметров.

    Параметры отбрасываем сознательно: `_normalize_url` уже выбросил то, что
    понимает только libpq, а asyncpg передаёт оставшиеся как аргументы
    подключения и падает на незнакомых. SSL задаём сами (см. `_connect_kwargs`).
    """
    dsn = url.split("?", 1)[0]
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


def _connect_kwargs(url: str) -> dict[str, object]:
    from app.db.base import _ssl_context, _ssl_enabled_for, ssl_verify_enabled

    if not _ssl_enabled_for(url):
        return {}
    return {"ssl": _ssl_context(ssl_verify_enabled())}


async def acquire_lock(connection, *, wait: float) -> bool:  # noqa: ANN001 - asyncpg.Connection
    """Взять advisory-lock, подождав освобождения. `False` — не дождались."""
    deadline = time.monotonic() + wait
    reported = False
    while True:
        if await connection.fetchval("SELECT pg_try_advisory_lock($1)", MIGRATIONS_LOCK_KEY):
            return True
        if time.monotonic() >= deadline:
            log.error("db.migrate_lock_timeout", waited_seconds=wait)
            return False
        if not reported:
            reported = True
            log.warning("db.migrate_waiting_for_lock", key=MIGRATIONS_LOCK_KEY)
        await asyncio.sleep(RETRY_INTERVAL_SECONDS)


async def upgrade_with_lock(wait: float | None = None) -> bool:
    """Миграции под локом. `False` — лок не дождались, применять не стали."""
    from app.config import get_settings
    from app.db.base import _normalize_url

    url = _normalize_url(get_settings().database_url)
    if "asyncpg" not in url:
        # SQLite и прочая локальная база: гонки за схему нет по определению.
        await asyncio.to_thread(run_upgrade)
        return True

    import asyncpg

    connection = await asyncpg.connect(asyncpg_dsn(url), **_connect_kwargs(url))
    try:
        if not await acquire_lock(connection, wait=wait if wait is not None else wait_seconds()):
            return False
        log.info("db.migrate_lock_acquired", key=MIGRATIONS_LOCK_KEY)
        try:
            # Миграции — блокирующий вызов со своим event loop внутри: уводим его
            # в поток, чтобы не путать два цикла в одном процессе.
            await asyncio.to_thread(run_upgrade)
        finally:
            await connection.execute(
                "SELECT pg_advisory_unlock($1)", MIGRATIONS_LOCK_KEY
            )
        return True
    finally:
        await connection.close()


def main(argv: list[str] | None = None) -> int:
    """Точка входа `python -m app.db.migrate` (её же вызывает Dockerfile)."""
    from app.config import get_settings
    from app.db.base import _normalize_url

    del argv
    url = _normalize_url(get_settings().database_url)
    structlog.configure()
    host = url.split("@")[-1].split("/")[0]
    log.info("db.migrate_start", host=host)
    if "asyncpg" not in url:
        run_upgrade()
        return 0
    applied = asyncio.run(upgrade_with_lock())
    if not applied:
        # Ненулевой код — контейнер перезапустится и попробует снова, уже без
        # второго набора DDL параллельно первому.
        print(
            "не дождались блокировки миграций: другой контейнер применяет их прямо сейчас",
            file=sys.stderr,
        )
        return 1
    log.info("db.migrate_done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
