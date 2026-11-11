"""`POST /api/telemetry`: приём отчёта об ошибке фронта.

Проверяем три вещи, которые важнее формата: ручка работает без авторизации
(ошибка бывает до входа), путь чистится от query — иначе подпись доступа
попадёт в логи, и слишком длинный отчёт отклоняется, а не занимает память.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import guards, routes_telemetry


def test_telemetry_is_rate_limited() -> None:
    """Публичная ручка телеметрии должна попадать под правило лимита (S-3)."""
    rules = [rule for rule in guards.default_rules() if rule.name == "telemetry"]
    assert rules, "у телеметрии нет правила лимита"
    rule = rules[0]
    assert rule.matches("POST", "/api/telemetry")
    assert rule.matches("POST", "/api/telemetry/vitals")
    assert rule.matches("POST", "/api/telemetry/csp")
    assert not rule.matches("POST", "/api/telemetryx")


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(routes_telemetry.router, prefix="/api")
    return TestClient(app)


def test_csp_report_is_accepted_and_clipped() -> None:
    # Формат report-uri: вложенный объект. Путь документа приходит с query —
    # в лог он попасть не должен, поэтому проверяем очистку функцией, а не
    # доверяем браузеру.
    response = _client().post(
        "/api/telemetry/csp",
        content='{"csp-report": {"violated-directive": "script-src", '
        '"blocked-uri": "https://evil.test/x.js", '
        '"document-uri": "https://semitaskbot.pages.dev/?access=SECRET"}}',
        headers={"Content-Type": "application/csp-report"},
    )
    assert response.status_code == 204
    assert response.content == b""
    assert routes_telemetry.clean_path(
        "https://semitaskbot.pages.dev/?access=SECRET"
    ) == "https://semitaskbot.pages.dev/"


def test_csp_report_garbage_does_not_error() -> None:
    assert _client().post("/api/telemetry/csp", content=b"not json").status_code == 204


def test_accepts_report_without_auth() -> None:
    response = _client().post(
        "/api/telemetry",
        json={
            "kind": "render",
            "message": "Cannot read properties of undefined",
            "stack": "at Screen (index-abc.js:1:2)",
            "path": "/app",
            "build": "520ab56e",
            "count": 2,
        },
    )
    assert response.status_code == 204
    assert response.content == b""


def test_path_loses_query_and_fragment() -> None:
    # Фронт чистит адрес сам, но старый/сломанный клиент может прислать как есть.
    assert routes_telemetry.clean_path("/app?access=SECRET#x") == "/app"
    assert routes_telemetry.clean_path("/app") == "/app"
    assert len(routes_telemetry.clean_path("/" + "a" * 500)) == 200


def test_oversized_report_is_rejected() -> None:
    response = _client().post(
        "/api/telemetry", json={"message": "x" * 5000}
    )
    assert response.status_code == 422


def test_unknown_kind_and_bad_count_are_rejected() -> None:
    client = _client()
    assert client.post("/api/telemetry", json={"kind": "crash"}).status_code == 422
    assert client.post("/api/telemetry", json={"count": 0}).status_code == 422
    assert client.post("/api/telemetry", json={"count": 101}).status_code == 422


def test_empty_body_is_rejected() -> None:
    # Совсем пустой запрос — это не отчёт, а шум: 422 честнее, чем 204.
    assert _client().post("/api/telemetry", json={}).status_code == 422
