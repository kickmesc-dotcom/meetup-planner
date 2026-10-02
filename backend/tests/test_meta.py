"""GHG10-ops: `/api/meta` — отпечаток кода, цель по БД и список возможностей.

Зачем тесты именно здесь: этот роут — единственный способ узнать снаружи, на
какой ревизии стоит боевой контейнер и в какую базу он пишет (см.
`docs/AMVERA_BUILD_DIAGNOSTIC.md`). Ошибка в маскировке хоста означала бы утечку
DSN в открытый эндпоинт, поэтому проверяем и её.
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI

from app.api import routes_meta
from app.api.routes_meta import (
    _mask_host,
    _provider,
    available_features,
    build_marker,
    code_fingerprint,
    db_target,
)


def _app_with(routes: list[tuple[str, str]]) -> FastAPI:
    app = FastAPI()

    async def _noop() -> dict[str, str]:
        return {}

    for method, path in routes:
        app.add_api_route(path, _noop, methods=[method])
    return app


# --- отпечаток кода -----------------------------------------------------------

def test_fingerprint_is_stable_and_route_sensitive():
    routes = [("GET", "/api/me/game"), ("POST", "/api/game/donate")]
    first = code_fingerprint(_app_with(routes))
    second = code_fingerprint(_app_with(list(reversed(routes))))
    assert first["fingerprint"] == second["fingerprint"]
    assert first["routes"] == 2

    other = code_fingerprint(_app_with([*routes, ("GET", "/api/game/holidays")]))
    assert other["fingerprint"] != first["fingerprint"]
    assert other["routes"] == 3


def test_fingerprint_ignores_service_routes_and_head():
    plain = code_fingerprint(_app_with([("GET", "/api/x")]))
    noisy = code_fingerprint(
        _app_with(
            [
                ("GET", "/api/x"),
                ("GET", "/openapi.json"),
                ("GET", "/docs"),
                ("HEAD", "/api/x"),
                ("OPTIONS", "/api/x"),
            ]
        )
    )
    assert plain == noisy


def test_fingerprint_counts_api_routes():
    fp = code_fingerprint(_app_with([("GET", "/api/x"), ("GET", "/tg/webhook")]))
    assert fp["routes"] == 2
    assert fp["api_routes"] == 1


# --- маркер сборки ------------------------------------------------------------

def test_build_marker_prefers_env_sha(monkeypatch):
    """Если хостинг отдал ревизию в env — берём её (короткие 12 символов)."""
    monkeypatch.setattr(routes_meta, "_build_cache", None)
    monkeypatch.setenv("GIT_SHA", "abcdef0123456789abcdef")
    marker = build_marker()
    assert marker == {"build": "abcdef012345", "source": "env"}


def test_build_marker_falls_back_without_env(monkeypatch):
    """Без env маркер всё равно есть: git или хеш исходников, но не пусто."""
    monkeypatch.setattr(routes_meta, "_build_cache", None)
    for name in routes_meta._BUILD_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    marker = build_marker()
    assert marker["source"] in {"git", "hash"}
    assert marker["build"]


def test_build_marker_is_cached(monkeypatch):
    monkeypatch.setattr(routes_meta, "_build_cache", None)
    first = build_marker()
    second = build_marker()
    assert first is second


# --- возможности -------------------------------------------------------------

def test_features_follow_registered_routes():
    app = _app_with(
        [
            ("GET", "/api/me/game"),
            ("GET", "/api/game/holidays"),
            ("POST", "/api/game/donate"),
        ]
    )
    assert available_features(app) == ["game.donate", "game.holidays", "me.game"]


def test_features_empty_on_old_build():
    """Этак 2–8 (живой Amvera на 2026-09-29) умел только это."""
    app = _app_with([("GET", "/api/me/game"), ("GET", "/api/game/achievements")])
    features = available_features(app)
    assert "game.donate" not in features
    assert "game.holidays" not in features
    assert "admin.game" not in features


def test_admin_game_detected():
    assert available_features(_app_with([("GET", "/api/admin/game")])) == ["admin.game"]


# --- маскировка хоста и провайдер --------------------------------------------

def test_mask_host_keeps_project_and_domain_only():
    masked = _mask_host("ep-cool-union-aszq9p4u.c-4.eu-central-1.aws.neon.tech")
    assert masked == "ep-cool-union-….neon.tech"
    assert "aszq9p4u" not in masked
    assert "eu-central-1" not in masked


def test_mask_host_handles_short_and_none():
    assert _mask_host(None) is None
    assert _mask_host("localhost") == "localhost"


def test_provider_detection():
    assert _provider("ep-cool-union-aszq9p4u.c-4.eu-central-1.aws.neon.tech") == "neon"
    assert _provider("db-1.amvera.ru") == "amvera"
    assert _provider("localhost") == "local"
    assert _provider("127.0.0.1") == "local"
    assert _provider("pg.example.com") == "other"
    assert _provider(None) == "local"


def test_db_target_never_leaks_credentials(monkeypatch):
    secret = "npg_GuSFzjs2L6ny"
    monkeypatch.setattr(
        routes_meta,
        "get_settings",
        lambda: SimpleNamespace(
            database_url=(
                f"postgresql+asyncpg://neondb_owner:{secret}"
                "@ep-cool-union-aszq9p4u.c-4.eu-central-1.aws.neon.tech:5432/neondb"
            )
        ),
    )
    payload = db_target()
    assert payload == {
        "provider": "neon",
        "host": "ep-cool-union-….neon.tech",
        "port": 5432,
        "name": "neondb",
    }
    assert secret not in str(payload)
    assert "neondb_owner" not in str(payload)
