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

from app.db.models import EventLog

log = structlog.get_logger()

DELETE_KIND = "feed_delete"
HIDE_KIND = "feed_hide"


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


async def delete_item(session: AsyncSession, *, item_id: str, actor: int | None = None) -> None:
    """Пометить запись удалённой для всех (идемпотентно)."""
    if item_id in await deleted_item_ids(session):
        return
    session.add(EventLog(kind=DELETE_KIND, actor_user_id=actor, payload={"item_id": item_id}))
    await session.commit()
    log.info("game.feed_item_deleted", item_id=item_id, actor=actor)


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
