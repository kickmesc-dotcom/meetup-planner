"""Проверка TLS-сертификата базы и `/readyz` (S-4, S-5).

Что здесь важнее всего: разница между «сертификат невалиден» и «база недоступна».
Первое — повод осознанно работать без проверки (и сказать об этом в логе),
второе — нет: снимать защиту из-за сетевого блипа нельзя.
"""

from __future__ import annotations

import os
import ssl

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://semitaskbot.pages.dev")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.test_ssl.db")

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app.db import base as db_base  # noqa: E402
from app import main as app_main  # noqa: E402


# --- режимы -----------------------------------------------------------------


def test_default_is_verification_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DB_SSL_VERIFY", raising=False)
    assert db_base.ssl_verify_requested() is True


def test_explicit_modes(monkeypatch: pytest.MonkeyPatch):
    for value in ("require", "on", "true", "yes", "1"):
        monkeypatch.setenv("DB_SSL_VERIFY", value)
        assert db_base.ssl_verify_requested() is True, value
    for value in ("off", "disable", "false", "no", "0"):
        monkeypatch.setenv("DB_SSL_VERIFY", value)
        assert db_base.ssl_verify_requested() is False, value


def test_context_verifies_by_default_and_relaxes_only_on_demand(monkeypatch: pytest.MonkeyPatch):
    verified = db_base._ssl_context(True)
    assert verified.verify_mode == ssl.CERT_REQUIRED
    assert verified.check_hostname is True

    relaxed = db_base._ssl_context(False)
    assert relaxed.verify_mode == ssl.CERT_NONE
    assert relaxed.check_hostname is False


def test_engine_is_recreated_when_mode_changes(monkeypatch: pytest.MonkeyPatch):
    """Живому пулу SSL-контекст не поменять — движок обязан пересоздаться."""
    db_base.set_ssl_verify(True)
    engine = db_base.get_engine()
    assert db_base.get_engine() is engine
    db_base.set_ssl_verify(False)
    try:
        assert db_base.get_engine() is not engine
    finally:
        db_base.set_ssl_verify(True)
        db_base.get_engine().sync_engine.dispose()


# --- распознавание ошибки сертификата --------------------------------------


def test_certificate_errors_are_recognised():
    exc = ssl.SSLCertVerificationError("certificate verify failed: self-signed certificate")
    assert db_base._is_cert_error(exc) is True
    # Обёрнутая ошибка (asyncpg/OSError поверх SSL) тоже видна.
    wrapped = ConnectionError("connect failed")
    wrapped.__cause__ = exc
    assert db_base._is_cert_error(wrapped) is True


def test_other_failures_are_not_treated_as_certificate_problems():
    """Иначе таймаут до базы молча снял бы защиту."""
    assert db_base._is_cert_error(TimeoutError("timed out")) is False
    assert db_base._is_cert_error(OSError("connection refused")) is False
    assert db_base._is_cert_error(Exception("password authentication failed")) is False


def test_cert_error_detection_does_not_loop_on_cycles():
    exc = Exception("boom")
    exc.__context__ = exc
    assert db_base._is_cert_error(exc) is False


# --- /readyz ----------------------------------------------------------------


def _client() -> TestClient:
    # Как и в тестах CORS: без lifespan, чтобы не гонять сидинг и Telegram.
    return TestClient(app_main.create_app(), raise_server_exceptions=False)


def test_healthz_stays_cheap_liveness():
    res = _client().get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_readyz_reports_degraded_when_db_is_down(monkeypatch: pytest.MonkeyPatch):
    async def boom() -> None:
        raise OSError("connection refused")

    monkeypatch.setattr(app_main, "_db_ping", boom)
    res = _client().get("/readyz")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"
    # Причина — тип ошибки, без строки подключения и пароля.
    assert body["reason"] == "OSError"


def test_readyz_reports_timeout_separately(monkeypatch: pytest.MonkeyPatch):
    import asyncio

    async def slow() -> None:
        await asyncio.sleep(30)

    monkeypatch.setattr(app_main, "_db_ping", slow)
    monkeypatch.setattr(app_main, "READY_DB_TIMEOUT_SECONDS", 0.05)
    res = _client().get("/readyz")
    assert res.status_code == 503
    assert res.json()["db"] == "timeout"


def test_readyz_says_ok_when_db_answers(monkeypatch: pytest.MonkeyPatch):
    called = {"n": 0}

    async def ok() -> None:
        called["n"] += 1

    monkeypatch.setattr(app_main, "_db_ping", ok)
    res = _client().get("/readyz")
    assert res.status_code == 200
    assert res.json()["db"] == "ok"
    assert called["n"] == 1
