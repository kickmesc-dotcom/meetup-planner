"""RUM: приём метрик фронта и сводка p75/p95 по устройствам.

Проверяем то, что важно для решения «где тормозит»: агрегация по устройству,
доля «хороших» по порогу Core Web Vitals и то, что старые события не держат
картину вечно. Отдельно — закрытый список имён: чужая метрика не должна
портить p75.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_telemetry
from app.services import rum


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(routes_telemetry.router, prefix="/api")
    return TestClient(app)


def setup_function() -> None:
    rum.rum.reset()


def test_p75_and_good_share_by_device() -> None:
    now = datetime.now(UTC)
    for value in (1000.0, 2000.0, 3000.0, 4000.0):
        rum.rum.record(
            name="LCP", value=value, device="mobile", path="/app", build="abc", now=now
        )
    rum.rum.record(
        name="LCP", value=900.0, device="desktop", path="/app", build="abc", now=now
    )

    snapshot = rum.rum.snapshot(now=now)

    assert snapshot["metrics"]["LCP"]["mobile"]["count"] == 4
    # p75 по ближайшему рангу: третье из четырёх значений.
    assert snapshot["metrics"]["LCP"]["mobile"]["p75"] == 3000.0
    # Порог «хорошо» для LCP — 2500 мс: под него попали 1000 и 2000.
    assert snapshot["metrics"]["LCP"]["mobile"]["good_share"] == 0.5
    assert snapshot["metrics"]["LCP"]["desktop"]["p75"] == 900.0


def test_old_events_leave_the_window() -> None:
    now = datetime.now(UTC)
    rum.rum.record(
        name="INP",
        value=50.0,
        device="mobile",
        now=now - timedelta(days=2),
    )
    rum.rum.record(name="INP", value=300.0, device="mobile", now=now)

    snapshot = rum.rum.snapshot(now=now)

    assert snapshot["metrics"]["INP"]["mobile"]["count"] == 1
    assert snapshot["metrics"]["INP"]["mobile"]["p75"] == 300.0


def test_endpoint_accepts_vitals() -> None:
    response = _client().post(
        "/api/telemetry/vitals",
        json={
            "name": "LCP",
            "value": 2100.5,
            "rating": "good",
            "device": "mobile",
            "platform": "android",
            "path": "/app?access=SECRET",
            "build": "520ab56e",
        },
    )
    assert response.status_code == 204
    assert response.content == b""

    snapshot = rum.rum.snapshot()
    assert snapshot["metrics"]["LCP"]["mobile"]["count"] == 1
    # Подпись доступа не должна попасть даже в топ путей.
    assert all("SECRET" not in item["path"] for item in snapshot["top_paths"])


def test_endpoint_rejects_unknown_metric_and_absurd_value() -> None:
    client = _client()
    assert client.post("/api/telemetry/vitals", json={"name": "XYZ", "value": 1}).status_code == 422
    assert client.post("/api/telemetry/vitals", json={"name": "LCP", "value": -1}).status_code == 422
    assert (
        client.post("/api/telemetry/vitals", json={"name": "LCP", "value": 600_001}).status_code
        == 422
    )
