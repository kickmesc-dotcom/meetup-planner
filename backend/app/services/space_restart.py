"""GHG8 P14: рестарт HF Space из админки + по расписанию.

Вариант A (P14-INV, подтверждён живым тестом 2026-06-07): POST
`https://huggingface.co/api/spaces/{SPACE_ID}/restart` с Bearer hf-токеном
(write) → HF пересоздаёт контейнер. Даунтайм HTTP/Mini App ≈ 0 (трафик
переключается бесшовно), но исходящие к TG деградированы ~7 мин после
подъёма (webhook переустанавливается retry-логикой) — отсюда анти-луп
«не чаще раза в 30 мин».

Env (DEPLOY_NOTES):
- `HF_TOKEN` — write-токен HF (новый секрет Space). Без него рестарт
  недоступен (эндпоинт отвечает 503, кнопка в админке дизейблится).
- `SPACE_ID` — HF проставляет сам внутри Space (`fryesw/meetup-planner-backend`);
  фолбэк захардкожен на прод-Space.

Хранение — admin_config, БЕЗ миграции (паттерн dead_chat):
- `space_restart.schedule` — JSON `{"mode": "off"|"once"|"interval",
  "at": ISO (для once), "every_hours": N (для interval)}`;
- `space_restart.last_restart_at` — ISO-якорь последнего ЗАПРОШЕННОГО
  рестарта (manual и scheduled). Нужен interval-режиму, чтобы рестарт не
  сдвигался от каждого подъёма Space, и 30-мин анти-лупу.

Порядок при once: режим сбрасывается в off (+commit) ДО вызова HF API —
иначе упавший между restart и сбросом процесс зациклил бы рестарты.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import aiohttp
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.admin_config import _get_value, _set_value

log = structlog.get_logger()

SCHEDULE_KEY = "space_restart.schedule"
LAST_RESTART_AT_KEY = "space_restart.last_restart_at"

_DEFAULT_SPACE_ID = "fryesw/meetup-planner-backend"
_HF_API_TIMEOUT = 20.0  # huggingface.co, не telegram — РКН-throttling не задевает

# P14.3: анти-луп. Первые ~7 мин после рестарта исходящие к TG деградированы
# (P14-INV), поэтому scheduled-рестарт чаще раза в 30 мин — самоубийство.
MIN_RESTART_INTERVAL = timedelta(minutes=30)
# Кламп interval-режима: ≥1ч (>30 мин анти-лупа), ≤30 суток.
EVERY_HOURS_MIN = 1
EVERY_HOURS_MAX = 720

_MODES = ("off", "once", "interval")


# --- Чистые функции (юнит-тестируемые без БД) ---

def parse_schedule(raw: str | None) -> dict:
    """JSON из admin_config → нормализованный dict с клампами.

    Невалидный JSON/режим → off (fail-safe: лучше не рестартовать, чем
    рестартовать по мусору). every_hours клампится в [1, 720]; once без
    валидного `at` тоже деградирует в off.
    """
    off = {"mode": "off", "at": None, "every_hours": None}
    if raw is None:
        return off
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return off
    if not isinstance(data, dict):
        return off
    mode = data.get("mode")
    if mode not in _MODES:
        return off
    if mode == "once":
        at = _parse_iso(data.get("at"))
        if at is None:
            return off
        return {"mode": "once", "at": at.isoformat(), "every_hours": None}
    if mode == "interval":
        try:
            hours = int(data.get("every_hours"))
        except (ValueError, TypeError):
            return off
        hours = max(EVERY_HOURS_MIN, min(EVERY_HOURS_MAX, hours))
        return {"mode": "interval", "at": None, "every_hours": hours}
    return off


def _parse_iso(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_next_restart(
    schedule: dict, last_restart_at: datetime | None, now: datetime
) -> datetime | None:
    """Когда следующий плановый рестарт (для UI «следующий рестарт: …»).

    off → None. once → at (даже если в прошлом — job подберёт на ближайшем
    тике). interval без якоря → прямо сейчас (первый рестарт при включении);
    с якорем → anchor + every_hours.
    """
    mode = schedule["mode"]
    if mode == "off":
        return None
    if mode == "once":
        return _parse_iso(schedule["at"])
    # interval
    if last_restart_at is None:
        return now
    return last_restart_at + timedelta(hours=schedule["every_hours"])


def should_fire(
    schedule: dict, last_restart_at: datetime | None, now: datetime
) -> bool:
    """Пора ли scheduled-рестартовать на этом тике.

    Анти-луп: < MIN_RESTART_INTERVAL от последнего запрошенного рестарта
    (включая ручной) — молчим, even если расписание говорит «пора».
    """
    nxt = compute_next_restart(schedule, last_restart_at, now)
    if nxt is None or nxt > now:
        return False
    if (
        last_restart_at is not None
        and now - last_restart_at < MIN_RESTART_INTERVAL
    ):
        return False
    return True


# --- get/set admin_config ---

async def get_schedule(session: AsyncSession) -> dict:
    return parse_schedule(await _get_value(session, SCHEDULE_KEY))


async def set_schedule(session: AsyncSession, schedule: dict) -> dict:
    """Нормализует через parse_schedule (кламп every_hours — P14.3) и пишет."""
    normalized = parse_schedule(json.dumps(schedule))
    await _set_value(session, SCHEDULE_KEY, json.dumps(normalized))
    return normalized


async def get_last_restart_at(session: AsyncSession) -> datetime | None:
    return _parse_iso(await _get_value(session, LAST_RESTART_AT_KEY))


async def set_last_restart_at(session: AsyncSession, at: datetime) -> None:
    await _set_value(session, LAST_RESTART_AT_KEY, at.isoformat())


# --- HF Hub API ---

def hf_token_configured() -> bool:
    return bool(os.getenv("HF_TOKEN"))


def _space_id() -> str:
    # SPACE_ID HF проставляет в контейнер сам; фолбэк — прод-Space.
    return os.getenv("SPACE_ID") or _DEFAULT_SPACE_ID


async def trigger_hf_restart(source: str) -> bool:
    """POST restart в HF Hub API. True = HF принял (HTTP 2xx).

    Любой фейл — warning + False, без raise: вызывающие (endpoint в
    background-таске, scheduler-job) ретраить не должны — админ увидит
    лог/UI и нажмёт ещё раз.
    """
    token = os.getenv("HF_TOKEN")
    if not token:
        log.warning("space_restart.no_hf_token", source=source)
        return False
    url = f"https://huggingface.co/api/spaces/{_space_id()}/restart"
    try:
        async with aiohttp.ClientSession(trust_env=False) as http:
            async with http.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=_HF_API_TIMEOUT),
            ) as resp:
                body = (await resp.text())[:200]
                if 200 <= resp.status < 300:
                    log.info(
                        "space_restart.accepted", source=source, status=resp.status
                    )
                    return True
                log.warning(
                    "space_restart.rejected",
                    source=source,
                    status=resp.status,
                    body=body,
                )
                return False
    except Exception as exc:  # noqa: BLE001 — сеть/timeout, не критично
        log.warning("space_restart.failed", source=source, error=str(exc))
        return False


# --- scheduler job (тик раз в 5 мин, паттерн bot_pause_auto_restore) ---

async def run_space_restart_tick() -> None:
    """Проверить расписание; если пора — рестарт.

    Дёшево для Neon: 2 point-SELECT по admin_config на тик. Сброс once → off
    коммитится ДО вызова HF API (анти-рестарт-луп). last_restart_at пишется
    тоже до вызова: даже если API-вызов упадёт, 30-мин guard не даст
    долбить HF каждые 5 минут.
    """
    from app.db.base import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as session:
        schedule = await get_schedule(session)
        if schedule["mode"] == "off":
            return
        now = datetime.now(timezone.utc)
        last = await get_last_restart_at(session)
        if not should_fire(schedule, last, now):
            return
        if schedule["mode"] == "once":
            await set_schedule(session, {"mode": "off"})
        await set_last_restart_at(session, now)
        log.info(
            "space_restart.scheduled_fired",
            mode=schedule["mode"],
            every_hours=schedule["every_hours"],
        )
    # Сессия закрыта, конфиг закоммичен — теперь можно дёргать HF.
    await trigger_hf_restart(source="scheduled")
