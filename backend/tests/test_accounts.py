"""Вход по почте: аккаунт, сессии, сброс (B2B_PLATFORM_PLAN, шаг 2.1).

Проверяем не «ручка ответила 200», а свойства, без которых вход небезопасен:

* пароль не хранится и не сравним побайтово (соль у каждого своя);
* «нет такого адреса» и «неверный пароль» неразличимы снаружи;
* токен сессии живёт только у клиента — в базе его хеш;
* отозванная и истёкшая сессия не пускают;
* сброс пароля: одинаковый ответ на любой адрес, ссылка одноразовая, после
  смены все старые входы погашены;
* почтовый вход входит в организацию из членства, а без членства получает
  403, а не сотрудника в первой организации.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.api import deps  # noqa: E402
from app.api import routes_auth  # noqa: E402
from app.db.auth_models import AuthSession, PasswordReset  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.org_models import DEFAULT_ORG_ID, Organization, current_org_id, reset_org, set_org  # noqa: E402
from app.services import accounts, mail, orgs  # noqa: E402

TABLES = (
    "organizations",
    "users",
    "employees",
    "organization_members",
    "auth_sessions",
    "password_resets",
)

PASSWORD = "correct-horse-battery"
EMAIL = "Owner@Example.COM"


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    tables = [Base.metadata.tables[name] for name in TABLES]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


@pytest.fixture(autouse=True)
def clean_org_context():
    token = set_org(DEFAULT_ORG_ID)
    yield
    reset_org(token)


async def _orgs(session) -> tuple[Organization, Organization]:
    first = Organization(id=DEFAULT_ORG_ID, slug="default", name="Моя организация")
    second = Organization(id=2, slug="salon", name="Салон")
    session.add_all([first, second])
    await session.commit()
    return first, second


# --------------------------------------------------------------------------
# Пароль
# --------------------------------------------------------------------------


def test_password_hash_is_salted_and_verifiable() -> None:
    first = accounts.hash_password(PASSWORD)
    second = accounts.hash_password(PASSWORD)
    assert first != second  # соль разная — одинаковые пароли не совпадают в базе
    assert PASSWORD not in first
    assert accounts.verify_password(PASSWORD, first)
    assert not accounts.verify_password("другой пароль", first)
    assert not accounts.verify_password(PASSWORD, None)
    assert not accounts.verify_password(PASSWORD, "мусор")


def test_hash_records_its_own_iterations() -> None:
    """Старый хеш с меньшим числом итераций обязан проверяться своим числом."""
    import base64
    import hashlib
    import secrets

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", PASSWORD.encode(), salt, 10_000)
    stored = "$".join(
        (
            "pbkdf2_sha256",
            "10000",
            base64.b64encode(salt).decode(),
            base64.b64encode(digest).decode(),
        )
    )
    assert accounts.verify_password(PASSWORD, stored)


def test_email_is_normalized_and_validated() -> None:
    assert accounts.normalize_email(" Owner@Example.COM ") == "owner@example.com"
    with pytest.raises(accounts.AccountsError, match="bad_email"):
        accounts.normalize_email("не-почта")


def test_password_rules() -> None:
    with pytest.raises(accounts.AccountsError, match="password_too_short"):
        accounts.validate_password("1234567")
    with pytest.raises(accounts.AccountsError, match="password_too_long"):
        accounts.validate_password("я" * 200)
    with pytest.raises(accounts.AccountsError, match="password_has_spaces"):
        accounts.validate_password("  password123  ")
    assert accounts.validate_password(PASSWORD) == PASSWORD


# --------------------------------------------------------------------------
# Аккаунт и вход
# --------------------------------------------------------------------------


async def test_register_creates_account_without_telegram(session) -> None:
    user = await accounts.register(session, email=EMAIL, password=PASSWORD, display_name="Владелец")
    assert user.id is not None
    assert user.email == "owner@example.com"
    assert user.telegram_id is None
    assert user.password_hash and PASSWORD not in user.password_hash
    assert user.display_name == "Владелец"

    # Без имени — берём часть адреса, а не пустую строку.
    plain = await accounts.register(
        session, email="manager@example.com", password=PASSWORD
    )
    assert plain.display_name == "manager"


async def test_duplicate_email_is_rejected_case_insensitive(session) -> None:
    await accounts.register(session, email=EMAIL, password=PASSWORD)
    with pytest.raises(accounts.AccountsError, match="email_taken"):
        await accounts.register(session, email="owner@example.COM", password=PASSWORD)


async def test_authenticate_hides_which_part_is_wrong(session) -> None:
    await accounts.register(session, email=EMAIL, password=PASSWORD)
    user = await accounts.authenticate(session, email="OWNER@example.com", password=PASSWORD)
    assert user.email == "owner@example.com"

    with pytest.raises(accounts.AccountsError, match="invalid_credentials"):
        await accounts.authenticate(session, email=EMAIL, password="не тот")
    with pytest.raises(accounts.AccountsError, match="invalid_credentials"):
        await accounts.authenticate(session, email="nobody@example.com", password=PASSWORD)


async def test_telegram_account_without_password_gets_its_own_error(session) -> None:
    """У аккаунта из Telegram пароля нет — это не «неверный пароль»."""
    from app.db.models import User

    session.add(
        User(
            id=10,
            telegram_id=555,
            display_name="Из Telegram",
            color_hex="#336699",
            timezone="Europe/Moscow",
        )
    )
    await session.commit()
    # Почты тоже нет: по почте такой аккаунт не находится вовсе.
    with pytest.raises(accounts.AccountsError, match="invalid_credentials"):
        await accounts.authenticate(session, email=EMAIL, password=PASSWORD)

    # А если почту привязали, но пароля нет — подсказка другая.
    row = await session.get(User, 10)
    row.email = "tg@example.com"
    await session.commit()
    with pytest.raises(accounts.AccountsError, match="password_not_set"):
        await accounts.authenticate(session, email="tg@example.com", password=PASSWORD)


# --------------------------------------------------------------------------
# Сессии
# --------------------------------------------------------------------------


async def test_session_roundtrip_and_revocation(session) -> None:
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    row, token = await accounts.create_session(session, user, user_agent="pytest")

    resolved = await accounts.resolve_session(session, token)
    assert resolved is not None
    assert resolved[0].id == user.id
    # Членства нет — организация входа пустая (не первая!).
    assert resolved[1] is None
    # В базе хеш, а не сам токен.
    assert row.token_hash != token

    assert (await accounts.resolve_session(session, "чужой-токен")) is None

    await accounts.revoke(session, row)
    assert await accounts.resolve_session(session, token) is None


async def test_expired_session_does_not_resolve(session) -> None:
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    _row, token = await accounts.create_session(
        session, user, ttl=timedelta(seconds=-1)
    )
    assert await accounts.resolve_session(session, token) is None


async def test_session_records_the_membership_org(session) -> None:
    first, second = await _orgs(session)
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    await orgs.ensure_member(session, org_id=second.id, user_id=user.id, role="manager")

    row, token = await accounts.create_session(session, user)
    assert row.org_id == second.id
    resolved = await accounts.resolve_session(session, token)
    assert resolved is not None and resolved[1] == second.id


async def test_logout_all_revokes_every_device(session) -> None:
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    first = await accounts.create_session(session, user)
    second = await accounts.create_session(session, user)

    assert await accounts.revoke_all(session, user.id) == 2
    assert await accounts.resolve_session(session, first[1]) is None
    assert await accounts.resolve_session(session, second[1]) is None

    # Новая сессия после «выйти везде» работает: отзыв не блокирует вход.
    fresh = await accounts.create_session(session, user)
    assert (await accounts.resolve_session(session, fresh[1])) is not None


# --------------------------------------------------------------------------
# Сброс пароля
# --------------------------------------------------------------------------


async def test_reset_request_for_unknown_email_changes_nothing(session) -> None:
    user, token = await accounts.request_reset(session, "nobody@example.com")
    assert (user, token) == (None, None)
    assert list(await session.scalars(select(PasswordReset))) == []


async def test_reset_flow_changes_password_and_kills_sessions(session) -> None:
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    _row, token = await accounts.create_session(session, user)

    found, reset_token = await accounts.request_reset(session, EMAIL)
    assert found is not None and reset_token

    await accounts.confirm_reset(
        session, token=reset_token, password="новый-пароль-123"
    )
    # Старый вход погашен, старый пароль не работает, новый работает.
    assert await accounts.resolve_session(session, token) is None
    with pytest.raises(accounts.AccountsError, match="invalid_credentials"):
        await accounts.authenticate(session, email=EMAIL, password=PASSWORD)
    assert (await accounts.authenticate(session, email=EMAIL, password="новый-пароль-123"))

    # Ссылка одноразовая.
    with pytest.raises(accounts.AccountsError, match="reset_invalid"):
        await accounts.confirm_reset(
            session, token=reset_token, password="ещё-один-пароль"
        )


async def test_expired_reset_link_is_rejected(session) -> None:
    await accounts.register(session, email=EMAIL, password=PASSWORD)
    _user, token = await accounts.request_reset(session, EMAIL)
    row = await session.scalar(
        select(PasswordReset).where(
            PasswordReset.token_hash == accounts.token_hash(token)
        )
    )
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()

    with pytest.raises(accounts.AccountsError, match="reset_expired"):
        await accounts.confirm_reset(session, token=token, password="новый-пароль-123")


async def test_reset_requests_are_throttled_per_address(session) -> None:
    await accounts.register(session, email=EMAIL, password=PASSWORD)
    tokens = []
    for _ in range(accounts.RESET_LIMIT_PER_HOUR):
        _user, token = await accounts.request_reset(session, EMAIL)
        assert token
        tokens.append(token)
    # Сверх лимита — письмо не создаётся (снаружи ответ всё равно 200).
    _user, token = await accounts.request_reset(session, EMAIL)
    assert token is None


# --------------------------------------------------------------------------
# Ручки
# --------------------------------------------------------------------------


async def test_route_errors_map_to_http_codes(session) -> None:
    await routes_auth.register(
        routes_auth.RegisterIn(email=EMAIL, password=PASSWORD), session, "pytest"
    )
    with pytest.raises(HTTPException) as taken:
        await routes_auth.register(
            routes_auth.RegisterIn(email=EMAIL, password=PASSWORD), session, None
        )
    assert taken.value.status_code == 409

    with pytest.raises(HTTPException) as wrong:
        await routes_auth.login(
            routes_auth.LoginIn(email=EMAIL, password="не тот"), session, None
        )
    assert wrong.value.status_code == 401
    assert wrong.value.detail == "invalid_credentials"

    with pytest.raises(HTTPException) as short:
        await routes_auth.register(
            routes_auth.RegisterIn(email="new@example.com", password="123"), session, None
        )
    assert short.value.status_code == 400
    assert short.value.detail == "password_too_short"


async def test_reset_request_always_answers_ok(session, monkeypatch) -> None:
    await accounts.register(session, email=EMAIL, password=PASSWORD)
    sent: list[mail.MailMessage] = []

    async def _capture(message: mail.MailMessage) -> str:
        sent.append(message)
        return "log"

    monkeypatch.setattr(routes_auth.mail, "send", _capture)

    assert await routes_auth.request_reset(
        routes_auth.ResetRequestIn(email="nobody@example.com"), session
    ) == {"ok": True}
    assert sent == []

    assert await routes_auth.request_reset(
        routes_auth.ResetRequestIn(email=EMAIL), session
    ) == {"ok": True}
    assert len(sent) == 1
    assert "reset?token=" in sent[0].text
    assert sent[0].to == "owner@example.com"


async def test_mail_transport_selection(monkeypatch) -> None:
    monkeypatch.setattr(
        mail, "get_settings", lambda: SimpleNamespace(resend_api_key="", smtp_host="")
    )
    assert mail.transport() == "log"
    monkeypatch.setattr(
        mail,
        "get_settings",
        lambda: SimpleNamespace(resend_api_key="", smtp_host="smtp.yandex.ru"),
    )
    assert mail.transport() == "smtp"
    monkeypatch.setattr(
        mail,
        "get_settings",
        lambda: SimpleNamespace(resend_api_key="re_123", smtp_host="smtp.yandex.ru"),
    )
    assert mail.transport() == "resend"  # HTTP-провайдер приоритетнее SMTP


# --------------------------------------------------------------------------
# Вход в приложение
# --------------------------------------------------------------------------


async def test_bearer_session_authenticates_and_sets_org(session) -> None:
    first, second = await _orgs(session)
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    await orgs.ensure_member(session, org_id=second.id, user_id=user.id)
    _row, token = await accounts.create_session(session, user)

    settings = SimpleNamespace(bot_token="1:test", initdata_max_age_seconds=86400)
    resolved = await deps.current_user(session, settings, f"Bearer {token}", None)
    assert resolved.id == user.id
    assert current_org_id.get() == second.id

    with pytest.raises(HTTPException) as bad:
        await deps.current_user(session, settings, "Bearer мусор", None)
    assert bad.value.status_code == 401


async def test_email_user_without_membership_gets_403_not_employee(session) -> None:
    await _orgs(session)
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    auth_token = deps.session_auth.set(True)
    try:
        with pytest.raises(HTTPException) as denied:
            await anext(deps.current_employee(session, user, None))
    finally:
        deps.session_auth.reset(auth_token)
    assert denied.value.status_code == 403
    assert denied.value.detail == "org_required"


async def test_telegram_user_without_membership_still_gets_an_employee(session) -> None:
    """Телеграм-вход — не повод отказывать: человек пришёл через бота.

    Именно так работал онбординг до фазы 2, и ломать его ради почтового входа
    нельзя. Разница только в способе входа (`session_auth`).
    """
    await _orgs(session)
    from app.db.models import User

    session.add(
        User(
            id=20,
            telegram_id=777,
            display_name="Из Telegram",
            color_hex="#336699",
            timezone="Europe/Moscow",
        )
    )
    await session.commit()
    user = await session.get(User, 20)

    employee = await anext(deps.current_employee(session, user, None))
    assert employee.org_id == DEFAULT_ORG_ID
    # Заодно появилось членство — иначе следующий почтовый вход в эту же
    # организацию не нашёл бы её.
    assert [org.id for org in await orgs.orgs_of(session, user.id)] == [DEFAULT_ORG_ID]


async def test_email_user_with_membership_gets_employee_in_the_right_org(session) -> None:
    _first, second = await _orgs(session)
    user = await accounts.register(session, email=EMAIL, password=PASSWORD)
    await orgs.ensure_member(session, org_id=second.id, user_id=user.id)
    set_org(second.id)

    employee = await anext(deps.current_employee(session, user, None))
    assert employee.org_id == second.id
    assert employee.user_id == user.id


async def test_reset_link_points_to_the_public_app(monkeypatch) -> None:
    monkeypatch.setattr(
        accounts,
        "get_settings",
        lambda: SimpleNamespace(link_base="https://app.example.com"),
    )
    assert (
        accounts.reset_link("token-123")
        == "https://app.example.com/reset?token=token-123"
    )
