"""Журнал доступа к данным организации (B2B_PLATFORM_PLAN, шаг 5.5).

Зачем журнал, если есть `structlog`. Логи уходят в stdout и живут до ротации
контейнера; клиенту, который спрашивает «кто выгружал наших сотрудников»,
показать нечего. Журнал — это данные организации, они лежат рядом с ней,
удаляются вместе с ней и читаются из кабинета.

Что попадает в журнал и что нет. Пишем действия с данными и доступами:
выгрузка, запрос удаления, отмена, смена роли, приглашения, сброс бренда.
Не пишем чтение списков и обычную работу смены: журнал, в котором каждый
просмотр, перестаёт читаться, а его объём начинает стоить денег. Просмотр
сотрудника руководителем — отдельное решение, когда появится запрос от
клиента.

Почему `actor_name` — снимок, а не join. Человека можно удалить, а событие
остаётся: «выгрузил Иванов» должно читаться и после увольнения Иванова.
`actor_user_id` при этом обнуляется (FK `ON DELETE SET NULL`), поэтому имя
хранится рядом.

Почему `details` — текст с JSON, а не JSONB. Журнал не фильтруют по полям
деталей, а переносимость важнее: тесты идут на sqlite, где JSONB нет.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.org_models import AuditEvent

# Сколько журнал живёт. Полгода — компромисс: хватает, чтобы разобрать
# конфликт «кто это сделал» после отпуска, и не превращает таблицу в архив
# на годы. Срок объявлен в `docs/PRIVACY.md` и в кабинете, чтобы обещание
# было проверяемым, а не устным.
RETENTION_DAYS = 180

# Предел выдачи за один запрос: журнал читают глазами, а не выгружают.
MAX_LIMIT = 200


async def record(
    session: AsyncSession,
    *,
    org_id: int,
    action: str,
    user: User | None = None,
    target_type: str | None = None,
    target_id: int | str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Записать событие. Коммитит вызывающий: журнал не должен жить отдельно.

    `flush` нужен, чтобы у события был `id` до коммита — ответ ручки может
    содержать его номер, а тесты проверяют связь с действием.
    """
    event = AuditEvent(
        org_id=org_id,
        actor_user_id=user.id if user is not None else None,
        actor_name=(user.display_name or None) if user is not None else None,
        action=action[:48],
        target_type=target_type[:32] if target_type else None,
        target_id=str(target_id)[:64] if target_id is not None else None,
        details=(
            json.dumps(details, ensure_ascii=False, sort_keys=True)
            if details
            else None
        ),
    )
    session.add(event)
    await session.flush()
    return event


async def events(
    session: AsyncSession, org_id: int, *, limit: int = 50
) -> list[AuditEvent]:
    """Последние события организации, новые сверху."""
    capped = max(1, min(int(limit), MAX_LIMIT))
    rows = await session.scalars(
        select(AuditEvent)
        .where(AuditEvent.org_id == org_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(capped)
    )
    return list(rows)


async def prune(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Удалить события старше срока хранения. Возвращает, сколько удалено."""
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=RETENTION_DAYS)
    result = await session.execute(
        delete(AuditEvent).where(AuditEvent.created_at < cutoff)
    )
    await session.commit()
    return int(result.rowcount or 0)


__all__ = ["MAX_LIMIT", "RETENTION_DAYS", "events", "prune", "record"]
