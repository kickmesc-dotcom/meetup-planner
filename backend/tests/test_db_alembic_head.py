"""GHG10-ops: сверка head миграций В КОДЕ с `alembic_version` НА БАЗАХ.

Зачем отдельный тест. Партия может не добавлять миграций (`alembic_head` не
меняется) и всё равно «не доехать» до базы — например, резерв остался на старой
ревизии (так и было: `ep-rapid-butterfly` застрял на `0017`, пока прод был на
`0021`). Глазами такое не видно, а `/api/meta` показывает только те базы, к
которым у контейнера есть DSN. Здесь мы берём head прямо из `alembic/` (это и
есть «код-хеш») и сверяем с каждой доступной базой.

Откуда берутся DSN, чтобы не тащить секреты в репозиторий:

1. переменная окружения `DB_HEAD_CHECK_DSNS` — список через запятую;
2. иначе, если рядом с воркспейсом лежит локальный `leltokens2.txt` (машина
   оператора), DSN вычитываются оттуда.

Поведение при недоступной базе: **skip**, а не падение — сеть и спящий Neon
free-tier не должны красить прогон. Но если база ответила и версия не совпала с
кодом — тест **падает** (это и есть дрейф, который нужно поймать).

Быстрый ручной прогон только этого теста:

    DB_HEAD_CHECK_DSNS='postgresql://…' ./.venv/Scripts/python.exe -m pytest tests/test_db_alembic_head.py -q
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[1]
WORKSPACE = BACKEND.parents[1]

# Тот же регексп, что в `tools/switch-db.py`/`tools/db-rehearsal.py`: ловим DSN в
# строках токен-файла, не привязываясь к его формату.
DSN_RE = re.compile(r"postgresql(?:\+asyncpg)?://[^\s\"'<>]+")


def code_head() -> str:
    """Head миграций ИЗ КОДА — ровно то, что печатает `/api/meta` как `alembic_head`."""
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def _all_heads() -> list[str]:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return list(ScriptDirectory.from_config(cfg).get_heads())


def _candidate_dsns() -> list[str]:
    env = (os.environ.get("DB_HEAD_CHECK_DSNS") or "").strip()
    if env:
        return [d.strip() for d in env.split(",") if d.strip()]
    tokens = WORKSPACE / "leltokens2.txt"
    if not tokens.exists():
        return []
    found: list[str] = []
    for line in tokens.read_text(encoding="utf-8", errors="replace").splitlines():
        for dsn in DSN_RE.findall(line):
            if dsn not in found:
                found.append(dsn)
    return found


def _mask(dsn: str) -> str:
    """DSN без пароля — чтобы упавшее сравнение не утекло в лог CI."""
    return re.sub(r"://([^:@/]*):[^@]*@", r"://\1:***@", dsn)


async def _fetch_alembic_version(dsn: str) -> str | None:
    """`alembic_version.version_num` из конкретной базы. None, если строки нет."""
    # Ленивые импорты: сам факт импорта теста не должен создавать движок приложения.
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db.base import _normalize_url, _ssl_enabled_for

    # Убираем query-параметры (`?sslmode=require`): SSL решаем тем же правилом,
    # что и приложение (`_ssl_enabled_for`), иначе asyncpg не понимает sslmode.
    clean = dsn.split("?", 1)[0]
    url = _normalize_url(clean)
    connect_args: dict[str, object] = {}
    if "asyncpg" in url:
        if _ssl_enabled_for(url):
            import ssl

            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            connect_args["ssl"] = ctx
        connect_args["timeout"] = 10

    engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            return await conn.scalar(text("select version_num from alembic_version"))
    finally:
        await engine.dispose()


# --- целостность кода ---------------------------------------------------------


def test_migrations_have_exactly_one_head():
    """Развилка ревизий (две ветки) — уже повод падать: неясно, что применять."""
    heads = _all_heads()
    assert len(heads) == 1, f"у alembic несколько head: {heads}"


def test_code_head_is_short_revision_identifier():
    head = code_head()
    assert head, "ScriptDirectory не вернул head миграций"
    assert isinstance(head, str)
    assert " " not in head


# --- сверка с живыми базами ---------------------------------------------------


async def test_live_databases_match_code_head():
    """Каждая доступная база должна стоять ровно на head из кода.

    Недоступные базы (нет DSN / таймаут / спит Neon) пропускаем: это не дрейф.
    Ответившая база с другой версией — падение.
    """
    dsns = _candidate_dsns()
    if not dsns:
        pytest.skip("нет DSN: задайте DB_HEAD_CHECK_DSNS или положите leltokens2.txt рядом")

    head = code_head()
    checked = 0
    mismatches: list[str] = []
    unavailable: list[str] = []
    for dsn in dsns:
        try:
            version = await _fetch_alembic_version(dsn)
        except Exception as exc:  # noqa: BLE001 — недоступность ≠ дрейф
            unavailable.append(f"{_mask(dsn)} ({type(exc).__name__})")
            continue
        checked += 1
        if version != head:
            mismatches.append(f"{_mask(dsn)}: в БД {version!r}, в коде {head!r}")

    if checked == 0:
        pytest.skip("ни одна база не ответила: " + "; ".join(unavailable))

    assert not mismatches, (
        "Расхождение head миграций между кодом и БД "
        f"(проверено баз: {checked}):\n" + "\n".join(mismatches)
    )
