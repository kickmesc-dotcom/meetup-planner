"""GHG6 E11 — глобальная пауза публикаций бота.

Модель: одна активная строка в `bot_pause` (`ended_at IS NULL`). При старте
паузы фиксируется snapshot всех master-toggles, master-toggles перезаписываются
в false. При снятии (по времени или вручную) — restore из snapshot.

Reasons (для логов/UI):
- `manual_admin` — кнопка «⏸ Поставить на паузу» в админке.
- `zaebal_threshold` — порог /zaebal набран в чате.
- `zaebal_vote` — Telegram-полл /zaebal-vote закрылся «за».
- `auto_monthly` — авто-зэбал бота (раз в месяц).

Auto-restore: scheduler.py при каждом тике должен звать
`maybe_auto_restore(session)` — функция проверяет, не истёк ли `ends_at`
у активной паузы. Это дешёвый запрос. Альтернатива — отдельный DateTrigger
на ends_at, но он усложнит код при ручном изменении длительности.

Чистые функции:
- `build_snapshot(scheduled, reactions, zaebal)` — собирает плоский dict из
  трёх агрегатов настроек.
- `apply_pause_overrides(snapshot)` — возвращает dict, которым нужно записать
  бэк настройки на время паузы (все master-toggles → false).
- `restore_from_snapshot(snapshot)` — возвращает значения, которыми нужно
  восстановить настройки.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BotPause
from app.services.admin_config import (
    get_bot_reactions_settings,
    get_scheduled_settings,
    set_bot_reactions_settings,
    set_scheduled_settings,
)

log = structlog.get_logger()

VALID_REASONS = {"manual_admin", "zaebal_threshold", "zaebal_vote", "auto_monthly"}

# P2.2: причины, инициированные чатом (команда/voot/авто-зэбал). Только для них
# при авто-разморозке по таймеру шлём «злобное приветствие» в группу. Паузы из
# админки (manual_admin) размораживаются молча.
CHAT_INITIATED_REASONS = {"zaebal_threshold", "zaebal_vote", "auto_monthly"}


def should_announce_restore(reason: str, announce: bool) -> bool:
    """Чистый предикат для P2.2.c: анонсить возвращение бота в группу?
    Только если вызывающий разрешил анонс (авто-разморозка) И пауза была
    инициирована чатом. Ручное снятие (announce=False) и manual_admin-паузы
    — silent."""
    return announce and reason in CHAT_INITIATED_REASONS


def _format_absence_hours(started_at: datetime, ended_at: datetime) -> int:
    """Сколько целых часов длилась пауза (минимум 1 для читаемости).
    Нормализуем tz: драйвер может вернуть `started_at` как naive — считаем
    его UTC, чтобы вычитание с aware `ended_at` не упало."""
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=timezone.utc)
    seconds = (ended_at - started_at).total_seconds()
    return max(1, round(seconds / 3600))


def build_snapshot(
    scheduled: dict, reactions: dict, zaebal: dict
) -> dict[str, Any]:
    """Сериализуемый snapshot всех настроек, которые пауза перезаписывает.

    Структура snapshot повторяет структуру входов — это упрощает restore
    (передаём напрямую в set_scheduled_settings / set_bot_reactions_settings).
    """
    return {
        "scheduled": scheduled,
        "reactions": reactions,
        "zaebal": zaebal,
    }


def apply_pause_overrides(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Что записать в admin_config на время паузы: всё master-toggles → false.

    Только enabled-флаги меняются; числовые значения (per_day/окна/тики)
    оставляем как есть. Это безопаснее: при restore мы и так выставим
    эти значения, но если restore почему-то сорвётся (DB crash), цифры
    хотя бы не превратятся в дефолты.
    """
    sched = snapshot.get("scheduled") or {}
    react = snapshot.get("reactions") or {}
    zaebal = snapshot.get("zaebal") or {}

    # Возвращаем тот же формат, что принимают set_*_settings, но с enabled=False.
    scheduled_override = {
        "reminders": {"enabled": False, "tick_minutes": (sched.get("reminders") or {}).get("tick_minutes", 5)},
        "loser": {**(sched.get("loser") or {}), "enabled": False},
        "phrases": {**(sched.get("phrases") or {}), "enabled": False},
        "avatars": {**(sched.get("avatars") or {}), "enabled": False},
        "birthdays": {"alerts_enabled": False},
        "chukhan": sched.get("chukhan") or {},  # без enabled-флага у чухана
    }
    reactions_override = {
        "mention_enabled": False,
        "reply_all_enabled": False,
        "reply_except_phrases_enabled": False,
    }
    zaebal_override = {**zaebal, "auto_enabled": False}
    return {
        "scheduled": scheduled_override,
        "reactions": reactions_override,
        "zaebal": zaebal_override,
    }


