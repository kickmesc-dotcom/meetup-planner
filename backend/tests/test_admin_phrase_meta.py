"""J.1: админ-ручки метаданных фраз (`/admin/phrases/meta*`).

Без поднятия FastAPI/БД: ручки вызываются напрямую с фейк-сессией (паттерн
`test_admin_jobs`) и подменённым `get_settings` (админ-проверка не должна зависеть
от env тестового окружения).

Покрываем контракт, на который опирается фронт-редактор:
- GET отдаёт `{phrase, source, hidden}` в порядке пула, дефолт — `manual/false`;
- POST точечно скрывает/возвращает фразу, ставит и снимает тег `ai`;
- bulk скрывает пачкой (это кнопка «🚫 Скрыть весь ИИ»);
- неизвестный пул → 422 (иначе опечатка в имени пула тихо писала бы мусор).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import routes_admin as ra
from app.services import admin_config as ac
from app.services.phrase_meta import SOURCE_AI, is_hidden, load_meta, source_of


class _FakeRow:
    def __init__(self, key: str, value: str) -> None:
        self.key = key
        self.value = value


class _FakeSession:
    def __init__(self) -> None:
        self._store: dict[str, _FakeRow] = {}

    async def get(self, model, key):  # noqa: ANN001
        return self._store.get(key)

    def add(self, row) -> None:  # noqa: ANN001
        self._store[row.key] = row

    async def commit(self) -> None:
        pass


@pytest.fixture
def session(monkeypatch):
    s = _FakeSession()
    monkeypatch.setattr(ac, "AdminConfig", _FakeRow)
    return s


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(ra, "get_settings", lambda: SimpleNamespace(admin_tg_id_set={777}))
    user = MagicMock()
    user.telegram_id = 777
    user.id = 42
    return user


@pytest.mark.asyncio
async def test_get_meta_defaults_to_manual_visible(session, admin):
    out = await ra.admin_get_phrase_meta("loser_reasons", session, admin)
    assert out.pool == "loser_reasons"
    assert out.items, "пул не должен быть пустым (дефолты из кода)"
    assert all(i.source == "manual" and i.hidden is False for i in out.items)


@pytest.mark.asyncio
async def test_get_meta_unknown_pool_rejected(session, admin):
    with pytest.raises(HTTPException) as ei:
        await ra.admin_get_phrase_meta("нет-такого-пула", session, admin)
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_hide_then_unhide_roundtrip(session, admin):
    phrases = await ra._get_pool_phrases(session, "advice")
    target = phrases[0]

    out = await ra.admin_set_phrase_meta(
        ra.PhraseMetaUpdate(pool="advice", phrase=target, hidden=True), session, admin
    )
    assert out.hidden is True
    assert is_hidden(await load_meta(session), "advice", target) is True

    out = await ra.admin_set_phrase_meta(
        ra.PhraseMetaUpdate(pool="advice", phrase=target, hidden=False), session, admin
    )
    assert out.hidden is False


@pytest.mark.asyncio
async def test_tag_and_untag_ai_source(session, admin):
    target = (await ra._get_pool_phrases(session, "advice"))[1]

    out = await ra.admin_set_phrase_meta(
        ra.PhraseMetaUpdate(pool="advice", phrase=target, source=SOURCE_AI),
        session,
        admin,
    )
    assert out.source == SOURCE_AI
    assert source_of(await load_meta(session), "advice", target) == SOURCE_AI

    # Обратно в «моё» — запись становится дефолтной и удаляется (мета компактна).
    out = await ra.admin_set_phrase_meta(
        ra.PhraseMetaUpdate(pool="advice", phrase=target, source="manual"), session, admin
    )
    assert out.source == "manual"
    assert await load_meta(session) == {}


@pytest.mark.asyncio
async def test_bulk_hide_all_ai(session, admin):
    phrases = (await ra._get_pool_phrases(session, "advice"))[:3]
    out: dict[str, Any] = await ra.admin_bulk_phrase_meta(
        ra.PhraseMetaBulkUpdate(pool="advice", phrases=phrases, hidden=True),
        session,
        admin,
    )
    assert out["updated"] == 3
    meta = await load_meta(session)
    assert all(is_hidden(meta, "advice", p) for p in phrases)


@pytest.mark.asyncio
async def test_meta_isolated_between_pools(session, admin):
    loser = (await ra._get_pool_phrases(session, "loser_reasons"))[0]
    await ra.admin_set_phrase_meta(
        ra.PhraseMetaUpdate(pool="loser_reasons", phrase=loser, hidden=True),
        session,
        admin,
    )
    meta = await load_meta(session)
    # Та же строка в другом пуле остаётся видимой.
    assert is_hidden(meta, "chukhan_reasons", loser) is False
