"""CORS: белый список Origin вместо звёздочки (S-1).

Живая проба на бою 26.10.2026 показала, что с `CORS_ORIGINS=*` и
`allow_credentials=True` Starlette отвечает `access-control-allow-origin` равным
**любому** Origin запроса. Здесь проверяем, что эта комбинация больше невозможна
ни при какой конфигурации, а своё приложение при этом не страдает.

Настройки читаются через `Settings` напрямую (без env): так тест говорит о
правиле, а не о том, что лежит в переменных окружения машины.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://semitaskbot.pages.dev")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.test_cors.db")

from app.config import Settings, origin_of_url  # noqa: E402


def _settings(**overrides) -> Settings:
    base = {
        "BOT_TOKEN": "test-token",
        "TG_WEBHOOK_SECRET": "test-secret",
        "MINI_APP_URL": "https://semitaskbot.pages.dev",
        "DATABASE_URL": "sqlite+aiosqlite:///./.test_cors.db",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_star_never_gets_credentials():
    """`*` + credentials — это и есть дыра: сочетание запрещено."""
    settings = _settings(CORS_ORIGINS="*")
    assert settings.cors_allow_all is True
    assert settings.cors_credentials_allowed is False
    assert settings.cors_allowed_origins == ["*"]


def test_empty_origins_is_treated_as_star_without_credentials():
    settings = _settings(CORS_ORIGINS="")
    assert settings.cors_allowed_origins == ["*"]
    assert settings.cors_credentials_allowed is False


def test_explicit_list_allows_credentials_and_keeps_own_origins():
    settings = _settings(
        CORS_ORIGINS="https://app.example.com, https://admin.example.com",
        APP_PUBLIC_URL="https://semitask.example.org/web",
    )
    assert settings.cors_credentials_allowed is True
    assert settings.cors_allowed_origins == [
        "https://app.example.com",
        "https://admin.example.com",
        # Свой мини-апп и веб-версия разрешены всегда: иначе владелец, забывший
        # вписать свой домен, получил бы неработающее приложение.
        "https://semitaskbot.pages.dev",
        "https://semitask.example.org",
    ]


def test_own_origin_is_not_duplicated():
    settings = _settings(
        CORS_ORIGINS="https://semitaskbot.pages.dev",
        MINI_APP_URL="https://semitaskbot.pages.dev",
    )
    assert settings.cors_allowed_origins == ["https://semitaskbot.pages.dev"]


def test_preview_and_localhost_regex_is_configured_by_default():
    settings = _settings()
    regex = settings.cors_origin_regex_or_none
    assert regex is not None
    assert "semitaskbot" in regex
    assert "localhost" in regex


def test_regex_can_be_disabled():
    assert _settings(CORS_ORIGIN_REGEX="off").cors_origin_regex_or_none is None
    assert _settings(CORS_ORIGIN_REGEX="").cors_origin_regex_or_none is None


def test_origin_of_url_ignores_relative_and_empty():
    assert origin_of_url("https://host.example/app?x=1") == "https://host.example"
    assert origin_of_url("http://localhost:5173") == "http://localhost:5173"
    assert origin_of_url("") == ""
    assert origin_of_url("/app") == ""


# --- поведение живого приложения ------------------------------------------


def _client():
    from starlette.testclient import TestClient

    from app.main import create_app

    # Без контекстного менеджера: lifespan (сидинг, вебхук Telegram) в тесте не
    # нужен, а ручки ответят отказом авторизации — для CORS это неважно.
    return TestClient(create_app(), raise_server_exceptions=False)


def test_foreign_origin_gets_no_allow_origin():
    client = _client()
    res = client.get("/healthz", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers


def test_own_production_origin_is_allowed():
    client = _client()
    res = client.get(
        "/healthz", headers={"Origin": "https://semitaskbot.pages.dev"}
    )
    assert res.headers["access-control-allow-origin"] == "https://semitaskbot.pages.dev"


def test_preview_deployment_origin_is_allowed():
    client = _client()
    origin = "https://a1b2c3d4.semitaskbot.pages.dev"
    res = client.get("/healthz", headers={"Origin": origin})
    assert res.headers["access-control-allow-origin"] == origin


def test_preflight_from_foreign_origin_is_refused():
    client = _client()
    res = client.options(
        "/api/auth/login",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in res.headers


def test_preflight_from_own_origin_is_allowed_for_authorization_header():
    client = _client()
    res = client.options(
        "/api/auth/login",
        headers={
            "Origin": "https://semitaskbot.pages.dev",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert res.headers["access-control-allow-origin"] == "https://semitaskbot.pages.dev"
    assert "authorization" in res.headers["access-control-allow-headers"].lower()
