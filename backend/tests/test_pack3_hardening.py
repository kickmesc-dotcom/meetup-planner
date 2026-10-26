"""Третий пакет правок: срок службы секретов и гонка при выкладке.

S-10 (подпись iCal-ссылки), S-13 (сравнение секретов), S-14 (блокировка миграций).
Проверяем ровно то, ради чего правили: старые ссылки продолжают работать, новые
подписаны длиннее; незнакомый секрет не совпадает и не роняет обработчик;
второй контейнер ждёт, а не применяет миграции параллельно.
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("MINI_APP_URL", "https://semitaskbot.pages.dev")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.test_pack3.db")

import pytest  # noqa: E402

from app.db import migrate  # noqa: E402
from app.services import ical, org_bots  # noqa: E402

# --- S-10: подпись iCal ------------------------------------------------------


def test_new_token_is_longer_than_legacy():
    token = ical.make_token(42)
    assert len(token) == ical.TOKEN_LENGTH == 32
    assert len(token) > ical.LEGACY_TOKEN_LENGTH
    assert token.isalnum()


def test_current_token_verifies():
    assert ical.verify_token(7, ical.make_token(7)) is True


def test_legacy_short_token_still_verifies():
    """Уже подключённые календари не должны отвалиться после правки."""
    user_id = 7
    legacy = ical.make_token(user_id)[: ical.LEGACY_TOKEN_LENGTH]
    assert ical.verify_token(user_id, legacy) is True


def test_token_is_bound_to_user_and_rejects_rubbish():
    assert ical.verify_token(8, ical.make_token(7)) is False
    assert ical.verify_token(7, "") is False
    assert ical.verify_token(7, "0" * 32) is False
    assert ical.verify_token(7, "не-токен") is False


def test_token_changes_with_secret(monkeypatch: pytest.MonkeyPatch):
    """Подпись считается от секрета вебхука: смена секрета отзывает все ссылки."""
    before = ical.make_token(7)
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "другой-секрет")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        after = ical.make_token(7)
    finally:
        get_settings.cache_clear()
    assert before != after


# --- S-13: сравнение секретов -----------------------------------------------


def _config(org_id: int, secret: str):
    return org_bots.OrgBotConfig(
        org_id=org_id, slug=f"org{org_id}", token=f"token{org_id}",
        chat_id=None, webhook_secret=secret,
    )


def test_webhook_secret_lookup_finds_own_org(monkeypatch: pytest.MonkeyPatch):
    org_bots.reset()
    monkeypatch.setitem(org_bots._registry, 1, _config(1, "secret-one"))
    monkeypatch.setitem(org_bots._registry, 2, _config(2, "secret-two"))
    try:
        assert org_bots.org_for_webhook_secret("secret-two") == 2
        assert org_bots.org_for_webhook_secret("secret-one") == 1
        assert org_bots.org_for_webhook_secret("secret-three") is None
        assert org_bots.org_for_webhook_secret("") is None
        assert org_bots.org_for_token("token1") == 1
    finally:
        org_bots.reset()


def test_non_ascii_secret_does_not_break_lookup(monkeypatch: pytest.MonkeyPatch):
    """В заголовке может прийти что угодно: должен быть отказ, а не 500."""
    org_bots.reset()
    monkeypatch.setitem(org_bots._registry, 1, _config(1, "secret-one"))
    try:
        assert org_bots.org_for_webhook_secret("секрет-с-кириллицей") is None
        assert org_bots.org_for_webhook_secret("secret-one ") is None
    finally:
        org_bots.reset()


def test_prefix_of_secret_is_not_a_match(monkeypatch: pytest.MonkeyPatch):
    org_bots.reset()
    monkeypatch.setitem(org_bots._registry, 1, _config(1, "very-long-secret-value"))
    try:
        assert org_bots.org_for_webhook_secret("very-long") is None
    finally:
        org_bots.reset()


# --- S-14: блокировка миграций ----------------------------------------------


def test_asyncpg_dsn_drops_driver_and_query():
    dsn = migrate.asyncpg_dsn("postgresql+asyncpg://u:p@host:5432/db?application_name=x")
    assert dsn == "postgresql://u:p@host:5432/db"


def test_wait_seconds_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DB_MIGRATE_LOCK_WAIT_SECONDS", raising=False)
    assert migrate.wait_seconds() == migrate.DEFAULT_WAIT_SECONDS
    monkeypatch.setenv("DB_MIGRATE_LOCK_WAIT_SECONDS", "30")
    assert migrate.wait_seconds() == 30.0
    monkeypatch.setenv("DB_MIGRATE_LOCK_WAIT_SECONDS", "off")
    assert migrate.wait_seconds() == float("inf")
    monkeypatch.setenv("DB_MIGRATE_LOCK_WAIT_SECONDS", "мусор")
    assert migrate.wait_seconds() == migrate.DEFAULT_WAIT_SECONDS


class _FakeConn:
    """Соединение-заглушка: считает запросы и отдаёт заранее заданные ответы."""

    def __init__(self, answers: list[bool]) -> None:
        self._answers = answers
        self.queries: list[str] = []

    async def fetchval(self, query: str, _key: int) -> bool:
        self.queries.append(query)
        value = self._answers.pop(0) if self._answers else False
        if "pg_try_advisory_lock" in query:
            self.took_lock = self.took_lock or value
        return value

    took_lock = False


def test_lock_is_acquired_on_first_try():
    conn = _FakeConn([True])
    assert asyncio.run(migrate.acquire_lock(conn, wait=5.0)) is True
    assert len(conn.queries) == 1


def test_lock_waits_while_other_container_holds_it():
    conn = _FakeConn([False, False, True])
    assert asyncio.run(migrate.acquire_lock(conn, wait=5.0)) is True
    # Три попытки: два отказа и успех на третьей.
    assert len(conn.queries) == 3


def test_lock_gives_up_instead_of_running_migrations_in_parallel():
    conn = _FakeConn([])  # лок всегда занят
    assert asyncio.run(migrate.acquire_lock(conn, wait=0.0)) is False


def test_lock_key_is_stable():
    """Ключ один на весь контур: иначе блокировка ничего не значит."""
    assert migrate.MIGRATIONS_LOCK_KEY == 771144
