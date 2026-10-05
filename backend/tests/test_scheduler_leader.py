"""GHG11(5): тесты single-writer лиза планировщика (H1).

Проверяем:
* чистую функцию решения (кто вправе взять лиз);
* реальный цикл на in-memory SQLite: забор, продление, отказ второму, перехват
  после истечения TTL (failover) и мгновенную передачу после graceful release.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import AdminConfig
from app.services import scheduler_leader as sl


# --- чистая логика -----------------------------------------------------------


def test_lease_is_free_decisions():
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    assert sl.lease_is_free(None, None, "me", now, 300) is True
    # продление собственного лиза — всегда можно
    assert sl.lease_is_free("me", now - timedelta(seconds=99_999), "me", now, 300) is True
    # свежий чужой лиз — нельзя
    assert sl.lease_is_free("other", now - timedelta(seconds=10), "me", now, 300) is False
    # просроченный чужой лиз — можно (лидер умер)
    assert sl.lease_is_free("other", now - timedelta(seconds=400), "me", now, 300) is True


def test_encode_decode_roundtrip_and_corrupt():
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    owner, at = sl.decode(sl.encode("host:1", now))
    assert owner == "host:1"
    assert at == now
    # кривое значение не роняет — считаем лиз свободным
    assert sl.decode("not json") == (None, None)
    assert sl.decode(None) == (None, None)


# --- DB-цикл на SQLite -------------------------------------------------------


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(AdminConfig.__table__.create)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield sm
    finally:
        await engine.dispose()


async def test_acquire_then_other_is_refused(session_factory):
    sm = session_factory
    async with sm() as s1:
        assert await sl.acquire_or_renew(s1, "hostA:1", ttl_seconds=300) is True
    async with sm() as s2:
        # свежий лиз А → Б не лидер
        assert await sl.acquire_or_renew(s2, "hostB:2", ttl_seconds=300) is False
    # А продлевает своё лидерство
    async with sm() as s1:
        assert await sl.acquire_or_renew(s1, "hostA:1", ttl_seconds=300) is True


async def test_failover_after_ttl_expiry(session_factory):
    sm = session_factory
    async with sm() as s1:
        assert await sl.acquire_or_renew(s1, "hostA:1", ttl_seconds=300) is True
    # Состариваем лиз А за пределами TTL (имитация умершего лидера)
    async with sm() as s:
        row = await s.get(AdminConfig, sl.LEASE_KEY)
        assert row is not None
        stale = datetime.now(timezone.utc) - timedelta(seconds=400)
        row.value = sl.encode("hostA:1", stale)
        await s.commit()
    async with sm() as s2:
        assert await sl.acquire_or_renew(s2, "hostB:2", ttl_seconds=300) is True
    # Проигравший А больше не лидер — его продление отбито
    async with sm() as s1:
        assert await sl.acquire_or_renew(s1, "hostA:1", ttl_seconds=300) is False


async def test_release_frees_lease_immediately(session_factory):
    sm = session_factory
    async with sm() as s1:
        assert await sl.acquire_or_renew(s1, "hostA:1", ttl_seconds=300) is True
        await sl.release(s1, "hostA:1")
    async with sm() as s2:
        assert await sl.acquire_or_renew(s2, "hostB:2", ttl_seconds=300) is True


# --- гейт в самом планировщике ----------------------------------------------


def test_scheduler_gate_blocks_non_leader(monkeypatch):
    """При включённом гейте не-лидер НЕ регистрирует job'ы (single-writer)."""
    from app.bot import scheduler as sched

    import types

    monkeypatch.setattr(sched, "_scheduler", None)
    monkeypatch.setattr(sched, "_LEADER_GATE_ENABLED", True)
    monkeypatch.setattr(sched, "_is_leader", False)
    monkeypatch.setattr(sched, "SCHEDULER_LEADER_DISABLED", False)
    # Тест не поднимает окружение приложения — подсовываем лёгкие настройки.
    monkeypatch.setattr(
        sched,
        "get_settings",
        lambda: types.SimpleNamespace(scheduler_tz="Europe/Moscow", chukhan_cron=""),
    )
    assert sched._leadership_ok() is False

    class _Bot:  # планировщик к боту не обращается до старта
        pass

    s = sched.start_scheduler(_Bot())  # type: ignore[arg-type]
    assert s.running is False
    assert s.get_jobs() == []
    assert sched.is_leader() is False


def test_scheduler_gate_allows_leader(monkeypatch):
    from app.bot import scheduler as sched

    monkeypatch.setattr(sched, "_LEADER_GATE_ENABLED", True)
    monkeypatch.setattr(sched, "_is_leader", True)
    monkeypatch.setattr(sched, "SCHEDULER_LEADER_DISABLED", False)
    assert sched._leadership_ok() is True
    assert sched.is_leader() is True


def test_scheduler_gate_disabled_returns_old_behavior(monkeypatch):
    from app.bot import scheduler as sched

    monkeypatch.setattr(sched, "_LEADER_GATE_ENABLED", True)
    monkeypatch.setattr(sched, "_is_leader", False)
    monkeypatch.setattr(sched, "SCHEDULER_LEADER_DISABLED", True)
    # kill-switch: старое поведение «каждый сам себе планировщик»
    assert sched._leadership_ok() is True


async def test_release_by_non_owner_is_noop(session_factory):
    sm = session_factory
    async with sm() as s1:
        assert await sl.acquire_or_renew(s1, "hostA:1", ttl_seconds=300) is True
    async with sm() as s2:
        await sl.release(s2, "hostB:2")  # чужой релиз не снимает лиз
    async with sm() as s1:
        assert await sl.acquire_or_renew(s1, "hostA:1", ttl_seconds=300) is True
