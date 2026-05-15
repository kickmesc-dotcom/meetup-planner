from __future__ import annotations

import structlog
from aiogram import Router
from aiogram.types import PollAnswer

from app.db.base import get_sessionmaker
from app.services.polls import record_poll_answer

log = structlog.get_logger()
router = Router()


@router.poll_answer()
async def on_poll_answer(answer: PollAnswer) -> None:
    if not answer.user:
        return
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            await record_poll_answer(
                session,
                telegram_user_id=answer.user.id,
                chosen_option_indexes=list(answer.option_ids),
                tg_poll_id=answer.poll_id,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("poll_answer.failed", error=str(exc))
