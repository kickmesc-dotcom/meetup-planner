"""Личные подписки на автоматические уведомления.

Правило, из-за которого это появилось: автоматическое сообщение в личку
приходит человеку только тогда, когда он **сам** его включил. «Все руководители
получают сводку» — это добавление в рассылку без согласия, и первое, что делает
такой получатель, — просит выключить вообще всё.

Почему по умолчанию выключено. У сводки нет срочности: если она нужна, человек
включит её за два нажатия. Включённая по умолчанию рассылка обучает игнорировать
бота, а вместе со сводкой игнорируются и напоминания о сроке.

Почему настройка персональная, а не организационная. Глобальный тумблер
(`hr.digest.enabled`) остаётся как «не слать никому в этой организации», но он
не должен быть единственным способом защититься от чужого решения.

Почему в базе `(org_id, user_id, kind)` с уникальным ключом. Один человек может
работать в двух организациях сети; подписка на сводку в одной не обязана
включать её во второй. Уникальный ключ делает запись идемпотентной: повторное
«включить» не плодит строки.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.org_models import NotifyPref

# Виды автоматических сообщений. Список закрытый: новое сообщение обязано
# получить решение «по умолчанию выключено» осознанно, а не проскочить.
KINDS: tuple[str, ...] = ("digest",)

# Значение по умолчанию для каждого вида. Все — выключено: включение это выбор
# человека, а не побочный эффект установки.
DEFAULTS: dict[str, bool] = {kind: False for kind in KINDS}


class NotifyPrefError(Exception):
    """Неизвестный вид уведомления."""


def _check_kind(kind: str) -> str:
    code = (kind or "").strip()
    if code not in KINDS:
        raise NotifyPrefError(f"unknown_kind:{code}")
    return code


async def get(
    session: AsyncSession, *, org_id: int, user_id: int, kind: str
) -> bool:
    """Включено ли у человека это уведомление. Нет строки — выключено."""
    code = _check_kind(kind)
    row = await session.scalar(
        select(NotifyPref).where(
            NotifyPref.org_id == org_id,
            NotifyPref.user_id == user_id,
            NotifyPref.kind == code,
        )
    )
    if row is None:
        return DEFAULTS[code]
    return bool(row.enabled)


async def set_enabled(  # noqa: A001 - имя читается как «set enabled»
    session: AsyncSession,
    *,
    org_id: int,
    user_id: int,
    kind: str,
    enabled: bool,
) -> bool:
    code = _check_kind(kind)
    row = await session.scalar(
        select(NotifyPref).where(
            NotifyPref.org_id == org_id,
            NotifyPref.user_id == user_id,
            NotifyPref.kind == code,
        )
    )
    if row is None:
        row = NotifyPref(
            org_id=org_id, user_id=user_id, kind=code, enabled=enabled
        )
        session.add(row)
    else:
        row.enabled = enabled
        row.updated_at = datetime.now(UTC)
    await session.flush()
    return bool(row.enabled)


async def snapshot(
    session: AsyncSession, *, org_id: int, user_id: int
) -> dict[str, bool]:
    """Все виды разом — для экрана настроек."""
    result: dict[str, bool] = {}
    for kind in KINDS:
        result[kind] = await get(
            session, org_id=org_id, user_id=user_id, kind=kind
        )
    return result


async def subscribers(
    session: AsyncSession, *, org_id: int, kind: str
) -> set[int]:
    """Кто в организации явно включил вид. Для рассылок."""
    code = _check_kind(kind)
    rows = await session.scalars(
        select(NotifyPref.user_id).where(
            NotifyPref.org_id == org_id,
            NotifyPref.kind == code,
            NotifyPref.enabled.is_(True),
        )
    )
    return {int(value) for value in rows.all()}


__all__ = [
    "DEFAULTS",
    "KINDS",
    "NotifyPrefError",
    "get",
    "set_enabled",
    "snapshot",
    "subscribers",
]
