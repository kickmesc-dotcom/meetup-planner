"""Редактируемые тексты приложения: каталог и хранение правок.

Заменяет прежний «снапшот фраз» (мемные пулы). Проверяем то, что важно
руководителю: правки не теряют дефолт, пустая строка возвращает исходник,
неизвестный код не просачивается в конфиг, а мусор в конфиге не ломает
интерфейс.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import AdminConfig  # noqa: E402
from app.services import app_texts  # noqa: E402


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: AdminConfig.__table__.create(c))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


def test_catalog_codes_are_unique_and_have_defaults() -> None:
    codes = [item.code for item in app_texts.CATALOG]
    assert len(codes) == len(set(codes))
    for item in app_texts.CATALOG:
        assert item.default.strip(), item.code
        assert item.group.strip(), item.code
        assert item.title.strip(), item.code


def test_defaults_cover_the_whole_catalog() -> None:
    assert app_texts.defaults() == {
        item.code: item.default for item in app_texts.CATALOG
    }


async def test_without_overrides_effective_is_defaults(session) -> None:
    assert await app_texts.overrides(session) == {}
    assert await app_texts.effective(session) == app_texts.defaults()


async def test_save_stores_trimmed_override_and_keeps_defaults(session) -> None:
    code = app_texts.CATALOG[0].code
    effective = await app_texts.save(session, {code: "  Своя формулировка  "})
    assert effective[code] == "Своя формулировка"
    # Не тронутые коды остаются на дефолтах — правка одной строки не стирает каталог.
    for item in app_texts.CATALOG[1:]:
        assert effective[item.code] == item.default
    assert (await app_texts.overrides(session)) == {code: "Своя формулировка"}


async def test_empty_value_returns_the_default(session) -> None:
    code = app_texts.CATALOG[0].code
    await app_texts.save(session, {code: "Своя формулировка"})
    effective = await app_texts.save(session, {code: "   "})
    assert effective[code] == app_texts.defaults()[code]
    assert await app_texts.overrides(session) == {}


async def test_partial_save_keeps_other_overrides(session) -> None:
    """Правка одной строки не стирает остальные — фронт присылает только изменённое."""
    first, second = app_texts.CATALOG[0].code, app_texts.CATALOG[1].code
    await app_texts.save(session, {first: "Первое"})
    effective = await app_texts.save(session, {second: "Второе"})
    assert effective[first] == "Первое"
    assert effective[second] == "Второе"


async def test_unknown_code_is_rejected_without_writing(session) -> None:
    with pytest.raises(app_texts.TextsError) as exc:
        await app_texts.save(session, {"nope.code": "текст"})
    assert "nope.code" in str(exc.value)
    assert await app_texts.overrides(session) == {}


async def test_too_long_text_is_rejected(session) -> None:
    code = app_texts.CATALOG[0].code
    with pytest.raises(app_texts.TextsError):
        await app_texts.save(session, {code: "я" * (app_texts.MAX_LEN + 1)})
    assert await app_texts.overrides(session) == {}


async def test_broken_config_does_not_break_the_catalog(session) -> None:
    session.add(AdminConfig(key=app_texts.STORAGE_KEY, value="{not json"))
    await session.commit()
    assert await app_texts.overrides(session) == {}
    assert await app_texts.effective(session) == app_texts.defaults()


async def test_unknown_values_in_config_are_ignored(session) -> None:
    stored = {
        "nope.code": "мусор",
        app_texts.CATALOG[0].code: "Своё",
        app_texts.CATALOG[1].code: "   ",
    }
    session.add(
        AdminConfig(
            key=app_texts.STORAGE_KEY, value=json.dumps(stored, ensure_ascii=False)
        )
    )
    await session.commit()
    assert await app_texts.overrides(session) == {app_texts.CATALOG[0].code: "Своё"}
