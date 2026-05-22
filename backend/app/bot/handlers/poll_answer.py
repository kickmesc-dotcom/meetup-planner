from __future__ import annotations

import structlog
from aiogram import Router
from aiogram.types import Poll, PollAnswer

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


@router.poll()
async def on_poll_update(poll: Poll) -> None:
    """Update про сам полл — приходит при изменении voter_count и при закрытии.

    При `is_closed=True` диспетчируем по `Poll.kind` (наша БД-запись):
    - `game_choice` / `game_when` — E6: победитель → объявление в чат и опц.
      follow-up или создание Meeting (см. services/games_poll).
    - иначе — zaebal-полл (legacy без kind: 2 опции, «за/против»).
    """
    if not poll.is_closed:
        return
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            from app.db.models import Poll as DbPoll
            from sqlalchemy import select as _select

            db_poll = (
                await session.scalars(
                    _select(DbPoll).where(DbPoll.tg_poll_id == poll.id)
                )
            ).first()
            kind = db_poll.kind if db_poll else None

            if kind in ("game_choice", "game_when"):
                from app.bot.dispatcher import get_bot
                from app.config import get_settings
                from app.services.games_poll import (
                    handle_game_choice_closed,
                    handle_game_when_closed,
                )

                settings = get_settings()
                if not settings.group_chat_id:
                    return
                bot = get_bot()
                if kind == "game_choice":
                    await handle_game_choice_closed(
                        session, bot, poll=db_poll, chat_id=settings.group_chat_id
                    )
                else:
                    await handle_game_when_closed(
                        session, bot, poll=db_poll, chat_id=settings.group_chat_id
                    )
                return

            # zaebal-полл — 2 опции, индекс 0 = «за».
            options = list(poll.options or [])
            yes = options[0].voter_count if options else 0
            no = options[1].voter_count if len(options) > 1 else 0
            from app.services.zaebal import handle_zaebal_poll_closed

            paused = await handle_zaebal_poll_closed(
                session, tg_poll_id=poll.id, yes_votes=yes, no_votes=no
            )
            if paused:
                from app.bot.dispatcher import get_bot
                from app.config import get_settings
                from app.services.zaebal import _farewell_phrase

                settings = get_settings()
                if settings.group_chat_id:
                    try:
                        bot = get_bot()
                        await bot.send_message(
                            settings.group_chat_id,
                            f"<i>{_farewell_phrase()}</i>\n\n"
                            f"⏸ Большинство против — бот уходит на паузу.",
                            parse_mode="HTML",
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning("zaebal.farewell_send_failed", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.warning("poll_update.failed", error=str(exc))
