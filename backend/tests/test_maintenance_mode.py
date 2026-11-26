"""Недоступная база не убивает контейнер: старт, `/readyz`, API и вебхук бота.

Контекст (19–26.11.2026). У Neon кончилась квота, compute остановился.
`python -m app.db.migrate` упал на подключении, CMD с `&&` не пустил uvicorn,
Amvera показала `RUN_PROBLEM`, и 503 отдавали все пути — включая вебхук
Telegram, который из-за этого копил апдейты. Здесь три вещи, которые обязаны
работать без базы:

* процесс поднимается, `/healthz` — 200, `/readyz` — 503 с причиной;
* любая ручка API отвечает 503 `service_maintenance`, а не 500;
* вебхук бота отвечает Telegram `ok` и говорит человеку «на обслуживании».

Тест изолирован: вместо настоящей базы — движок на заведомо закрытый порт,
никакой сети до Postgres не нужно.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://semitaskbot.pages.dev")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.test_maintenance.db")

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app import main as app_main  # noqa: E402
from app.bot import webhook as webhook_mod  # noqa: E402
from app.db import base as db_base  # noqa: E402

# Порт 9 (discard) на loopback не слушает никто: отказ мгновенный и не зависит
# от внешней сети.
DEAD_DSN = "postgresql+asyncpg://user:pass@127.0.0.1:9/nodb?ssl=disable"


@pytest.fixture()
def dead_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Подменить движок на недоступную базу и вернуть всё назад."""
    engine = create_async_engine(DEAD_DSN, poolclass=NullPool)
    monkeypatch.setattr(db_base, "_engine", engine)
    monkeypatch.setattr(
        db_base,
        "_sessionmaker",
        async_sessionmaker(engine, expire_on_commit=False),
    )
    yield
    engine.sync_engine.dispose()


def test_app_starts_without_db_and_reports_maintenance(
    dead_db: None,  # noqa: ARG001 - фикстура ради побочного эффекта
) -> None:
    """Lifespan переживает мёртвую базу, а не падает вместе с контейнером."""
    app = app_main.create_app()

    @app.get("/api/__maintenance_probe")
    async def _probe() -> dict[str, int]:
        """Ручка, которой нужна только база — как любая реальная."""
        from sqlalchemy import text

        from app.db.base import get_sessionmaker

        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        return {"ok": 1}

    with TestClient(app, raise_server_exceptions=False) as client:
        # Живость процесса — без базы.
        assert client.get("/healthz").status_code == 200

        ready = client.get("/readyz")
        assert ready.status_code == 503
        body = ready.json()
        assert body["status"] == "degraded"
        assert body["detail"] == app_main.MAINTENANCE_DETAIL
        assert body["message"] == app_main.MAINTENANCE_TEXT
        # Причина названа и это тип ошибки, а не DSN с паролем.
        assert body["reason"]
        assert "postgresql" not in ready.text
        assert ready.headers["retry-after"] == "60"

        # Любая ручка API — не 500, а понятное «на обслуживании».
        api = client.get("/api/__maintenance_probe")
        assert api.status_code == 503
        assert api.json()["detail"] == app_main.MAINTENANCE_DETAIL
        assert "обслуживании" in api.json()["message"]


def test_migrations_tolerate_unreachable_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--tolerate-db-down` — контейнер стартует, миграции догонятся фоном."""
    from types import SimpleNamespace

    from app import config as app_config
    from app.db import migrate

    monkeypatch.setattr(
        app_config, "get_settings", lambda: SimpleNamespace(database_url=DEAD_DSN)
    )
    # Без флага поведение прежнее: ошибка подключения не проглатывается.
    with pytest.raises(OSError):
        migrate.main([])
    # С флагом — код 0, чтобы `sh -c` пошёл дальше к uvicorn.
    assert migrate.main(["--tolerate-db-down"]) == 0


def test_bot_webhook_says_maintenance_instead_of_503(
    dead_db: None,  # noqa: ARG001 - фикстура ради побочного эффекта
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telegram получает `ok`, человек — фразу; очередь апдейтов не растёт."""
    sent: dict[str, object] = {}

    class FakeBot:
        async def send_message(self, chat_id: int, text: str, **_: object) -> None:
            sent["chat_id"] = chat_id
            sent["text"] = text

        async def answer_callback_query(self, *_: object, **__: object) -> None:
            sent["callback"] = True

    monkeypatch.setattr(webhook_mod, "bot_for_org", lambda *_: FakeBot())

    payload = {
        "update_id": 778899,
        "message": {
            "message_id": 1,
            "date": 1_700_000_000,
            "chat": {"id": 42, "type": "private"},
            "text": "/start",
        },
    }
    client = TestClient(app_main.create_app(), raise_server_exceptions=False)
    res = client.post(
        "/tg/webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
    )

    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert sent["chat_id"] == 42
    assert "обслуживании" in str(sent["text"])
