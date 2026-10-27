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

from app.config import (  # noqa: E402
    DEFAULT_CORS_ORIGIN_REGEX,
    Settings,
    origin_of_url,
)


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


# --- широкая регулярка из среды (S-1b) ------------------------------------
#
# Живая проба на боевом Space 26.10.2026: `access-control-allow-origin:
# https://evil.example.com` + `allow-credentials: true`. В коде белый список был,
# но переменная `CORS_ORIGIN_REGEX` с широким шаблоном заставляла Starlette
# отражать любой Origin. Эти тесты фиксируют, что такое значение не работает.


ITER_FOREIGN_PATTERNS = (
    r".*",
    r"https://.*",
    r"^https?://.*$",
    r"https?://[a-z0-9.-]+",
    r"|",  # пустая ветка в альтернативе — тоже «пускает всех»
)


def test_wide_regex_from_env_is_replaced_with_safe_default():
    for pattern in ITER_FOREIGN_PATTERNS:
        settings = _settings(CORS_ORIGIN_REGEX=pattern)
        assert settings.cors_origin_regex_rejected is True, pattern
        assert settings.cors_origin_regex_or_none == DEFAULT_CORS_ORIGIN_REGEX, pattern


def test_safe_regex_from_env_is_kept_as_is():
    pattern = r"https://([a-z0-9-]+\.)*my-own-domain\.example"
    settings = _settings(CORS_ORIGIN_REGEX=pattern)
    assert settings.cors_origin_regex_rejected is False
    assert settings.cors_origin_regex_or_none == pattern


def test_invalid_regex_is_rejected_not_crashed():
    settings = _settings(CORS_ORIGIN_REGEX=r"https://([unclosed")
    assert settings.cors_origin_regex_rejected is True
    assert settings.cors_origin_regex_or_none == DEFAULT_CORS_ORIGIN_REGEX


def test_canary_check_covers_both_match_semantics():
    r"""Ловим и `fullmatch`, и `match`: версии Starlette разные.

    Обрезанный шаблон (`https://evil\.example\.co`) на `fullmatch` не сработал
    бы, а на `match` — да: такую регулярку тоже нельзя пускать в дело.
    """
    import re

    from app.config import CORS_ORIGIN_CANARIES, cors_regex_allows_foreign

    canary = CORS_ORIGIN_CANARIES[0]
    truncated = r"https://evil\.example\.co"
    assert re.fullmatch(truncated, canary) is None  # только `match` его ловит
    assert re.match(truncated, canary) is not None
    assert cors_regex_allows_foreign(truncated) is True
    assert cors_regex_allows_foreign(r"https://evil\.example\.com$") is True
    assert cors_regex_allows_foreign(r"https://our-own\.example") is False


def test_deploy_default_regex_matches_code():
    """Регулярка в деплой-инструменте и в коде должны совпадать.

    `tools/deploy-hf.py` кладёт в Space `SAFE_CORS_ORIGIN_REGEX`, не импортируя
    приложение. Если две копии разойдутся, в Space уедет одно правило, а код
    применит другое — и вопрос «почему на бою не то же, что локально» вернётся.
    """
    import ast
    from pathlib import Path

    import pytest

    script = Path(__file__).resolve().parents[2] / "tools" / "deploy-hf.py"
    if not script.exists():
        pytest.skip("копия без tools/ (например, зеркало Space)")
    tree = ast.parse(script.read_text(encoding="utf-8"))
    value = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == "SAFE_CORS_ORIGIN_REGEX" for target in node.targets
        ):
            value = ast.literal_eval(node.value)
    assert value == DEFAULT_CORS_ORIGIN_REGEX


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


def test_wide_regex_in_env_cannot_open_the_perimeter(monkeypatch):
    """Сквозная проверка: широкая регулярка в среде не открывает никого.

    Именно этот случай был на бою: список Origin правильный, а регулярка из
    переменных пускала любой сайт. Здесь она выставлена в среде и должно быть
    видно, что чужой Origin всё равно не получает `allow-origin`.
    """
    monkeypatch.setenv("CORS_ORIGINS", "https://semitaskbot.pages.dev")
    monkeypatch.setenv("CORS_ORIGIN_REGEX", "https://.*")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        client = _client()
        foreign = client.get("/healthz", headers={"Origin": "https://evil.example.com"})
        assert "access-control-allow-origin" not in foreign.headers
        own = client.get("/healthz", headers={"Origin": "https://semitaskbot.pages.dev"})
        assert own.headers["access-control-allow-origin"] == "https://semitaskbot.pages.dev"
        cover = client.get(
            "/healthz", headers={"Origin": "https://a1b2c3d4.semitaskbot.pages.dev"}
        )
        assert cover.headers["access-control-allow-origin"] == (
            "https://a1b2c3d4.semitaskbot.pages.dev"
        )
    finally:
        get_settings.cache_clear()
        monkeypatch.delenv("CORS_ORIGIN_REGEX", raising=False)
        monkeypatch.delenv("CORS_ORIGINS", raising=False)


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
