"""Четвёртый пакет: гигиена ответов и логов (S-12, S-15, S-16, S-17).

Что проверяем и почему именно так:

* **S-15** (`server: uvicorn`) убирается флагом uvicorn, а не middleware, поэтому
  в тесте приложения этого не видно — проверяем сам `Dockerfile` (это
  «политический» тест: он ловит возврат флага назад). Живая проверка — `curl -D`
  по боевому контуру после выкладки.
* **S-12** публичный `/api/meta` не должен отдавать версию СУБД, порт и имя
  базы; они живут в `/api/meta/net` под секретом. Проверяем оба состояния —
  «чего нет» и «где есть».
* **S-16** `/api/meta/net` без секрета не существует (404), чтобы сетевое
  устройство контейнера не показывали никому.
* **S-17** логгер вырезает подписи из подписанных адресов, `Bearer`-токены,
  секрет вебхука в заголовке и пароль из DSN.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("MINI_APP_URL", "https://semitaskbot.pages.dev")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.test_pack4.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import structlog  # noqa: E402

from app.log_redaction import (  # noqa: E402
    REDACTED,
    configure_logging,
    log_processors,
    redact_event,
    scrub,
)

ROOT = Path(__file__).resolve().parents[1]


# --- S-15: заголовок сервера -------------------------------------------------


def test_dockerfile_starts_uvicorn_without_server_header():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    cmd = [line for line in dockerfile.splitlines() if line.startswith("CMD")]
    assert cmd, "в Dockerfile нет CMD"
    assert "--no-server-header" in cmd[-1], (
        "uvicorn снова отдаёт заголовок `server: uvicorn` — верни "
        "`--no-server-header` в CMD (S-15)"
    )


def test_dockerfile_migrations_still_go_through_lock_wrapper():
    """Страховка от отката второй правки: миграции только через `app.db.migrate`."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    cmd = [line for line in dockerfile.splitlines() if line.startswith("CMD")][-1]
    assert "python -m app.db.migrate" in cmd
    assert "alembic upgrade head" not in cmd


# --- S-12 / S-16: что отдаём публично ---------------------------------------


@pytest.fixture()
def client() -> TestClient:
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def test_public_meta_has_no_database_fingerprint(client: TestClient):
    """Версия СУБД, порт и имя базы — не для публичной ручки."""
    body = client.get("/api/meta").json()
    db = body["db"]
    assert "server_version" not in db, "версия СУБД снова утекает в /api/meta"
    assert "port" not in db
    assert "name" not in db


def test_public_meta_keeps_what_our_checks_need(client: TestClient):
    """Сверка хостов живёт на этих полях — их потеря тоже была бы поломкой."""
    body = client.get("/api/meta").json()
    assert body["status"] == "ok"
    code = body["code"]
    for key in ("routes", "api_routes", "fingerprint", "alembic_head"):
        assert key in code, f"в /api/meta пропало поле code.{key}"
    assert {"provider", "host"} <= set(body["db"])
    assert isinstance(body["features"], list)


def test_db_details_are_behind_the_diag_token(client: TestClient):
    """Без секрета ручки диагностики нет вообще (404), а не «есть, но пустая»."""
    assert client.get("/api/meta/net").status_code == 404


def test_diag_endpoint_rejects_wrong_secret(client: TestClient):
    # Значение ASCII: в HTTP-заголовке не-ASCII байты просто не отправляются, и
    # тест проверял бы клиент, а не нашу ручку.
    response = client.get("/api/meta/net", headers={"X-Diag-Token": "not-the-secret"})
    assert response.status_code == 404


def test_diag_endpoint_gives_db_details_with_the_right_secret(client: TestClient):
    """Убранное из `/api/meta` доступно с секретом — иначе оно просто потеряно."""
    from app.config import get_settings

    token = get_settings().tg_webhook_secret
    response = client.get("/api/meta/net", headers={"X-Diag-Token": token})
    assert response.status_code == 200
    report = response.json()
    assert {"port", "name", "server_version"} <= set(report["db"]), (
        "подробности о базе не найдены ни в публичной мете, ни в диагностике"
    )


