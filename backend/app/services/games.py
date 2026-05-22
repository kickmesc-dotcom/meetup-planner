"""GHG6 E6 — номинированные игры и связанные операции.

Чисто-CRUD сервис над таблицей `game_nominations`. Лимит 10 активных
строк (`removed_at IS NULL`) и дедуп по имени проверяются здесь, а не
БД-констрейнтами: при повторном `add_nomination(name)` для уже
soft-deleted строки реанимируем её (restore), вместо создания
дубликата.

Имена сравниваются case-insensitively по `name.strip().lower()`. На
вход принимаем сырые строки; сохраняем как пользователь ввёл
(с обрезкой пробелов по краям).
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameNomination

log = structlog.get_logger()

# Лимит активных номинаций. Поднимать без миграции — просто константу.
MAX_ACTIVE_NOMINATIONS = 10


class NominationLimitExceeded(Exception):
    """Уже 10 активных номинаций — больше добавить нельзя."""


class NominationEmpty(Exception):
    """Имя пустое или только whitespace."""


def _norm(name: str) -> str:
    return name.strip().lower()


async def list_active_nominations(session: AsyncSession) -> list[GameNomination]:
    """Все активные (не soft-deleted), отсортированные по `added_at`."""
    rows = await session.scalars(
        select(GameNomination)
        .where(GameNomination.removed_at.is_(None))
        .order_by(GameNomination.added_at.asc())
    )
    return list(rows.all())


async def count_active_nominations(session: AsyncSession) -> int:
    cnt = await session.scalar(
        select(func.count(GameNomination.id)).where(
            GameNomination.removed_at.is_(None)
        )
    )
    return int(cnt or 0)


async def add_nomination(
    session: AsyncSession, *, name: str, added_by_tg_id: int
) -> GameNomination:
    """Создать (или восстановить из soft-delete) номинацию.

    - Пустое имя → `NominationEmpty`.
    - Если уже есть активная с тем же `_norm(name)` — возвращаем её
      (идемпотентность для повторной команды от пользователя).
    - Если есть только soft-deleted — реанимируем её
      (`removed_at=None`, обновляем `added_by_tg_id`/`added_at`).
    - Если активных уже `MAX_ACTIVE_NOMINATIONS` — `NominationLimitExceeded`.
    """
    trimmed = name.strip()
    if not trimmed:
        raise NominationEmpty("empty_name")

    norm = _norm(trimmed)
    rows = await session.scalars(
        select(GameNomination).where(func.lower(GameNomination.name) == norm)
    )
    existing = list(rows.all())

    active = [r for r in existing if r.removed_at is None]
    if active:
        return active[0]

    if await count_active_nominations(session) >= MAX_ACTIVE_NOMINATIONS:
        raise NominationLimitExceeded(
            f"max_active_nominations:{MAX_ACTIVE_NOMINATIONS}"
        )

    if existing:
        # Реанимируем soft-deleted: чище, чем плодить дубликаты с тем же именем.
        row = existing[0]
        row.removed_at = None
        row.added_by_tg_id = added_by_tg_id
        row.added_at = datetime.now(timezone.utc)
        row.name = trimmed  # подхватываем актуальное написание
        await session.commit()
        await session.refresh(row)
        log.info("games.nomination_restored", id=row.id, name=row.name)
        return row

    row = GameNomination(
        name=trimmed,
        added_by_tg_id=added_by_tg_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    log.info("games.nomination_added", id=row.id, name=row.name)
    return row


async def remove_nomination(
    session: AsyncSession, *, nomination_id: int
) -> bool:
    """Soft-delete по id. Возвращает True, если запись была активной."""
    row = await session.get(GameNomination, nomination_id)
    if row is None or row.removed_at is not None:
        return False
    row.removed_at = datetime.now(timezone.utc)
    await session.commit()
    log.info("games.nomination_removed", id=row.id, name=row.name)
    return True


async def remove_nomination_by_name(
    session: AsyncSession, *, name: str
) -> GameNomination | None:
    """Soft-delete по имени (case-insensitive). Возвращает удалённую запись или None.

    Используется bot-командой `/remove_nominated_game <name>`.
    """
    norm = _norm(name)
    if not norm:
        return None
    row = await session.scalar(
        select(GameNomination).where(
            func.lower(GameNomination.name) == norm,
            GameNomination.removed_at.is_(None),
        )
    )
    if row is None:
        return None
    row.removed_at = datetime.now(timezone.utc)
    await session.commit()
    log.info("games.nomination_removed_by_name", id=row.id, name=row.name)
    return row
