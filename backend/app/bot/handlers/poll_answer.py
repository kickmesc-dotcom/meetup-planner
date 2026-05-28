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
            # GHG6 N2: если это feedback-полл, перехватываем тут — для него
            # есть отдельная таблица meeting_feedback и побочный эффект на
            # chukhan-веса. Остальные kind'ы (game_*, meetup, zaebal) идут
            # через стандартный record_poll_answer (poll_votes).
            from sqlalchemy import select as _select

            from app.db.models import Poll as DbPoll, User as DbUser
            from app.services.meeting_feedback import (
                POLL_KIND_MEETING_FEEDBACK,
                feedback_index_to_payload,
                submit_feedback,
            )

            db_poll = (
                await session.scalars(
                    _select(DbPoll).where(DbPoll.tg_poll_id == answer.poll_id)
                )
            ).first()

            if db_poll is not None and db_poll.kind == POLL_KIND_MEETING_FEEDBACK:
                if not answer.option_ids:
                    # Голос отозван — поллу с allows_multiple_answers=False
                    # это означает, что юзер кликнул дважды. Игнорим: запись
                    # в meeting_feedback оставляем (последний выбор побеждает).
                    return
                idx = int(answer.option_ids[0])
                rating, was_absent = feedback_index_to_payload(idx)
                if rating is None and not was_absent:
                    log.warning(
                        "meeting_feedback.bad_option_index",
                        option=idx,
                        tg_poll_id=answer.poll_id,
                    )
                    return
                meeting_id = db_poll.game_nomination_id
                if meeting_id is None:
                    log.warning(
                        "meeting_feedback.no_meeting_link", poll_id=db_poll.id
                    )
                    return
                user = (
                    await session.scalars(
                        _select(DbUser).where(DbUser.telegram_id == answer.user.id)
                    )
                ).first()
                if user is None:
                    log.warning(
                        "meeting_feedback.unknown_voter", tg_id=answer.user.id
                    )
                    return
                from app.bot.dispatcher import get_bot

                await submit_feedback(
                    session,
                    meeting_id=meeting_id,
                    user_id=user.id,
                    rating=rating,
                    was_absent=was_absent,
                    bot=get_bot(),
                )
                return

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
                    bot = None
                    sent_announce = None
                    try:
                        bot = get_bot()
                        sent_announce = await bot.send_message(
                            settings.group_chat_id,
                            f"<i>{_farewell_phrase()}</i>\n\n"
                            f"⏸ Большинство против — бот уходит на паузу.",
                            parse_mode="HTML",
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning("zaebal.farewell_send_failed", error=str(exc))
                    # G3.4: пин announce, если admin_config.polls.pin_result=true.
                    if bot is not None and sent_announce is not None:
                        from app.services.admin_config import get_polls_pin_result

                        if await get_polls_pin_result(session):
                            from app.bot.utils.pinning import pin_message_safely

                            await pin_message_safely(
                                bot,
                                chat_id=settings.group_chat_id,
                                message_id=sent_announce.message_id,
                            )
    except Exception as exc:  # noqa: BLE001
        log.warning("poll_update.failed", error=str(exc))
