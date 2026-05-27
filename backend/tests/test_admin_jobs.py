"""GHG6 M2/M3: ручное управление scheduler-jobs через админку.

Тестируем чистую логику ручек `/admin/jobs/{id}/reschedule` и
`DELETE /admin/jobs/{id}` через mock APScheduler — без поднятия FastAPI и
БД (паттерн test_polls_quorum / test_loser_cooldown_split).

Покрываем:
- `_classify_trigger` — корректно распознаёт Interval/Cron/Date.
- reschedule editable interval-job → `modify_job(next_run_time=run_at)`.
- reschedule НЕ editable (proxy_health) → HTTPException 400.
- reschedule unknown job → 404.
- cancel one-shot (date) → `remove_job`.
- cancel recurring (interval) → `modify_job` к get_next_fire_time(now+1s).
- cancel НЕ editable → 400.

Reminder-кейсы (`reminder:<id>`) требуют живой DB-сессии — пропускаем
(они интегрируются с MeetingReminder.sent_at и тестируются по живой схеме
вручную; их логика не менялась с GHG5).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import HTTPException

from app.api.routes_admin import (
    JobRescheduleIn,
    _classify_trigger,
    cancel_job,
    reschedule_job,
)


# --- _classify_trigger ------------------------------------------------------


def test_classify_interval() -> None:
    assert _classify_trigger(IntervalTrigger(minutes=5)) == "interval"


def test_classify_cron() -> None:
    assert _classify_trigger(CronTrigger(hour=9, minute=37)) == "cron"


def test_classify_date() -> None:
    when = datetime.now(timezone.utc) + timedelta(minutes=1)
    assert _classify_trigger(DateTrigger(run_date=when)) == "date"


def test_classify_unknown() -> None:
    class _Fake:
        pass

    assert _classify_trigger(_Fake()) == "unknown"


# --- общая инфраструктура для асинхронных handler'ов -------------------------


class _AdminUser:
    """Минимальный stub под `_ensure_admin`."""

    id = 999
    telegram_id = 12345  # должен быть в admin_tg_id_set; патчим через _ensure_admin


def _patch_admin_check():
    """Patch settings.admin_tg_id_set, чтобы наш fake-user был админом."""
    fake_settings = MagicMock()
    fake_settings.admin_tg_id_set = {_AdminUser.telegram_id}
    return patch("app.api.routes_admin.get_settings", return_value=fake_settings)


class _FakeJob:
    def __init__(self, jid: str, trigger: Any, next_run: datetime | None) -> None:
        self.id = jid
        self.trigger = trigger
        self.next_run_time = next_run


class _FakeScheduler:
    """Минимальный stub APScheduler для тестов M.

    Хранит дикт job_id → _FakeJob, фиксирует все вызовы modify_job / remove_job
    для проверки в тестах.
    """

    def __init__(self, jobs: dict[str, _FakeJob]) -> None:
        self._jobs = jobs
        self.modify_calls: list[tuple[str, datetime]] = []
        self.remove_calls: list[str] = []

    def get_job(self, jid: str) -> _FakeJob | None:
        return self._jobs.get(jid)

    def get_jobs(self) -> list[_FakeJob]:
        return list(self._jobs.values())

    def modify_job(self, jid: str, *, next_run_time: datetime) -> None:
        if jid not in self._jobs:
            raise KeyError(jid)
        self._jobs[jid].next_run_time = next_run_time
        self.modify_calls.append((jid, next_run_time))

    def remove_job(self, jid: str) -> None:
        if jid in self._jobs:
            del self._jobs[jid]
        self.remove_calls.append(jid)


# --- reschedule -------------------------------------------------------------


async def test_reschedule_interval_job_calls_modify_job() -> None:
    trig = IntervalTrigger(minutes=5)
    sched = _FakeScheduler({"autoloser": _FakeJob("autoloser", trig, None)})
    run_at = datetime.now(timezone.utc) + timedelta(minutes=15)

    with (
        _patch_admin_check(),
        patch("app.api.routes_admin.get_scheduler", return_value=sched),
    ):
        out = await reschedule_job(
            job_id="autoloser",
            body=JobRescheduleIn(run_at=run_at),
            session=MagicMock(),
            user=_AdminUser(),
        )
    assert sched.modify_calls == [("autoloser", run_at)]
    assert out.id == "autoloser"
    assert out.trigger_kind == "interval"
    assert out.editable is True


async def test_reschedule_unknown_job_returns_404() -> None:
    sched = _FakeScheduler({})
    with (
        _patch_admin_check(),
        patch("app.api.routes_admin.get_scheduler", return_value=sched),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await reschedule_job(
                job_id="nonexistent",
                body=JobRescheduleIn(run_at=datetime.now(timezone.utc)),
                session=MagicMock(),
                user=_AdminUser(),
            )
    assert exc_info.value.status_code == 404


async def test_reschedule_non_editable_returns_400() -> None:
    """proxy_health помечен как НЕ editable — modify_job вообще не должен зваться."""
    sched = _FakeScheduler(
        {"proxy_health": _FakeJob("proxy_health", IntervalTrigger(seconds=30), None)}
    )
    with (
        _patch_admin_check(),
        patch("app.api.routes_admin.get_scheduler", return_value=sched),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await reschedule_job(
                job_id="proxy_health",
                body=JobRescheduleIn(run_at=datetime.now(timezone.utc)),
                session=MagicMock(),
                user=_AdminUser(),
            )
    assert exc_info.value.status_code == 400
    assert sched.modify_calls == []  # триггер не двигали


async def test_reschedule_naive_datetime_treated_as_utc() -> None:
    """Если фронт прислал naive datetime — считаем что это UTC, не падаем."""
    trig = IntervalTrigger(minutes=5)
    sched = _FakeScheduler({"autoloser": _FakeJob("autoloser", trig, None)})
    naive = datetime(2026, 6, 1, 12, 0, 0)  # без tzinfo

    with (
        _patch_admin_check(),
        patch("app.api.routes_admin.get_scheduler", return_value=sched),
    ):
        await reschedule_job(
            job_id="autoloser",
            body=JobRescheduleIn(run_at=naive),
            session=MagicMock(),
            user=_AdminUser(),
        )
    assert len(sched.modify_calls) == 1
    _, applied = sched.modify_calls[0]
    assert applied.tzinfo is not None
    assert applied.tzinfo == timezone.utc


# --- cancel -----------------------------------------------------------------


async def test_cancel_oneshot_date_job_removes_it() -> None:
    """DateTrigger — действительно удаляем job (он всё равно одноразовый)."""
    when = datetime.now(timezone.utc) + timedelta(minutes=10)
    sched = _FakeScheduler(
        {"autoloser": _FakeJob("autoloser", DateTrigger(run_date=when), when)}
    )

    with (
        _patch_admin_check(),
        patch("app.api.routes_admin.get_scheduler", return_value=sched),
    ):
        resp = await cancel_job(
            job_id="autoloser",
            session=MagicMock(),
            user=_AdminUser(),
        )
    assert resp.status_code == 204
    assert sched.remove_calls == ["autoloser"]
    assert sched.modify_calls == []


async def test_cancel_recurring_interval_skips_next() -> None:
    """IntervalTrigger — modify_job на следующий fire после now+1s, НЕ remove."""
    trig = IntervalTrigger(minutes=5)
    now = datetime.now(timezone.utc)
    sched = _FakeScheduler({"reminders_tick": _FakeJob("reminders_tick", trig, now)})

    with (
        _patch_admin_check(),
        patch("app.api.routes_admin.get_scheduler", return_value=sched),
    ):
        resp = await cancel_job(
            job_id="reminders_tick",
            session=MagicMock(),
            user=_AdminUser(),
        )
    assert resp.status_code == 204
    # remove не зван — job сохранён
    assert sched.remove_calls == []
    # modify_job зван ровно один раз, новое время в будущем (минимум через ~5мин)
    assert len(sched.modify_calls) == 1
    _, new_time = sched.modify_calls[0]
    assert new_time > now + timedelta(seconds=30)


async def test_cancel_recurring_cron_skips_next() -> None:
    """CronTrigger — то же поведение, modify_job на ближайший cron-fire."""
    trig = CronTrigger(hour="*", minute="*/10")  # каждые 10 минут
    now = datetime.now(timezone.utc)
    sched = _FakeScheduler({"chukhan_weekly": _FakeJob("chukhan_weekly", trig, now)})

    with (
        _patch_admin_check(),
        patch("app.api.routes_admin.get_scheduler", return_value=sched),
    ):
        resp = await cancel_job(
            job_id="chukhan_weekly",
            session=MagicMock(),
            user=_AdminUser(),
        )
    assert resp.status_code == 204
    assert sched.remove_calls == []
    assert len(sched.modify_calls) == 1


async def test_cancel_non_editable_returns_400() -> None:
    sched = _FakeScheduler(
        {"proxy_health": _FakeJob("proxy_health", IntervalTrigger(seconds=30), None)}
    )
    with (
        _patch_admin_check(),
        patch("app.api.routes_admin.get_scheduler", return_value=sched),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await cancel_job(
                job_id="proxy_health",
                session=MagicMock(),
                user=_AdminUser(),
            )
    assert exc_info.value.status_code == 400
    assert sched.remove_calls == []
    assert sched.modify_calls == []


async def test_cancel_unknown_returns_404() -> None:
    sched = _FakeScheduler({})
    with (
        _patch_admin_check(),
        patch("app.api.routes_admin.get_scheduler", return_value=sched),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await cancel_job(
                job_id="ghost",
                session=MagicMock(),
                user=_AdminUser(),
            )
    assert exc_info.value.status_code == 404
