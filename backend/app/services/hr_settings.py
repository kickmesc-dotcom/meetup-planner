"""Настраиваемые правила HR-ядра, которые админ меняет без передеплоя.

Живут в той же таблице `admin_config` (key → value), что и настройки
наследного движка: отдельная таблица тут не нужна, а админка уже умеет
показывать произвольные ключи. Значения читаются планировщиком НА КАЖДОМ тике
(а не на старте), поэтому правка правил в мини-аппе действует сразу.

Правила касаются напоминаний о сроке поручения и автоэскалации просрочки —
именно их бриф просит «настраивать администратором».
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import AdminConfig
from app.services import hr_worktime

KEY_REMINDERS_ENABLED = "hr.reminders.enabled"
KEY_REMIND_BEFORE_MINUTES = "hr.reminders.before_minutes"
KEY_ESCALATION_ENABLED = "hr.escalation.enabled"
KEY_TICK_MINUTES = "hr.tick.minutes"
# Один тумблер для тестового пула `[BOT]`: скрыть его следы из ленты, списков и
# отчётов, не удаляя данные. Полное удаление — отдельная операция
# (`services.hr_demo.purge`), потому что её нельзя случайно «переключить» назад.
KEY_DEMO_VISIBLE = "hr.demo.visible"
# Рабочие часы ресторана и «тихие часы». Управляющий задаёт их один раз, все
# смены равняются на это время: ночные алерты в 03:41 — баг, а не забота.
KEY_WORK_OPEN = "hr.work.open"
KEY_WORK_CLOSE = "hr.work.close"
KEY_NOTIFY_ONLY_WORK_HOURS = "hr.notify.only_work_hours"
KEY_NOTIFY_LEAD_MINUTES = "hr.notify.lead_minutes"
KEY_NOTIFY_TAIL_MINUTES = "hr.notify.tail_minutes"
# Глобальный мьют управляющего: до какого момента не слать ничего.
KEY_NOTIFY_MUTED_UNTIL = "hr.notify.muted_until"

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

DEFAULT_WORK_OPEN = time(10, 0)
DEFAULT_WORK_CLOSE = time(23, 0)
DEFAULT_NOTIFY_ONLY_WORK_HOURS = True
DEFAULT_NOTIFY_LEAD_MINUTES = 60
DEFAULT_NOTIFY_TAIL_MINUTES = 60

# Максимальный мьют — месяц вперёд: дальше это уже «выключи уведомления».
MAX_MUTE_HOURS = 24 * 30

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


# --------------------------------------------------------------------------
# Рабочие часы и тихие часы
# --------------------------------------------------------------------------


def local_now(now: datetime | None = None) -> datetime:
    """Текущее время в часовом поясе ресторана (`SCHEDULER_TZ`)."""
    tz = ZoneInfo(get_settings().scheduler_tz)
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(tz)


async def get_work_open(session: AsyncSession) -> time:
    return hr_worktime.parse_hhmm(
        await _get(session, KEY_WORK_OPEN), DEFAULT_WORK_OPEN
    )


async def get_work_close(session: AsyncSession) -> time:
    return hr_worktime.parse_hhmm(
        await _get(session, KEY_WORK_CLOSE), DEFAULT_WORK_CLOSE
    )


async def get_only_work_hours(session: AsyncSession) -> bool:
    return await _get_bool(
        session, KEY_NOTIFY_ONLY_WORK_HOURS, DEFAULT_NOTIFY_ONLY_WORK_HOURS
    )


async def get_lead_minutes(session: AsyncSession) -> int:
    return max(
        0,
        min(
            12 * 60,
            await _get_int(
                session, KEY_NOTIFY_LEAD_MINUTES, DEFAULT_NOTIFY_LEAD_MINUTES
            ),
        ),
    )


async def get_tail_minutes(session: AsyncSession) -> int:
    return max(
        0,
        min(
            12 * 60,
            await _get_int(
                session, KEY_NOTIFY_TAIL_MINUTES, DEFAULT_NOTIFY_TAIL_MINUTES
            ),
        ),
    )


async def get_muted_until(session: AsyncSession) -> datetime | None:
    raw = await _get(session, KEY_NOTIFY_MUTED_UNTIL)
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


async def mute_for_hours(session: AsyncSession, hours: int) -> datetime:
    """Заглушить уведомления на N часов (24ч / 3 суток / неделю / месяц)."""
    span = max(1, min(MAX_MUTE_HOURS, int(hours)))
    until = datetime.now(UTC) + timedelta(hours=span)
    await _set(session, KEY_NOTIFY_MUTED_UNTIL, until.isoformat())
    return until


async def clear_mute(session: AsyncSession) -> None:
    await _set(session, KEY_NOTIFY_MUTED_UNTIL, "")


async def notifications_allowed(
    session: AsyncSession, now: datetime | None = None
) -> tuple[bool, str]:
    """Можно ли сейчас слать Telegram-алерты. Возвращает (можно, причина).

    Причина нужна, чтобы тест и лог объясняли молчание: `muted` (ручной мьют),
    `quiet_hours` (вне рабочего окна), `ok`. В приложении уведомления живут
    отдельно — тихие часы глушат только доставку в чат.
    """
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    muted_until = await get_muted_until(session)
    if muted_until is not None and moment < muted_until:
        return False, "muted"
    if not await get_only_work_hours(session):
        return True, "ok"
    local = moment.astimezone(ZoneInfo(get_settings().scheduler_tz))
    inside = hr_worktime.in_work_window(
        local,
        opens_at=await get_work_open(session),
        closes_at=await get_work_close(session),
        lead_minutes=await get_lead_minutes(session),
        tail_minutes=await get_tail_minutes(session),
    )
    return (True, "ok") if inside else (False, "quiet_hours")


async def work_hours_snapshot(session: AsyncSession) -> dict[str, object]:
    """Рабочие часы и мьют отдельным блоком (для экрана настроек)."""
    muted_until = await get_muted_until(session)
    return {
        "work_open": hr_worktime.format_hhmm(await get_work_open(session)),
        "work_close": hr_worktime.format_hhmm(await get_work_close(session)),
        "notify_only_work_hours": await get_only_work_hours(session),
        "notify_lead_minutes": await get_lead_minutes(session),
        "notify_tail_minutes": await get_tail_minutes(session),
        "muted_until": muted_until.isoformat() if muted_until else None,
        "notifications_allowed": (await notifications_allowed(session))[0],
    }


async def snapshot(session: AsyncSession) -> dict[str, int | bool | str | None]:
    """Текущие правила одним объектом — для админки и тестов."""
    return {
        "reminders_enabled": await get_reminders_enabled(session),
        "remind_before_minutes": await get_remind_before_minutes(session),
        "escalation_enabled": await get_escalation_enabled(session),
        "tick_minutes": await get_tick_minutes(session),
        "demo_visible": await get_demo_visible(session),
        **(await work_hours_snapshot(session)),
    }


async def update(
    session: AsyncSession,
    *,
    reminders_enabled: bool | None = None,
    remind_before_minutes: int | None = None,
    escalation_enabled: bool | None = None,
    tick_minutes: int | None = None,
    demo_visible: bool | None = None,
    work_open: str | None = None,
    work_close: str | None = None,
    notify_only_work_hours: bool | None = None,
    notify_lead_minutes: int | None = None,
    notify_tail_minutes: int | None = None,
) -> dict[str, int | bool | str | None]:
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
    if work_open is not None:
        await _set(
            session,
            KEY_WORK_OPEN,
            hr_worktime.format_hhmm(
                hr_worktime.parse_hhmm(work_open, DEFAULT_WORK_OPEN)
            ),
        )
    if work_close is not None:
        await _set(
            session,
            KEY_WORK_CLOSE,
            hr_worktime.format_hhmm(
                hr_worktime.parse_hhmm(work_close, DEFAULT_WORK_CLOSE)
            ),
        )
    if notify_only_work_hours is not None:
        await _set(
            session,
            KEY_NOTIFY_ONLY_WORK_HOURS,
            "true" if notify_only_work_hours else "false",
        )
    if notify_lead_minutes is not None:
        await _set(
            session,
            KEY_NOTIFY_LEAD_MINUTES,
            str(max(0, min(12 * 60, notify_lead_minutes))),
        )
    if notify_tail_minutes is not None:
        await _set(
            session,
            KEY_NOTIFY_TAIL_MINUTES,
            str(max(0, min(12 * 60, notify_tail_minutes))),
        )
    return await snapshot(session)
