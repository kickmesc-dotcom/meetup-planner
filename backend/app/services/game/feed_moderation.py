"""GHG11: модерация ленты — удаление админом и «скрыть у себя» участником.

Отдельной таблицы не заводим (миграций в партии нет): контрольные записи живут
в `event_log`:

* ``feed_delete`` — админ убрал запись из ленты ДЛЯ ВСЕХ (payload `item_id`);
* ``feed_hide``   — участник скрыл запись ТОЛЬКО У СЕБЯ (payload `item_id` +
  `user_id`).

`item_id` — тот же строковый ключ, что отдаёт лента (`ach:12`, `journal:45`,
`loser:3`, …). Удаление обратимо: повторная запись/`restore` снимает пометку,
поэтому «отменить» в плашке кулдауна — это просто удаление контрольной записи.
"""
from __future__ import annotations

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    EventLog,
    GameJournalEntry,
    GameVoiceSubmission,
    GameVoiceTask,
    LoserRoll,
    MusicGameRound,
    MusicSelection,
    WeeklyChukhan,
)

log = structlog.get_logger()

DELETE_KIND = "feed_delete"
HIDE_KIND = "feed_hide"


async def _cascade_delete(session: AsyncSession, item_id: str) -> bool:
    """GHG11(3): при админском удалении записи СТЕРЕТЬ и её источник из БД.

    Иначе удаление «записи ленты» оставляло «фантомную задачу»: строка опроса /
    игровой активности жила в БД и блокировала запуск новой (или выстреливала
    позже). Удаляем строку-источник по префиксу ключа ленты. Ачивки (`ach:`) —
    исключение: это факт биографии игрока, их не стираем.

    Возвращает True, если физическое удаление произошло (→ откат «Отменить»
    невозможен).
    """
    prefix, _, raw = item_id.partition(":")
    if not raw.isdigit():
        return False
    row_id = int(raw)
    if prefix == "journal":
        await session.execute(
            sa_delete(GameJournalEntry).where(GameJournalEntry.id == row_id)
        )
    elif prefix == "voice":
        await session.execute(
            sa_delete(GameVoiceSubmission).where(
                GameVoiceSubmission.task_id == row_id
            )
        )
        await session.execute(
            sa_delete(GameVoiceTask).where(GameVoiceTask.id == row_id)
        )
    elif prefix == "music":
        await session.execute(
            sa_delete(MusicSelection).where(MusicSelection.id == row_id)
        )
    elif prefix == "music_game":
        await session.execute(
            sa_delete(MusicGameRound).where(MusicGameRound.id == row_id)
        )
    elif prefix == "loser":
        await session.execute(sa_delete(LoserRoll).where(LoserRoll.id == row_id))
    elif prefix == "chukhan":
        await session.execute(
            sa_delete(WeeklyChukhan).where(WeeklyChukhan.id == row_id)
        )
    else:
        return False
    return True


async def deleted_item_ids(session: AsyncSession) -> set[str]:
    """Ключи записей, удалённых админами (для всех)."""
    rows = await session.scalars(
        select(EventLog.payload["item_id"].as_string()).where(
            EventLog.kind == DELETE_KIND
        )
    )
    return {str(x) for x in rows.all() if x}


async def hidden_item_ids(session: AsyncSession, user_id: int) -> set[str]:
    """Ключи записей, скрытых ЭТИМ участником у себя."""
    rows = await session.scalars(
        select(EventLog.payload["item_id"].as_string()).where(
            EventLog.kind == HIDE_KIND,
            EventLog.payload["user_id"].as_integer() == int(user_id),
        )
    )
    return {str(x) for x in rows.all() if x}


async def delete_item(
    session: AsyncSession, *, item_id: str, actor: int | None = None
) -> bool:
    """Пометить запись удалённой для всех и стереть её источник из БД.

    Возвращает True, если источник физически удалён (тогда «Отменить» уже не
    вернёт запись). Идемпотентно: повторный вызов — no-op.
    """
    if item_id in await deleted_item_ids(session):
        return False
    hard = await _cascade_delete(session, item_id)
    session.add(
        EventLog(kind=DELETE_KIND, actor_user_id=actor, payload={"item_id": item_id})
    )
    await session.commit()
    log.info("game.feed_item_deleted", item_id=item_id, actor=actor, hard=hard)
    return hard


async def restore_item(session: AsyncSession, *, item_id: str) -> None:
    """Снять пометку удаления (кнопка «Отменить»)."""
    await session.execute(
        sa_delete(EventLog).where(
            EventLog.kind == DELETE_KIND,
            EventLog.payload["item_id"].as_string() == item_id,
        )
    )
    await session.commit()
    log.info("game.feed_item_restored", item_id=item_id)


async def hide_item(session: AsyncSession, *, item_id: str, user_id: int) -> None:
    """Скрыть запись у себя (идемпотентно)."""
    if item_id in await hidden_item_ids(session, user_id):
        return
    session.add(
        EventLog(kind=HIDE_KIND, actor_user_id=user_id, payload={"item_id": item_id, "user_id": int(user_id)})
    )
    await session.commit()
    log.info("game.feed_item_hidden", item_id=item_id, user_id=user_id)


async def unhide_item(session: AsyncSession, *, item_id: str, user_id: int) -> None:
    """Снять «скрыто у себя» (кнопка «Отменить»)."""
    await session.execute(
        sa_delete(EventLog).where(
            EventLog.kind == HIDE_KIND,
            EventLog.payload["item_id"].as_string() == item_id,
            EventLog.payload["user_id"].as_integer() == int(user_id),
        )
    )
    await session.commit()
    log.info("game.feed_item_unhidden", item_id=item_id, user_id=user_id)
