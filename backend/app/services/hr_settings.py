"""Настраиваемые правила HR-ядра, которые админ меняет без передеплоя.

Живут в той же таблице `admin_config` (key → value), что и настройки
наследного движка: отдельная таблица тут не нужна, а админка уже умеет
показывать произвольные ключи. Значения читаются планировщиком НА КАЖДОМ тике
(а не на старте), поэтому правка правил в мини-аппе действует сразу.

Правила касаются напоминаний о сроке поручения и автоэскалации просрочки —
именно их бриф просит «настраивать администратором».
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminConfig

KEY_REMINDERS_ENABLED = "hr.reminders.enabled"
KEY_REMIND_BEFORE_MINUTES = "hr.reminders.before_minutes"
KEY_ESCALATION_ENABLED = "hr.escalation.enabled"
KEY_TICK_MINUTES = "hr.tick.minutes"
# Один тумблер для тестового пула `[BOT]`: скрыть его следы из ленты, списков и
# отчётов, не удаляя данные. Полное удаление — отдельная операция
# (`services.hr_demo.purge`), потому что её нельзя случайно «переключить» назад.
KEY_DEMO_VISIBLE = "hr.demo.visible"

# Значения по умолчанию подобраны под смену ресторана: напомнить за час,
# проверять раз в 15 минут. Тик достаточно частый, потому что срок поручения
# (в отличие от недельных титулов) измеряется минутами, а не днями.
DEFAULT_REMINDERS_ENABLED = True
DEFAULT_REMIND_BEFORE_MINUTES = 60
DEFAULT_ESCALATION_ENABLED = True
DEFAULT_TICK_MINUTES = 15
# Пул заведён для показа/тестов, поэтому по умолчанию он ВИДЕН: скрывать его —
# осознанное действие перед показом боевой картины.
DEFAULT_DEMO_VISIBLE = True

_MAX_BEFORE_MINUTES = 24 * 60
_MIN_TICK_MINUTES = 5
_MAX_TICK_MINUTES = 24 * 60


async def _get(session: AsyncSession, key: str) -> str | None:
    # `AdminConfig.value` — колонка-строка, но `scalar()` типизирован как `Any`,
    # поэтому приводим тип явно: иначе mypy(strict) ругается на `no-any-return`.
    value = await session.scalar(select(AdminConfig.value).where(AdminConfig.key == key))
    return None if value is None else str(value)


async def _set(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(AdminConfig, key)
    if row is None:
        session.add(AdminConfig(key=key, value=value))
    else:
        row.value = value
    await session.commit()


async def _get_bool(session: AsyncSession, key: str, default: bool) -> bool:
    raw = await _get(session, key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


async def _get_int(session: AsyncSession, key: str, default: int) -> int:
    raw = await _get(session, key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def clamp_before_minutes(value: int) -> int:
    """За сколько напоминать: от 5 минут до суток."""
    return max(5, min(_MAX_BEFORE_MINUTES, value))


def clamp_tick_minutes(value: int) -> int:
    """Как часто проверять. Ниже 5 минут — лишняя нагрузка на базу."""
    return max(_MIN_TICK_MINUTES, min(_MAX_TICK_MINUTES, value))


async def get_reminders_enabled(session: AsyncSession) -> bool:
    return await _get_bool(session, KEY_REMINDERS_ENABLED, DEFAULT_REMINDERS_ENABLED)


async def get_remind_before_minutes(session: AsyncSession) -> int:
    return clamp_before_minutes(
        await _get_int(session, KEY_REMIND_BEFORE_MINUTES, DEFAULT_REMIND_BEFORE_MINUTES)
    )


async def get_escalation_enabled(session: AsyncSession) -> bool:
    return await _get_bool(session, KEY_ESCALATION_ENABLED, DEFAULT_ESCALATION_ENABLED)


async def get_tick_minutes(session: AsyncSession) -> int:
    return clamp_tick_minutes(
        await _get_int(session, KEY_TICK_MINUTES, DEFAULT_TICK_MINUTES)
    )


async def get_demo_visible(session: AsyncSession) -> bool:
    return await _get_bool(session, KEY_DEMO_VISIBLE, DEFAULT_DEMO_VISIBLE)


async def set_demo_visible(session: AsyncSession, value: bool) -> bool:
    """Единственный переключатель тестового пула: видно / не видно."""
    await _set(session, KEY_DEMO_VISIBLE, "true" if value else "false")
    return value


async def snapshot(session: AsyncSession) -> dict[str, int | bool]:
    """Текущие правила одним объектом — для админки и тестов."""
    return {
        "reminders_enabled": await get_reminders_enabled(session),
        "remind_before_minutes": await get_remind_before_minutes(session),
        "escalation_enabled": await get_escalation_enabled(session),
        "tick_minutes": await get_tick_minutes(session),
        "demo_visible": await get_demo_visible(session),
    }


async def update(
    session: AsyncSession,
    *,
    reminders_enabled: bool | None = None,
    remind_before_minutes: int | None = None,
    escalation_enabled: bool | None = None,
    tick_minutes: int | None = None,
    demo_visible: bool | None = None,
) -> dict[str, int | bool]:
    """Частичное обновление правил: приходит только то, что реально меняют."""
    if reminders_enabled is not None:
        await _set(session, KEY_REMINDERS_ENABLED, "true" if reminders_enabled else "false")
    if remind_before_minutes is not None:
        await _set(
            session,
            KEY_REMIND_BEFORE_MINUTES,
            str(clamp_before_minutes(remind_before_minutes)),
        )
    if escalation_enabled is not None:
        await _set(session, KEY_ESCALATION_ENABLED, "true" if escalation_enabled else "false")
    if tick_minutes is not None:
        await _set(session, KEY_TICK_MINUTES, str(clamp_tick_minutes(tick_minutes)))
    if demo_visible is not None:
        await _set(session, KEY_DEMO_VISIBLE, "true" if demo_visible else "false")
    return await snapshot(session)
