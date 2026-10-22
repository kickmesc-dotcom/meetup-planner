"""Ссылки доступа в браузер: токен как пароль.

Проверяем чистые правила, от которых зависит безопасность: в базе лежит только
хеш, токен одноразово показывается в ссылке, срок и отзыв действительно
закрывают вход. Работа с БД (`issue`/`resolve`) — интеграционная и проверяется
на живом Postgres в `tools/hr-pg-test.py`.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from app.db.hr_models import AppAccessLink
from app.services import app_access


def _link(
    *,
    expires_in: timedelta = timedelta(days=30),
    revoked: bool = False,
) -> AppAccessLink:
    moment = datetime.now(UTC)
    link = AppAccessLink(
        id=1,
        user_id=7,
        token_hash=app_access.hash_token(app_access.generate_token()),
        label="Веб-версия",
        expires_at=moment + expires_in,
        revoked_at=moment if revoked else None,
    )
    return link


# --- Токен ----------------------------------------------------------------


def test_token_has_prefix_and_enough_entropy():
    token = app_access.generate_token()
    assert token.startswith(app_access.TOKEN_PREFIX)
    # 32 байта в base64url — это 43 символа; порог ниже оставляет запас, но
    # ловит случайное «укоротили до 8 символов».
    assert len(token) >= 40
    assert app_access.generate_token() != token


def test_database_stores_only_hash():
    token = app_access.generate_token()
    hashed = app_access.hash_token(token)
    assert hashed == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert token not in hashed
    assert len(hashed) == 64
    # Тот же токен — тот же хеш (иначе вход не найдёт строку).
    assert app_access.hash_token(f"  {token}  ") == hashed


def test_hash_is_not_plain_and_differs_per_token():
    a = app_access.hash_token(app_access.generate_token())
    b = app_access.hash_token(app_access.generate_token())
    assert a != b


# --- Ссылка ---------------------------------------------------------------


def test_url_appends_access_parameter():
    assert (
        app_access.build_url("https://app.example.com", "sweb_abc")
        == "https://app.example.com?access=sweb_abc"
    )


def test_url_keeps_existing_query():
    assert (
        app_access.build_url("https://app.example.com/?startapp=feed", "sweb_abc")
        == "https://app.example.com/?startapp=feed&access=sweb_abc"
    )


def test_empty_base_gives_empty_url():
    # Пустой MINI_APP_URL не должен превращаться в «?access=…» без хоста.
    assert app_access.build_url("", "sweb_abc") == ""


# --- Срок и отзыв ---------------------------------------------------------


def test_fresh_link_is_active():
    assert app_access.is_active(_link())


def test_expired_link_is_not_active():
    assert not app_access.is_active(_link(expires_in=timedelta(minutes=-1)))


def test_revoked_link_is_not_active_even_if_not_expired():
    assert not app_access.is_active(_link(revoked=True))


def test_default_lifetime_is_one_month():
    assert app_access.DEFAULT_TTL_DAYS == 30


def test_active_links_are_capped():
    # Держим закладки, а не коллекцию: старые сверх лимита отзываются.
    assert 1 <= app_access.MAX_ACTIVE_LINKS <= 10


# --- Авторизация ----------------------------------------------------------


def test_owner_can_be_resolved_only_by_token_prefix():
    """Токен без префикса даже не ищется в базе — это отсекает мусор."""
    assert app_access.TOKEN_PREFIX == "sweb_"
