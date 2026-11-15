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
#
# 04.11.2026 к сводке добавились напоминания о сроке и эскалации: правило
# владельца — «любое автоматическое сообщение в личку только по явному
# выбору» — не может действовать для одного вида из трёх.
KINDS: tuple[str, ...] = ("digest", "deadline", "escalation", "events")

# Значение по умолчанию для каждого вида. Рассылки (сводка, напоминания,
# эскалации) выключены: включение — выбор человека, а не побочный эффект
# установки.
#
# `events` — исключение и включён: это не рассылка, а адресное событие по твоим
# же поручениям и проблеме («назначили», «просрочили»). Молчать о том, что на
# тебя только что повесили задачу, — хуже, чем разбудить; от потока защищает
# потолок в `web_push`, а этот тумблер — чтобы прекратить совсем.
DEFAULTS: dict[str, bool] = {kind: False for kind in KINDS}
DEFAULTS["events"] = True


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


async def allowed_users(
    session: AsyncSession, *, org_id: int, kind: str, user_ids: list[int]
) -> set[int]:
    """Кому из этих людей можно прислать вид — с учётом значения по умолчанию.

    Нужен обоим режимам: для `events` (включён по умолчанию) — все, кроме тех,
    кто явно выключил; для рассылок — только явно включившие. `subscribers`
    этого не умеет: он видит только строки «включено».
    """
    code = _check_kind(kind)
    wanted = {int(uid) for uid in user_ids}
    if not wanted:
        return set()
    rows = await session.execute(
        select(NotifyPref.user_id, NotifyPref.enabled).where(
            NotifyPref.org_id == org_id,
            NotifyPref.kind == code,
            NotifyPref.user_id.in_(wanted),
        )
    )
    stated = {int(uid): bool(flag) for uid, flag in rows.all()}
    if DEFAULTS[code]:
        return {uid for uid in wanted if stated.get(uid, True)}
    return {uid for uid in wanted if stated.get(uid, False)}


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
    "allowed_users",
    "get",
    "set_enabled",
    "snapshot",
    "subscribers",
]
