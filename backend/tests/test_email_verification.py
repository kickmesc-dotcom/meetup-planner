"""Подтверждение адреса почты (B2B_PLATFORM_PLAN, шаг 2.1).

Проверяем свойства, без которых подтверждение бесполезно:

* в базе только хеш ссылки — утечка дампа не даёт подтвердить чужой адрес;
* ссылка одноразовая, но повторный клик по уже сработавшей — не ошибка;
* просроченная и выдуманная ссылки различимы для человека, но не для чужих;
* письма не превращаются в спам: не больше трёх в час, и ни одного, если
  адрес уже подтверждён;
* после подтверждения гасятся остальные живые ссылки.
"""

from __future__ import annotations

import os
from datetime import timedelta

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.auth_models import EmailVerification  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.services import accounts  # noqa: E402

TABLES = ("users", "email_verifications")

PASSWORD = "correct-horse-battery"
EMAIL = "worker@example.com"


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


async def _user(session, *, email: str | None = EMAIL):
    if email:
        return await accounts.register(
            session, email=email, password=PASSWORD, display_name="Сотрудник"
        )
    from app.db.models import User

    user = User(
        telegram_id=900001,
        display_name="Из Telegram",
        color_hex="#336699",
        timezone="Europe/Moscow",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def test_request_stores_only_hash_and_returns_link(session) -> None:
    user = await _user(session)
    token = await accounts.request_email_verification(session, user)
    assert token

    rows = (await session.scalars(select(EmailVerification))).all()
    assert len(rows) == 1
    assert rows[0].token_hash == accounts.token_hash(token)
    assert token not in rows[0].token_hash
    assert rows[0].used_at is None
    assert "/verify?token=" in accounts.verify_link(token)
    assert user.email_verified is False


async def test_confirm_marks_email_and_is_idempotent(session) -> None:
    user = await _user(session)
    token = await accounts.request_email_verification(session, user)
    assert token

    confirmed = await accounts.confirm_email(session, token)
    assert confirmed.email_verified_at is not None
    assert confirmed.email_verified is True

    # Второй клик по тому же письму: адрес уже подтверждён — это успех.
    again = await accounts.confirm_email(session, token)
    assert again.id == user.id
    assert again.email_verified is True


async def test_bad_and_expired_tokens_are_rejected(session) -> None:
    user = await _user(session)
    with pytest.raises(accounts.AccountsError, match="verify_invalid"):
        await accounts.confirm_email(session, "не-токен")

    token = await accounts.request_email_verification(session, user)
    assert token
    row = await session.scalar(
        select(EmailVerification).where(
            EmailVerification.token_hash == accounts.token_hash(token)
        )
    )
    assert row is not None
    row.expires_at = accounts._now() - timedelta(minutes=1)
    await session.commit()

    with pytest.raises(accounts.AccountsError, match="verify_expired"):
        await accounts.confirm_email(session, token)


async def test_no_request_when_verified_or_without_email(session, monkeypatch) -> None:
    verified = await _user(session)
    verified.email_verified_at = accounts._now()
    await session.commit()
    assert await accounts.request_email_verification(session, verified) is None

    telegram_only = await _user(session, email=None)
    assert await accounts.request_email_verification(session, telegram_only) is None


async def test_rate_limit_three_per_hour(session) -> None:
    user = await _user(session)
    tokens = [
        await accounts.request_email_verification(session, user) for _ in range(3)
    ]
    assert all(tokens)
    assert await accounts.request_email_verification(session, user) is None


async def test_confirm_revokes_other_live_links(session) -> None:
    user = await _user(session)
    first = await accounts.request_email_verification(session, user)
    second = await accounts.request_email_verification(session, user)
    assert first and second

    await accounts.confirm_email(session, first)
    rows = (await session.scalars(select(EmailVerification))).all()
    assert all(row.used_at is not None for row in rows)
    # Старая ссылка больше не подтверждает (но адрес уже подтверждён).
    again = await accounts.confirm_email(session, second)
    assert again.email_verified is True