# --- S-17: полоскание подписей ----------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "https://api.example/api/media/17?s=8f3a1c9d5e7b2a4c6d8e0f1a2b3c4d5e",
        "/api/media/tg/321?s=8f3a1c9d5e7b2a4c6d8e0f1a2b3c4d5e",
        "/api/meetings/ical/42.ics?t=1a2b3c4d5e6f7a8b",
        "https://host/cb?token=секрет-в-параметре&x=1",
        "https://host/path?signature=abcdef0123456789",
    ],
)
def test_signature_is_scrubbed_from_urls(text: str):
    cleaned = scrub(text)
    assert REDACTED in cleaned
    # Сама подпись не остаётся ни в каком виде, а адрес — остаётся.
    for tail in ("8f3a1c9d5e7b2a4c6d8e0f1a2b3c4d5e", "1a2b3c4d5e6f7a8b", "abcdef0123456789"):
        assert tail not in cleaned or tail in text.split("=")[0]
    assert "/api/" in cleaned or "https://host" in cleaned


def test_scrub_keeps_ordinary_text_untouched():
    text = "media.fetch_failed: 404 для blob 17 (хост ответил за 3 мс)"
    assert scrub(text) == text


def test_bearer_token_and_webhook_secret_are_scrubbed():
    assert REDACTED in scrub("Authorization: Bearer abcdef1234567890xyz")
    header = "X-Telegram-Bot-Api-Secret-Token: 2f4a6c8e0b1d3f5a"
    cleaned = scrub(header)
    assert REDACTED in cleaned
    assert "2f4a6c8e0b1d3f5a" not in cleaned


def test_dsn_password_is_scrubbed():
    """Текст ошибки подключения не должен печатать пароль базы."""
    cleaned = scrub("connection failed: postgresql://user:sup3rp4ss@db.neon.tech:5432/neondb")
    assert "sup3rp4ss" not in cleaned
    assert "db.neon.tech" in cleaned


def test_event_processor_scrubs_every_string_value():
    event = redact_event(
        None,
        "warning",
        {
            "event": "media.fetch_failed",
            "url": "/api/media/17?s=8f3a1c9d5e7b2a4c6d8e0f1a2b3c4d5e",
            "items": ["/api/media/18?s=0011223344556677889900aabbccddee"],
            "count": 2,
            "nested": {"url": "/api/media/tg/9?s=ffeeddccbbaa99887766554433221100"},
        },
    )
    assert "8f3a1c9d5e7b2a4c6d8e0f1a2b3c4d5e" not in str(event)
    assert "0011223344556677889900aabbccddee" not in str(event)
    assert "ffeeddccbbaa99887766554433221100" not in str(event)
    assert event["count"] == 2
    assert event["event"] == "media.fetch_failed"


def test_application_uses_the_redacting_chain():
    """Полоскание должно стоять в боевой цепочке, а не существовать отдельно."""
    processors = log_processors()
    names = [
        getattr(item, "__name__", type(item).__name__) for item in processors
    ]
    assert "redact_event" in names
    # Рендерер — последний в цепочке, каким бы он ни был: полоскание обязано
    # идти до него (иначе оно полоскает не то). Именно так, а не по имени
    # `JSONRenderer`: 31.10.2026 рендерер сменился на консольный, потому что
    # панель хостинга не показывает JSON-строки вообще.
    renderer_at = names.index("ConsoleRenderer")
    assert renderer_at == len(names) - 1, "рендерер должен быть последним"
    assert names.index("redact_event") < renderer_at, (
        "полоскание должно идти до рендерера, иначе оно полоскает не то"
    )


def test_structlog_writes_to_stderr_not_stdout():
    """structlog обязан идти в stderr.

    Регрессия 31.10.2026: события structlog (`scheduler.job_fired` и остальные)
    месяцами не попадали в логи хостинга — панель Amvera собирает stderr, а
    `PrintLogger` по умолчанию пишет в stdout. Диагностика существовала, но её
    нельзя было увидеть, поэтому здесь закреплён сам приёмник, а не только
    состав процессоров.
    """
    import sys

    configure_logging()
    factory = structlog.get_config()["logger_factory"]
    assert factory._file is sys.stderr, (
        "structlog должен писать в stderr: stdout панель хостинга не собирает"
    )


def test_migrations_process_uses_the_same_chain():
    """`app.db.migrate` стартует отдельным процессом — цепочка у него та же.

    Проверяем именно `configure_logging()`, а не список процессоров: с
    31.10.2026 общая настройка включает ещё и приёмник (stderr), и миграции
    обязаны получать его тем же вызовом, что и приложение.
    """
    source = (ROOT / "app" / "db" / "migrate.py").read_text(encoding="utf-8")
    assert "configure_logging" in source
    # Важно и то, ЧЕМ импортируется: из `app.main` это тянуло бы всё приложение
    # в процесс миграций и поднимало его память (см. S-19).
    assert "from app.main import" not in source