async def get_active_pause(session: AsyncSession) -> BotPause | None:
    return await session.scalar(
        select(BotPause).where(BotPause.ended_at.is_(None))
    )


async def is_paused(session: AsyncSession) -> bool:
    return (await get_active_pause(session)) is not None


# Заглушка для zaebal settings — модуль zaebal_settings подтянется отдельно
# (см. ниже). Делаем сразу здесь, чтобы не плодить файлы.

ZAEBAL_THRESHOLD_KEY = "zaebal.threshold"  # default 2 (из 5)
ZAEBAL_DURATION_DAYS_KEY = "zaebal.duration_days"  # default 3
ZAEBAL_POLL_HOURS_KEY = "zaebal.poll_hours"  # default 24
ZAEBAL_VOTE_DURATION_DAYS_KEY = "zaebal.vote_duration_days"  # default 7
ZAEBAL_AUTO_ENABLED_KEY = "zaebal.auto_enabled"  # default false
ZAEBAL_AUTO_MAX_PER_MONTH_KEY = "zaebal.auto_max_per_month"  # default 1


async def get_zaebal_settings(session: AsyncSession) -> dict[str, Any]:
    from app.services.admin_config import _get_bool, _get_int, _get_value

    return {
        "threshold": int(await _get_int(session, ZAEBAL_THRESHOLD_KEY, 2)),
        "duration_days": int(await _get_int(session, ZAEBAL_DURATION_DAYS_KEY, 3)),
        "poll_hours": int(await _get_int(session, ZAEBAL_POLL_HOURS_KEY, 24)),
        "vote_duration_days": int(
            await _get_int(session, ZAEBAL_VOTE_DURATION_DAYS_KEY, 7)
        ),
        "auto_enabled": await _get_bool(session, ZAEBAL_AUTO_ENABLED_KEY, False),
        "auto_max_per_month": int(
            await _get_int(session, ZAEBAL_AUTO_MAX_PER_MONTH_KEY, 1)
        ),
    }


async def set_zaebal_settings(
    session: AsyncSession, body: dict[str, Any]
) -> None:
    from app.services.admin_config import _set_value

    if "threshold" in body:
        await _set_value(session, ZAEBAL_THRESHOLD_KEY, str(int(body["threshold"])))
    if "duration_days" in body:
        await _set_value(
            session, ZAEBAL_DURATION_DAYS_KEY, str(int(body["duration_days"]))
        )
    if "poll_hours" in body:
        await _set_value(session, ZAEBAL_POLL_HOURS_KEY, str(int(body["poll_hours"])))
    if "vote_duration_days" in body:
        await _set_value(
            session,
            ZAEBAL_VOTE_DURATION_DAYS_KEY,
            str(int(body["vote_duration_days"])),
        )
    if "auto_enabled" in body:
        await _set_value(
            session,
            ZAEBAL_AUTO_ENABLED_KEY,
            "true" if body["auto_enabled"] else "false",
        )
    if "auto_max_per_month" in body:
        await _set_value(
            session,
            ZAEBAL_AUTO_MAX_PER_MONTH_KEY,
            str(int(body["auto_max_per_month"])),
        )


async def _snapshot_now(session: AsyncSession) -> dict[str, Any]:
    scheduled = await get_scheduled_settings(session)
    reactions = await get_bot_reactions_settings(session)
    zaebal = await get_zaebal_settings(session)
    return build_snapshot(scheduled, reactions, zaebal)


async def _apply_settings(session: AsyncSession, settings: dict[str, Any]) -> None:
    """Записывает три блока настроек. Используется и для overrides (старт паузы),
    и для restore (снятие паузы). После записи вызывающий должен дёрнуть
    scheduler.reload_dynamic_jobs(bot), чтобы крон-задачи пересобрались."""
    sched = settings.get("scheduled") or {}
    react = settings.get("reactions") or {}
    zaebal = settings.get("zaebal") or {}
    if sched:
        await set_scheduled_settings(session, sched)
    if react:
        await set_bot_reactions_settings(
            session,
            mention_enabled=react.get("mention_enabled"),
            reply_all_enabled=react.get("reply_all_enabled"),
            reply_except_phrases_enabled=react.get("reply_except_phrases_enabled"),
        )
    if zaebal:
        await set_zaebal_settings(session, zaebal)


