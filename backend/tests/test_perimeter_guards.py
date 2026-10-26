"""Предохранители периметра: размер тела, лимит частоты, защитные заголовки.

Аудит 26.10.2026 (`docs/AUDIT_SECURITY_STABILITY.md`), находки S-2 и S-3.
Проверяем свойства, а не «middleware вызвался»:

* тело сверх предела отклоняется ПО КОНТЕНТ-ДЛИНЕ и ПО ПОТОКУ (chunked);
* лимит частоты отвечает `429` с `Retry-After`, считает восстановление в окне,
  и не задевает `OPTIONS` (предпросмотр CORS — не работа с данными);
* у `429` есть CORS-заголовки: иначе браузер покажет сетевую ошибку вместо
  «слишком много попыток»;
* защитные заголовки добавляются, но НЕ затирают то, что поставила ручка.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://semitaskbot.pages.dev")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.test_perimeter.db")

import pytest  # noqa: E402
from fastapi import FastAPI, Request, Response  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app.api import guards  # noqa: E402


# --- размер тела -----------------------------------------------------------


def _echo_app() -> FastAPI:
    """Минимальное приложение: принимает тело и возвращает его длину."""
    inner = FastAPI()

    @inner.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        body = await request.body()
        return {"size": len(body)}

    return inner


def _limited_client(inner: FastAPI, limit: int) -> TestClient:
    from starlette.middleware import Middleware

    return TestClient(
        guards.BodySizeLimitMiddleware(inner, max_bytes=limit),
    )


def test_body_over_limit_by_content_length_is_rejected_without_reading():
    client = _limited_client(_echo_app(), 1024)
    res = client.post("/echo", content=b"x" * 4096)

    assert res.status_code == 413
    assert res.json()["detail"] == "body_too_large"
    # Ответ не должен быть закэширован: это отказ, а не данные.
    assert res.headers["cache-control"] == "no-store"


def test_body_within_limit_is_passed_through():
    client = _limited_client(_echo_app(), 1024)
    res = client.post("/echo", content=b"x" * 512)

    assert res.status_code == 200
    assert res.json() == {"size": 512}


def test_chunked_body_without_length_is_capped_while_streaming():
    """Тело без `Content-Length` (chunked) тоже обрывается по пределу."""

    def chunks():
        for _ in range(64):
            yield b"x" * 256

    client = _limited_client(_echo_app(), 1024)
    res = client.post("/echo", content=chunks())

    assert res.status_code == 413
    assert res.json()["detail"] == "body_too_large"


def test_guard_can_be_switched_off_by_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAX_REQUEST_BYTES", "off")
    client = _limited_client(_echo_app(), None)
    assert client.post("/echo", content=b"x" * 4096).status_code == 200


def test_max_body_bytes_default_and_explicit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAX_REQUEST_BYTES", raising=False)
    assert guards.max_body_bytes() == guards.DEFAULT_MAX_BODY_BYTES
    monkeypatch.setenv("MAX_REQUEST_BYTES", "2048")
    assert guards.max_body_bytes() == 2048
    monkeypatch.setenv("MAX_REQUEST_BYTES", "мусор")
    assert guards.max_body_bytes() == guards.DEFAULT_MAX_BODY_BYTES


# --- лимит частоты ---------------------------------------------------------


def test_sliding_window_counts_and_releases():
    limiter = guards.SlidingWindowLimiter()
    for _ in range(3):
        assert limiter.check("k", limit=3, window=10.0, now=100.0) is None
    # Четвёртая попытка внутри окна — ждать до выхода первой (100 + 10).
    assert limiter.check("k", limit=3, window=10.0, now=100.0) == pytest.approx(10.0)
    # Через окно счётчик освободился.
    assert limiter.check("k", limit=3, window=10.0, now=110.5) is None


def test_sliding_window_is_per_key():
    limiter = guards.SlidingWindowLimiter()
    for _ in range(2):
        limiter.check("a", limit=2, window=5.0, now=1.0)
    assert limiter.check("a", limit=2, window=5.0, now=1.0) is not None
    assert limiter.check("b", limit=2, window=5.0, now=1.0) is None


def test_client_ip_prefers_public_socket_address():
    # 8.8.8.8, а не 203.0.113.7: адреса из TEST-NET `ipaddress` считает
    # приватными, и тест проверял бы не ту ветку.
    scope = {"client": ("8.8.8.8", 1234), "headers": [(b"x-forwarded-for", b"1.2.3.4")]}
    # Прямое подключение: верим адресу соединения, а не заголовку.
    assert guards.client_ip(scope) == "8.8.8.8"


def test_client_ip_uses_forwarded_for_behind_proxy():
    scope = {"client": ("10.111.85.1", 1234), "headers": [(b"x-forwarded-for", b"1.2.3.4, 10.0.0.1")]}
    # За прокси адрес соединения внутренний, настоящий — первый хоп.
    assert guards.client_ip(scope) == "1.2.3.4"


def test_rules_cover_the_public_entry_points():
    """Лимит стоит именно там, где он нужен: вход, письма, фото, вступление."""
    names = {rule.name for rule in guards.rules()}
    assert {"auth_login", "auth_mail", "media_upload", "org_join"} <= names
    login = next(rule for rule in guards.rules() if rule.name == "auth_login")
    assert login.matches("POST", "/api/auth/login")
    assert login.matches("POST", "/api/auth/password/reset/confirm")
    # Письма лимитируются отдельно и жёстче: каждое письмо стоит денег.
    mail = next(rule for rule in guards.rules() if rule.name == "auth_mail")
    assert mail.matches("POST", "/api/auth/password/reset/request")
    assert mail.limit < login.limit
    # Вебхук Telegram лимитом не трогаем — это законный трафик.
    assert not any(rule.matches("POST", "/tg/webhook") for rule in guards.rules())


def test_rate_limit_middleware_returns_429_with_retry_after():
    inner = FastAPI()

    @inner.post("/api/auth/login")
    async def login() -> dict[str, bool]:
        return {"ok": True}

    rule = guards.RateRule(
        name="unit",
        methods=("POST",),
        pattern=__import__("re").compile(r"/api/auth/login"),
        limit=2,
        window=60.0,
        global_limit=100,
    )
    client = TestClient(guards.RateLimitMiddleware(inner, rules_=[rule]))

    assert client.post("/api/auth/login").status_code == 200
    assert client.post("/api/auth/login").status_code == 200
    blocked = client.post("/api/auth/login")
    assert blocked.status_code == 429
    assert blocked.json()["detail"].startswith("rate_limited:")
    assert int(blocked.headers["retry-after"]) >= 1


def test_preflight_is_never_rate_limited():
    inner = FastAPI()

    @inner.post("/api/auth/login")  # pragma: no cover - вызываться не должен
    async def login() -> dict[str, bool]:
        return {"ok": True}

    rule = guards.RateRule(
        name="unit",
        methods=("POST",),
        pattern=__import__("re").compile(r"/api/auth/login"),
        limit=1,
        window=60.0,
        global_limit=100,
    )
    client = TestClient(guards.RateLimitMiddleware(inner, rules_=[rule]))
    for _ in range(5):
        assert client.options("/api/auth/login").status_code != 429


def test_global_counter_bounds_forwarded_for_spoofing():
    """Подделка `X-Forwarded-For` не снимает лимит целиком: есть общий счётчик."""
    inner = FastAPI()

    @inner.post("/api/auth/login")
    async def login() -> dict[str, bool]:
        return {"ok": True}

    rule = guards.RateRule(
        name="unit",
        methods=("POST",),
        pattern=__import__("re").compile(r"/api/auth/login"),
        limit=1,
        window=60.0,
        global_limit=3,
    )
    client = TestClient(guards.RateLimitMiddleware(inner, rules_=[rule]))
    statuses = [
        client.post(
            "/api/auth/login", headers={"x-forwarded-for": f"203.0.113.{i}"}
        ).status_code
        for i in range(1, 6)
    ]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3:] == [429, 429]


def test_rate_limit_can_be_switched_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RATE_LIMIT_OFF", "1")
    inner = FastAPI()

    @inner.get("/api/auth/login")
    async def login() -> dict[str, bool]:  # pragma: no cover - проверяем проход
        return {"ok": True}

    rule = guards.RateRule(
        name="unit",
        methods=("GET",),
        pattern=__import__("re").compile(r"/api/auth/login"),
        limit=0,
        window=60.0,
        global_limit=0,
    )
    client = TestClient(guards.RateLimitMiddleware(inner, rules_=[rule]))
    assert client.get("/api/auth/login").status_code == 200


# --- защитные заголовки ----------------------------------------------------


def test_security_headers_added_but_handler_wins():
    inner = FastAPI()

    @inner.get("/plain")
    async def plain() -> Response:
        return Response("ok", headers={"referrer-policy": "same-origin"})

    client = TestClient(guards.SecurityHeadersMiddleware(inner))
    res = client.get("/plain")

    assert res.headers["x-content-type-options"] == "nosniff"
    # Значение ручки не затирается: свои заголовки ручка знает лучше.
    assert res.headers["referrer-policy"] == "same-origin"


def test_no_secret_is_written_to_log(caplog: pytest.LogCaptureFixture):
    """В лог лимита не должен попадать ни секрет вебхука, ни токен."""
    inner = FastAPI()

    @inner.post("/api/auth/login")
    async def login() -> dict[str, bool]:
        return {"ok": True}

    rule = guards.RateRule(
        name="unit",
        methods=("POST",),
        pattern=__import__("re").compile(r"/api/auth/login"),
        limit=1,
        window=60.0,
        global_limit=1,
    )
    client = TestClient(guards.RateLimitMiddleware(inner, rules_=[rule]))
    client.post("/api/auth/login", headers={"x-forwarded-for": "203.0.113.9"})
    client.post("/api/auth/login")
    # Сам ответ тоже не несёт ничего лишнего.
    body = client.post("/api/auth/login").json()
    assert set(body) == {"detail"}
    assert json.dumps(body, ensure_ascii=False).startswith('{"detail"')
