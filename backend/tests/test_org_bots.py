"""Свой бот у организации (B2B_PLATFORM_PLAN, шаг 1.6).

Что проверяем и почему именно это:

1. **Откат на env.** Организация без своего токена обязана работать на общем
   боте: иначе миграция сломала бы текущий контур.
2. **Свой бот и чат.** Токен, чат и секрет вебхука берутся из строки
   организации, а не из процесса.
3. **Резолв по секрету.** Входящий апдейт находит организацию по заголовку
   Telegram: тело ещё не разобрано, доверять в нём нечему.
4. **Контекст обработки.** Пока идёт апдейт, все запросы видят данные этой
   организации (иначе второй клиент читал бы первый).
5. **`initData` второго бота.** Подпись мини-аппа считается от токена
   конкретного бота — при одном env-токене сотрудник второго клиента получал
   бы 401.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from types import SimpleNamespace
from urllib.parse import urlencode

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.bot import dispatcher as dispatcher_module  # noqa: E402
from app.bot import webhook as webhook_module  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.org_models import (  # noqa: E402
    DEFAULT_ORG_ID,
    Organization,
    current_org_id,
    reset_org,
    set_org,
)
from app.services import org_bots  # noqa: E402

ENV_TOKEN = "100:env-token"
ENV_CHAT = -1001
ENV_SECRET = "env-secret"


@pytest.fixture(autouse=True)
def isolated_env_defaults(monkeypatch):
    """Не зависим от реального `.env` оператора: env-бот задан тестом."""
    monkeypatch.setattr(org_bots, "_env_defaults", lambda: (ENV_TOKEN, ENV_CHAT))
    monkeypatch.setattr(org_bots, "_env_webhook_secret", lambda: ENV_SECRET)
    org_bots.reset()
    dispatcher_module.reset_bots()
    yield
    org_bots.reset()
    dispatcher_module.reset_bots()


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    tables = [
        Base.metadata.tables[name]
        for name in ("organizations", "users", "employees")
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


async def _two_orgs(session) -> None:
    session.add(
        Organization(id=DEFAULT_ORG_ID, slug="default", name="Моя организация")
    )
    session.add(
        Organization(
            id=2,
            slug="salon",
            name="Салон",
            bot_token="200:salon-token",
            bot_username="salon_bot",
            webhook_secret="salon-secret",
            group_chat_id=-2002,
        )
    )
    await session.commit()


async def test_org_without_own_bot_uses_env(session) -> None:
    await _two_orgs(session)
    await org_bots.reload(session)

    default = org_bots.config(DEFAULT_ORG_ID)
    assert default is not None
    assert default.token == ENV_TOKEN
    assert default.chat_id == ENV_CHAT
    assert default.webhook_secret == ENV_SECRET

    # У третьей организации бота нет вовсе: токен и чат — общие, отдельный
    # вебхук ей не нужен.
    session.add(Organization(id=3, slug="store", name="Магазин"))
    await session.commit()
    await org_bots.reload(session)

    plain = org_bots.config(3)
    assert plain is not None and not plain.own_bot
    assert org_bots.token_for(3) == ENV_TOKEN
    assert org_bots.chat_id_for(3) == ENV_CHAT


async def test_own_bot_chat_and_secret_win(session) -> None:
    await _two_orgs(session)
    await org_bots.reload(session)

    assert org_bots.token_for(2) == "200:salon-token"
    assert org_bots.chat_id_for(2) == -2002
    assert org_bots.org_for_token("200:salon-token") == 2
    assert org_bots.org_for_webhook_secret("salon-secret") == 2
    assert org_bots.org_for_webhook_secret("nope") is None
    # Организации со своим ботом получают отдельный вебхук.
    assert [cfg.org_id for cfg in org_bots.orgs_with_own_bot()] == [2]


async def test_chat_id_follows_the_current_org(session) -> None:
    await _two_orgs(session)
    await org_bots.reload(session)

    from app.config import get_settings

    settings = get_settings()
    # Чат — свойство текущего контекста, а не процесса: один и тот же объект
    # настроек отдаёт разные чаты.
    assert settings.group_chat_id == ENV_CHAT
    token = set_org(2)
    try:
        assert settings.group_chat_id == -2002
    finally:
        reset_org(token)
    assert settings.group_chat_id == ENV_CHAT


async def test_token_candidates_cover_every_bot_without_duplicates(session) -> None:
    await _two_orgs(session)
    await org_bots.reload(session)

    tokens = org_bots.token_candidates()
    assert tokens[0] == ENV_TOKEN
    assert "200:salon-token" in tokens
    assert len(tokens) == len(set(tokens))


async def test_webhook_secret_resolution(session) -> None:
    await _two_orgs(session)
    await org_bots.reload(session)

    assert await webhook_module.resolve_org(session, ENV_SECRET) == DEFAULT_ORG_ID
    assert await webhook_module.resolve_org(session, "salon-secret") == 2
    with pytest.raises(HTTPException) as bad:
        await webhook_module.resolve_org(session, "чужой")
    assert bad.value.status_code == 403


async def test_webhook_feeds_update_inside_the_org_context(session, monkeypatch) -> None:
    await _two_orgs(session)
    await org_bots.reload(session)

    seen: dict[str, object] = {}

    class _FakeDispatcher:
        async def feed_update(self, bot, update) -> None:  # noqa: ANN001
            seen["bot"] = bot
            seen["org"] = current_org_id.get()
            seen["update_id"] = update.update_id

    class _FakeUpdate:
        @staticmethod
        def model_validate(payload):  # noqa: ANN001, ANN205
            return SimpleNamespace(update_id=payload["update_id"])

    class _FakeRequest:
        async def json(self):  # noqa: ANN201
            return {"update_id": 7}

    monkeypatch.setattr(webhook_module, "get_dispatcher", lambda: _FakeDispatcher())
    monkeypatch.setattr(webhook_module, "Update", _FakeUpdate)
    monkeypatch.setattr(webhook_module, "bot_for_org", lambda org_id: f"bot-{org_id}")

    result = await webhook_module.tg_webhook(
        _FakeRequest(), session, "salon-secret"
    )

    assert result == {"ok": True}
    assert seen == {"bot": "bot-2", "org": 2, "update_id": 7}
    # После обработки контекст вернулся — иначе следующий запрос в этой же
    # задаче увидел бы чужую организацию.
    assert current_org_id.get() == DEFAULT_ORG_ID


async def test_get_bot_is_per_org(monkeypatch) -> None:
    monkeypatch.setattr(
        org_bots,
        "token_for",
        lambda org_id: f"{org_id}00:token-of-{org_id}",
    )

    token = set_org(2)
    try:
        first = dispatcher_module.get_bot()
        assert first is dispatcher_module.get_bot()  # кеш на организацию
    finally:
        reset_org(token)

    assert dispatcher_module.get_bot() is not first
    assert dispatcher_module.all_bots() == [first, dispatcher_module.get_bot()]


def _sign(params: dict[str, str], token: str) -> str:
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def _init_data(user_id: int, token: str) -> str:
    params = {
        "auth_date": str(int(time.time())),
        "query_id": "qid",
        "user": json.dumps(
            {"id": user_id, "first_name": "Новый"}, separators=(",", ":")
        ),
    }
    params["hash"] = _sign(params, token)
    return urlencode(params)


async def test_initdata_signed_by_org_bot_sets_the_org(session) -> None:
    """Сотрудник второго клиента открыл мини-апп через бота второго клиента."""
    await _two_orgs(session)
    await org_bots.reload(session)

    from app.api import deps
    from app.db.models import User

    # sqlite не автоинкрементит BIGINT-первичник: заводим личность явно.
    session.add(
        User(
            id=1,
            telegram_id=777001,
            display_name="Новый",
            color_hex="#336699",
            timezone="Europe/Moscow",
        )
    )
    await session.commit()

    settings = SimpleNamespace(
        bot_token=ENV_TOKEN,
        initdata_max_age_seconds=86400,
    )
    user = await deps.current_user(
        session, settings, f"tma {_init_data(777001, '200:salon-token')}", None
    )

    assert user.telegram_id == 777001
    assert current_org_id.get() == 2
    reset_org(set_org(DEFAULT_ORG_ID))

    with pytest.raises(HTTPException) as bad:
        await deps.current_user(
            session, settings, f"tma {_init_data(777002, '999:чужой-бот')}", None
        )
    assert bad.value.status_code == 401


async def test_set_bot_validates_and_switches_the_org(session) -> None:
    """Подключение своего бота: проверки и мгновенное обновление реестра."""
    await _two_orgs(session)
    session.add(Organization(id=3, slug="store", name="Магазин"))
    await session.commit()
    await org_bots.reload(session)

    from app.services import orgs

    with pytest.raises(orgs.OrgsError, match="bad_token"):
        await orgs.set_bot(session, 3, token="не-токен", webhook_secret="s3")
    with pytest.raises(orgs.OrgsError, match="bot_needs_secret"):
        await orgs.set_bot(session, 3, token="300:store-token-000", webhook_secret="")
    with pytest.raises(orgs.OrgsError, match="token_taken"):
        await orgs.set_bot(
            session, 3, token="200:salon-token", webhook_secret="fresh-secret"
        )
    with pytest.raises(orgs.OrgsError, match="secret_taken"):
        await orgs.set_bot(
            session, 3, token="300:store-token-000", webhook_secret="salon-secret"
        )

    org = await orgs.set_bot(
        session,
        3,
        token="300:store-token-000",
        username="store_bot",
        webhook_secret="store-secret",
        chat_id=-3003,
    )
    assert org.bot_username == "store_bot"
    # Реестр обновился сразу: без перезапуска бот уже знает свой чат.
    assert org_bots.token_for(3) == "300:store-token-000"
    assert org_bots.chat_id_for(3) == -3003
    assert org_bots.org_for_webhook_secret("store-secret") == 3

    # Пустой токен возвращает организацию на общий бот из env.
    cleared = await orgs.set_bot(session, 3, token=None)
    assert cleared.bot_token is None and cleared.webhook_secret is None
    assert not org_bots.config(3).own_bot
    assert org_bots.token_for(3) == ENV_TOKEN
