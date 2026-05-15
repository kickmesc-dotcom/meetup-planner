from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User

log = structlog.get_logger()

# 6 предзаданных цветов с проверкой контраста на TG light/dark темах.
PALETTE = [
    "#22c55e",  # green
    "#3b82f6",  # blue
    "#f59e0b",  # amber
    "#ef4444",  # red
    "#a855f7",  # purple
    "#06b6d4",  # cyan
]


def color_for_user(telegram_id: int) -> str:
    """Детерминированно выдаёт цвет из палитры по telegram_id.
    Используется в seed и при ad-hoc создании юзеров вне whitelist.
    """
    return PALETTE[abs(telegram_id) % len(PALETTE)]


async def seed_users(session: AsyncSession) -> None:
    settings = get_settings()
    pairs = settings.whitelist_pairs
    if not pairs:
        log.warning("seed.skip_empty_whitelist")
        return

    for idx, (tg_id, name) in enumerate(pairs):
        existing = await session.scalar(select(User).where(User.telegram_id == tg_id))
        color = PALETTE[idx % len(PALETTE)]
        if existing is None:
            session.add(
                User(
                    telegram_id=tg_id,
                    display_name=name,
                    color_hex=color,
                )
            )
            log.info("seed.user_created", telegram_id=tg_id, name=name)
        else:
            updated = False
            if existing.display_name != name:
                existing.display_name = name
                updated = True
            if existing.color_hex != color:
                existing.color_hex = color
                updated = True
            if updated:
                log.info("seed.user_updated", telegram_id=tg_id)
    await session.commit()