async def _reload_jobs_safe() -> None:
    """Пересобрать динамические job'ы. Изолируем импорт, чтобы tests без
    bot/scheduler могли импортировать этот модуль (юнит-тесты на чистую
    логику snapshot/restore не должны тянуть Telegram-стек)."""
    try:
        from app.bot.dispatcher import get_bot
        from app.bot.scheduler import reload_dynamic_jobs

        await reload_dynamic_jobs(get_bot())
    except Exception as exc:  # noqa: BLE001
        log.warning("bot_pause.reload_jobs_failed", error=str(exc))


async def _announce_welcome_back_safe(hours: int) -> None:
    """P2.2: «злобное приветствие» в группу при авто-разморозке zaebal-паузы.
    Изолируем импорт Telegram-стека (как в `_reload_jobs_safe`), чтобы
    юнит-тесты на чистую логику не тянули bot/dispatcher. Любая ошибка/
    отсутствие group_chat_id — тихо логируется, restore уже закоммичен."""
    try:
        from app.bot.dispatcher import get_bot
        from app.config import get_settings
        from app.services.zaebal import _welcome_back_phrase

        settings = get_settings()
        if not settings.group_chat_id:
            return
        text = (
            f"<i>{_welcome_back_phrase()}</i>\n\n"
            f"▶️ Меня не было {hours} ч."
        )
        await get_bot().send_message(
            settings.group_chat_id, text, parse_mode="HTML"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("bot_pause.welcome_send_failed", error=str(exc))


async def start_pause(
    session: AsyncSession,
    *,
    duration_days: int | None,
    reason: str,
    started_by_tg_id: int | None,
) -> BotPause:
    """Стартует паузу. Если есть активная — кидаем ValueError."""
    if reason not in VALID_REASONS:
        raise ValueError(f"invalid_reason:{reason}")
    existing = await get_active_pause(session)
    if existing is not None:
        raise ValueError("already_paused")

    snapshot = await _snapshot_now(session)
    overrides = apply_pause_overrides(snapshot)

    now = datetime.now(timezone.utc)
    ends_at = (
        now + timedelta(days=duration_days)
        if duration_days is not None and duration_days > 0
        else None
    )
    pause = BotPause(
        started_at=now,
        ends_at=ends_at,
        ended_at=None,
        started_by_tg_id=started_by_tg_id,
        reason=reason,
        settings_snapshot=snapshot,
    )
    session.add(pause)
    await session.flush()

    await _apply_settings(session, overrides)
    await session.commit()
    await _reload_jobs_safe()
    log.info(
        "bot_pause.started",
        id=pause.id,
        reason=reason,
        ends_at=ends_at.isoformat() if ends_at else None,
        by=started_by_tg_id,
    )
    return pause


async def stop_pause(
    session: AsyncSession,
    *,
    automatic: bool = False,
    announce: bool = False,
) -> BotPause | None:
    """Снимает активную паузу — restore из snapshot. Возвращает строку
    или None, если паузы не было.

    `announce=True` (передаётся только из `maybe_auto_restore`) разрешает
    анонс возвращения в группу — но фактически шлём лишь для chat-инициированных
    пауз (см. `should_announce_restore`). Ручное снятие (админка / `/zaebal_undo`)
    оставляет `announce=False` → silent."""
    pause = await get_active_pause(session)
    if pause is None:
        return None
    ended_at = datetime.now(timezone.utc)
    pause.ended_at = ended_at
    await session.flush()

    # Снимаем поля до commit — после него объект может стать expired.
    reason = pause.reason
    started_at = pause.started_at

    snapshot = pause.settings_snapshot or {}
    await _apply_settings(session, snapshot)
    await session.commit()
    await _reload_jobs_safe()
    log.info(
        "bot_pause.stopped",
        id=pause.id,
        automatic=automatic,
        reason=reason,
    )
    if should_announce_restore(reason, announce):
        await _announce_welcome_back_safe(
            _format_absence_hours(started_at, ended_at)
        )
    return pause


async def maybe_auto_restore(session: AsyncSession) -> bool:
    """Если активная пауза истекла — снять. Возвращает True если снято."""
    pause = await get_active_pause(session)
    if pause is None or pause.ends_at is None:
        return False
    if pause.ends_at > datetime.now(timezone.utc):
        return False
    await stop_pause(session, automatic=True, announce=True)
    return True
