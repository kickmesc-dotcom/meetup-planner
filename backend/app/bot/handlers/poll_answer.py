"""Приём ответов на опросы бота.

Рабочий контур: опросы встреч и пост-фактум обратная связь по смене
(`meeting_feedback` → таблица `meeting_feedback`). Шуточные поллы (мьюзик-гейм,
голосовые задания, номинации, голосование за паузу бота) уехали в `app/_legacy`
вместе со своими механиками, поэтому их ветки отсюда убраны: обработчиков,
которые бы эти поллы создавали, в рабочем контуре больше нет.

GHG6 N2: feedback-полл перехватываем ДО общей записи — у него отдельная таблица,
а остальные ответы идут через стандартный `record_poll_answer` (poll_votes).
"""
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
