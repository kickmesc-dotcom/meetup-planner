"""Ожидающее действие в боте: «жду фото» / «жду причину проблемы».

Бот в личке работает без FSM-хранилища (в проекте его нет), поэтому «следующее
сообщение относится к задаче N» надо где-то запомнить. Кладём в `admin_config`
(ключ на Telegram ID) — в отличие от памяти процесса, это переживает рестарт
контейнера, а цена — один point-SELECT.

Состояние одно на пользователя (`kind`): нельзя одновременно ждать и фото, и
комментарий к проблеме. Новое ожидание перетирает старое — так и задумано,
сотрудник не может «застрять» в непонятном режиме.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminConfig

KIND_TASK_PHOTO = "task_photo"
KIND_TASK_ISSUE = "task_issue"
KIND_CHECKLIST_PHOTO = "checklist_photo"


@dataclass(frozen=True)
class Pending:
    kind: str
    target_id: int
    extra: dict

    def as_json(self) -> str:
        return json.dumps(
            {"kind": self.kind, "target_id": self.target_id, "extra": self.extra},
            ensure_ascii=False,
        )


def _key(telegram_id: int) -> str:
    return f"hr.pending.{telegram_id}"


def parse(raw: str | None) -> Pending | None:
    """Разобрать сохранённое состояние. Мусор в значении — просто «нет ожидания»."""
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    kind = payload.get("kind")
    target = payload.get("target_id")
    if not isinstance(kind, str) or not isinstance(target, int):
        return None
    extra = payload.get("extra")
    return Pending(kind=kind, target_id=target, extra=extra if isinstance(extra, dict) else {})


async def set_pending(
    session: AsyncSession, telegram_id: int, pending: Pending
) -> None:
    key = _key(telegram_id)
    value = pending.as_json()
    row = await session.get(AdminConfig, key)
    if row is None:
        session.add(AdminConfig(key=key, value=value))
    else:
        row.value = value
    await session.commit()


async def get_pending(session: AsyncSession, telegram_id: int) -> Pending | None:
    row = await session.get(AdminConfig, _key(telegram_id))
    return parse(row.value if row else None)


async def clear_pending(session: AsyncSession, telegram_id: int) -> None:
    row = await session.get(AdminConfig, _key(telegram_id))
    if row is not None:
        await session.delete(row)
        await session.commit()
