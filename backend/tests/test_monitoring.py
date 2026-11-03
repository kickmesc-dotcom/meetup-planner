"""Мониторинг: окно, проценты, алерты (B2B_PLATFORM_PLAN, 5.2).

Проверяем правило, а не окружение: метрики живут в памяти процесса, поэтому
каждый тест создаёт свой `Metrics` и передаёт `now` явно — без `sleep`.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://semitaskbot.pages.dev")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.test_monitoring.db")

from app.services.monitoring import (  # noqa: E402
    ALERT_COOLDOWN_SEC,
    MIN_REQUESTS_FOR_ALERT,
    WINDOW_SEC,
    Metrics,
)


def _fill(
    metrics: Metrics,
    *,
    total: int = 100,
    errors: int = 0,
    status: int = 200,
    duration_ms: float = 50.0,
    now: float = 1000.0,
    path: str = "/api/hr/employees/{id}",
) -> None:
    for index in range(total):
        code = 500 if index < errors else status
        metrics.record("GET", path, code, duration_ms, now=now)


def test_empty_window_is_all_zeros_not_a_crash():
    snapshot = Metrics().snapshot(now=1000.0)
    assert snapshot.requests == 0
    assert snapshot.errors == 0
    assert snapshot.error_rate == 0.0
    assert snapshot.p50_ms == 0.0
    assert snapshot.p95_ms == 0.0
    assert snapshot.last_error is None
    assert snapshot.alert is None


def test_counts_and_error_rate():
    metrics = Metrics()
    _fill(metrics, total=100, errors=10)
    snapshot = metrics.snapshot(now=1000.0)
    assert snapshot.requests == 100
    assert snapshot.errors == 10
    assert snapshot.error_rate == 0.1


def test_client_errors_are_not_server_errors():
    """401/404 — это не падение: иначе чужой сканер «ронял» бы весь сервис."""
    metrics = Metrics()
    _fill(metrics, total=100, status=404)
    snapshot = metrics.snapshot(now=1000.0)
    assert snapshot.errors == 0
    assert snapshot.alert is None


def test_percentiles_use_observed_values():
    metrics = Metrics()
    for duration in (10.0, 20.0, 30.0, 40.0):
        metrics.record("GET", "/healthz", 200, duration, now=1000.0)
    snapshot = metrics.snapshot(now=1000.0)
    assert snapshot.p50_ms == 20.0
    # p95 на четырёх значениях — максимум, а не «среднее с потолком».
    assert snapshot.p95_ms == 40.0
    assert snapshot.slowest_ms == 40.0


def test_old_events_fall_out_of_the_window():
    metrics = Metrics()
    _fill(metrics, total=10, now=1000.0)
    later = 1000.0 + WINDOW_SEC + 1
    assert metrics.snapshot(now=later).requests == 0


def test_alert_needs_both_share_and_volume():
    """Один запрос из трёх — это 33%, но не падение: объёма нет."""
    small = Metrics()
    _fill(small, total=MIN_REQUESTS_FOR_ALERT - 1, errors=MIN_REQUESTS_FOR_ALERT - 1)
    assert small.snapshot(now=1000.0).alert is None

    big = Metrics()
    _fill(big, total=100, errors=5)
    assert big.snapshot(now=1000.0).alert == "errors"


def test_slow_api_raises_latency_alert():
    metrics = Metrics()
    _fill(metrics, total=100, duration_ms=2500.0)
    assert metrics.snapshot(now=1000.0).alert == "latency"


def test_alert_is_sent_once_per_cooldown():
    metrics = Metrics()
    _fill(metrics, total=100, errors=10, now=2000.0)
    assert metrics.take_alert(now=2000.0) == "errors"
    assert metrics.take_alert(now=2060.0) is None
    # Кулдаун истёк, но окно скользит: без свежих событий алерта нет — «тишина
    # в API» это не падение, а отсутствие трафика.
    later = 2000.0 + ALERT_COOLDOWN_SEC + 60
    assert metrics.take_alert(now=later) is None
    _fill(metrics, total=100, errors=10, now=later)
    assert metrics.take_alert(now=later) == "errors"


def test_snapshot_does_not_consume_the_alert():
    """Экран админки опрашивает сводку часто — это не должно глушить алерт."""
    metrics = Metrics()
    _fill(metrics, total=100, errors=10)
    for _ in range(5):
        assert metrics.snapshot(now=1000.0).alert == "errors"
    assert metrics.take_alert(now=1000.0) == "errors"


def test_alert_text_has_numbers_and_place_to_look():
    metrics = Metrics()
    _fill(metrics, total=100, errors=10)
    metrics.take_alert(now=1000.0)
    text = metrics.alert_text("errors", now=1000.0)
    assert "10" in text and "100" in text
    assert "/api/hr/employees/{id}" in text
    assert "Платформа" in text


def test_last_error_keeps_the_most_recent_one():
    metrics = Metrics()
    _fill(metrics, total=10, errors=3, now=1000.0)
    last = metrics.snapshot(now=1000.0).last_error
    assert last is not None
    assert last["status"] == 500
    assert last["method"] == "GET"


def test_middleware_records_real_request_with_route_template():
    """Сквозная проверка: middleware пишет шаблон маршрута, а не сырой путь."""
    from starlette.testclient import TestClient

    from app.main import create_app
    from app.services import monitoring

    monitoring.reset()
    try:
        client = TestClient(create_app(), raise_server_exceptions=False)
        client.get("/healthz")
        snapshot = monitoring.snapshot()
        assert snapshot.requests >= 1
        assert any(item["path"] == "/healthz" for item in snapshot.top_paths)
    finally:
        monitoring.reset()


def test_platform_monitoring_route_is_registered():
    from app.main import create_app

    # `app.routes` в этом проекте содержит `_IncludedRouter` без путей, поэтому
    # смотрим схему: в ней пути уже с префиксом `/api`.
    assert "/api/platform/monitoring" in create_app().openapi()["paths"]
