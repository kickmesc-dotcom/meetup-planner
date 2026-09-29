"""GHG10: граница «игра ↔ HTTP» — там, где награды ломали ответ API.

История бага (нашлась 29.09.2026 в боевых логах): `POST /api/availability`
отвечал 500 при тапе по свободному дню, но диапазон в базе СОЗДАВАЛСЯ — клетка
зеленела только после следующего рефетча. Цепочка была такая:

1. `xp.award` искал маркер окна как `session.get(XpGrant, (user_id, key))`,
   хотя у `XpGrant` суррогатный PK `id` → «Incorrect number of values in
   identifier to formulate primary key».
2. Исключение ловил `awards._guarded` и делал `session.rollback()`.
3. Rollback экспайрит ВСЕ объекты сессии — включая тот, который роут возвращает
   в `response_model`.
4. FastAPI сериализует ответ вне greenlet'а → `MissingGreenlet` → 500.

Тесты подменяли сессию слишком добрым фейком (он принимал любой ключ и отвечал
на поиск маркера из очереди), поэтому 781 зелёный тест этот баг пропустил.
Здесь проверяются все четыре звена — и строгость фейка в том числе.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.api.deps import resync_if_expired
from app.db.models import XpGrant
from app.services.game import xp
from tests.game_fakes import assert_single_column_pk_get, grant_lookup

# --------------------------------------------------------------------------
# 1. Модель: у XpGrant действительно суррогатный PK
# --------------------------------------------------------------------------


def test_xp_grant_has_surrogate_pk_not_composite():
    """Если однажды у `XpGrant` появится составной PK, этот тест скажет об этом
    прямо, а не через 500 в бою."""
    from sqlalchemy import inspect as sa_inspect

    assert [c.key for c in sa_inspect(XpGrant).mapper.primary_key] == ["id"]


def test_fake_session_rejects_tuple_key_for_single_column_pk():
    """Строгость стенда: именно этой проверки не хватало, чтобы поймать баг."""
    from app.db.models import XpDaily

    with pytest.raises(AssertionError, match="Incorrect number of values"):
        assert_single_column_pk_get(XpGrant, (5, "availability:2026-W39"))
    # Настоящий PK проходит молча.
    assert_single_column_pk_get(XpGrant, 5)
    # Составной PK (у `xp_daily` это (user_id, day, event)) требует полный кортеж.
    assert_single_column_pk_get(XpDaily, (5, date(2026, 9, 29), "message"))
    with pytest.raises(AssertionError, match="ожидался кортеж"):
        assert_single_column_pk_get(XpDaily, 5)


# --------------------------------------------------------------------------
# 2. Поиск маркера окна отвечается по store (как база по уникальному индексу)
# --------------------------------------------------------------------------


class _StoreSession:
    """Мини-стенд: только то, что нужно `grant_exists`."""

    def __init__(self, store: dict[tuple, object]) -> None:
        self.store = store

    async def scalar(self, stmt, *_a, **_k):  # noqa: ANN001, ANN002
        handled, value = grant_lookup(stmt, self.store)
        assert handled, "запрос должен быть про xp_grants — иначе тест бессмыслен"
        return value


@pytest.mark.asyncio
async def test_grant_exists_hits_unique_index_not_primary_key():
    """Маркер ищется по паре (user_id, idem_key), а не по `id`."""
    empty = _StoreSession({})
    assert await xp.grant_exists(empty, 5, "availability:2026-W39") is None

    filled = _StoreSession(
        {
            ("XpGrant", (5, "availability:2026-W39")): XpGrant(
                user_id=5, idem_key="availability:2026-W39"
            )
        }
    )
    assert await xp.grant_exists(filled, 5, "availability:2026-W39") is not None
    # Чужой ключ (другая неделя, другой юзер) не считается найденным.
    assert await xp.grant_exists(filled, 5, "availability:2026-W40") is None
    assert await xp.grant_exists(filled, 6, "availability:2026-W39") is None


# --------------------------------------------------------------------------
# 3. Граница роута: экспайренный объект обязательно перечитывается
# --------------------------------------------------------------------------


class _State:
    def __init__(self, expired: bool) -> None:
        self.expired = expired


class _ResyncSession:
    def __init__(self) -> None:
        self.refreshed: list[object] = []

    async def refresh(self, obj) -> None:  # noqa: ANN001
        self.refreshed.append(obj)


def _state_of(states: dict[int, bool]):
    """Подмена `sa_inspect` в `app.api.deps`: реальный ORM-объект не может быть
    «экспайрен» без живой сессии, а проверить надо именно реакцию на флаг."""

    return lambda obj: _State(states[id(obj)])   # noqa: ARG005


@pytest.mark.asyncio
async def test_resync_refreshes_only_expired_objects(monkeypatch):
    from app.api import deps

    expired, alive = object(), object()
    monkeypatch.setattr(deps, "sa_inspect", _state_of({id(expired): True, id(alive): False}))

    session = _ResyncSession()
    await resync_if_expired(session, expired, alive, None)
    assert session.refreshed == [expired], "перечитываем только экспайренные и не падаем на None"


@pytest.mark.asyncio
async def test_award_calendar_resyncs_row_after_awards(monkeypatch):
    """`_award_calendar` — это и есть контракт «награда не ломает ответ»."""
    from types import SimpleNamespace

    from app.api import deps, routes_availability

    calls: list[int] = []

    async def _availability(session, user_id):  # noqa: ANN001, ANN202
        calls.append(user_id)

    # Подменяем атрибут ПАКЕТА: роут делает `from app.services.game import
    # awards`, и это резолвится через атрибут пакета, а не через sys.modules.
    monkeypatch.setattr("app.services.game.awards", SimpleNamespace(availability=_availability))

    row = object()
    monkeypatch.setattr(deps, "sa_inspect", _state_of({id(row): True}))
    session = _ResyncSession()

    await routes_availability._award_calendar(session, 5, row)

    assert calls == [5]
    assert session.refreshed == [row], "экспайренный диапазон должен быть перечитан"


@pytest.mark.asyncio
async def test_award_calendar_handles_missing_row_for_bulk(monkeypatch):
    """Bulk-роут возвращает id, а не объект — перечитывать нечего."""
    from types import SimpleNamespace

    from app.api import routes_availability

    async def _availability(session, user_id):  # noqa: ANN001, ANN202
        return None

    monkeypatch.setattr("app.services.game.awards", SimpleNamespace(availability=_availability))

    session = _ResyncSession()
    await routes_availability._award_calendar(session, 5)
    assert session.refreshed == []
