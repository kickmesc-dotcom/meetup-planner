"""GHG10 Э5.5 (админский экран игры) и роут доната Э11.

Админские ручки проверяем на трёх вещах, которые легко сломать незаметно:
правах (рубильник обязан быть админским), пересборке job'ов после переключения
(иначе выключение оставляет игровые job'ы тикать) и кодах отказа доната.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import routes_admin, routes_game
from app.db.models import GameProfile
from app.services.game import awards, donations


class _Rows:
    def __init__(self, rows=None, rowcount: int = 1) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def all(self):
        return list(self._rows)


class _FakeSession:
    """Мини-сессия: store для get/add + очереди ответов."""

    def __init__(self, *, scalar=None, scalar_one=None) -> None:
        self.store: dict = {}
        self.added: list = []
        self.commits = 0
        self.executed: list = []
        self._scalar = list(scalar or [])
        self._scalar_one = scalar_one

    async def get(self, model, key):
        return self.store.get((model.__name__, key))

    def add(self, row) -> None:
        self.added.append(row)
        self.store[(type(row).__name__, getattr(row, "user_id", None))] = row

    async def scalar(self, *_a, **_k):
        return self._scalar.pop(0) if self._scalar else None

    async def execute(self, stmt, *_a, **_k):
        self.executed.append(stmt)
        return _Rows(rowcount=self._scalar_one or 1)

    async def commit(self) -> None:
        self.commits += 1


def _admin(telegram_id: int = 777) -> SimpleNamespace:
    return SimpleNamespace(id=1, telegram_id=telegram_id, display_name="Серж-NEO")


@pytest.fixture
def as_admin(monkeypatch):
    monkeypatch.setattr(
        routes_admin, "get_settings", lambda: SimpleNamespace(admin_tg_id_set={777})
    )


@pytest.fixture
def game_config(monkeypatch):
    """Подменяем чтение/запись конфига игры — БД в тестах нет."""
    state = {"enabled": True, "debug": [1, 2], "set": []}

    async def _get_enabled(_session):
        return state["enabled"]

    async def _set_enabled(_session, value):
        state["enabled"] = value
        state["set"].append(("enabled", value))

    async def _get_debug(_session):
        return list(state["debug"])

    async def _set_debug(_session, ids):
        state["debug"] = list(ids)
        state["set"].append(("debug", list(ids)))

    monkeypatch.setattr(
        "app.services.admin_config.get_game_enabled", _get_enabled
    )
    monkeypatch.setattr(
        "app.services.admin_config.set_game_enabled", _set_enabled
    )
    monkeypatch.setattr(
        "app.services.admin_config.get_game_debug_tg_ids", _get_debug
    )
    monkeypatch.setattr(
        "app.services.admin_config.set_game_debug_tg_ids", _set_debug
    )
    return state


# --- права -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_game_get_rejects_non_admin(monkeypatch):
    monkeypatch.setattr(
        routes_admin, "get_settings", lambda: SimpleNamespace(admin_tg_id_set={1})
    )
    with pytest.raises(HTTPException) as exc:
        await routes_admin.admin_game_get(_FakeSession(), _admin())
    assert exc.value.status_code == 403


# --- чтение и переключение ---------------------------------------------------

@pytest.mark.asyncio
async def test_admin_game_get_returns_state(as_admin, game_config):
    session = _FakeSession(scalar=[4])
    out = await routes_admin.admin_game_get(session, _admin())
    assert out.enabled is True
    assert out.debug_tg_ids == [1, 2]
    assert out.players == 4
    assert out.achievements_total > 0


@pytest.mark.asyncio
async def test_admin_game_toggle_rewrites_jobs(as_admin, game_config, monkeypatch):
    calls: list[str] = []

    async def _reload(_bot):
        calls.append("reload")

    monkeypatch.setattr(routes_admin, "reload_dynamic_jobs", _reload)
    monkeypatch.setattr(
        "app.bot.dispatcher.get_bot", lambda: SimpleNamespace()
    )
    body = routes_admin.GameToggleIn(enabled=False)
    out = await routes_admin.admin_game_put(body, _FakeSession(scalar=[0]), _admin())
    assert out.enabled is False
    assert ("enabled", False) in game_config["set"]
    # Без пересборки job'ы остались бы зарегистрированными до рестарта Space.
    assert calls == ["reload"]


@pytest.mark.asyncio
async def test_admin_game_toggle_keeps_debug_ids_when_omitted(
    as_admin, game_config, monkeypatch
):
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(routes_admin, "reload_dynamic_jobs", _noop)
    monkeypatch.setattr("app.bot.dispatcher.get_bot", lambda: SimpleNamespace())
    await routes_admin.admin_game_put(
        routes_admin.GameToggleIn(enabled=True), _FakeSession(scalar=[0]), _admin()
    )
    # Список отладчиков не трогали — он не должен затереться пустым.
    assert game_config["debug"] == [1, 2]


# --- отладочные действия -----------------------------------------------------

@pytest.mark.asyncio
async def test_grant_rejects_unknown_code(as_admin):
    body = routes_admin.GameGrantIn(telegram_id=777, code="нет-такой")
    with pytest.raises(HTTPException) as exc:
        await routes_admin.admin_game_grant(body, _FakeSession(), _admin())
    assert exc.value.status_code == 400
    assert exc.value.detail == "unknown_achievement"


@pytest.mark.asyncio
async def test_grant_passes_code_to_facade(as_admin, monkeypatch):
    granted: list[tuple] = []
    card = routes_admin.GamePlayerOut(
        telegram_id=5, name="Митян", xp=0, level=1, rank_name="Подшконарь",
        prestige=0, achievements=[], counters={},
    )

    async def _achievement(_session, user_id, code):
        granted.append((user_id, code))

    async def _player(*_a, **_k):
        return SimpleNamespace(id=5, telegram_id=5, display_name="Митян")

    async def _out(*_a, **_k):
        return card

    monkeypatch.setattr(awards, "achievement", _achievement)
    monkeypatch.setattr(routes_admin, "_game_player", _player)
    monkeypatch.setattr(routes_admin, "_game_player_out", _out)
    out = await routes_admin.admin_game_grant(
        routes_admin.GameGrantIn(telegram_id=5, code="chin_up"),
        _FakeSession(),
        _admin(),
    )
    assert granted == [(5, "chin_up")]
    assert out is card


@pytest.mark.asyncio
async def test_reset_deletes_achievements(as_admin, monkeypatch):
    card = routes_admin.GamePlayerOut(
        telegram_id=5, name="Митян", xp=0, level=1, rank_name="Подшконарь",
        prestige=0, achievements=[], counters={},
    )

    async def _player(*_a, **_k):
        return SimpleNamespace(id=5, telegram_id=5, display_name="Митян")

    async def _out(*_a, **_k):
        return card

    monkeypatch.setattr(routes_admin, "_game_player", _player)
    monkeypatch.setattr(routes_admin, "_game_player_out", _out)
    session = _FakeSession(scalar_one=3)
    out = await routes_admin.admin_game_reset(
        routes_admin.GameResetIn(telegram_id=5, counters=True), session, _admin()
    )
    assert out is card
    # Две выборки: сами ачивки и накопители (иначе «Опиум» вернётся сразу).
    assert len(session.executed) == 2
    assert session.commits == 1


@pytest.mark.asyncio
async def test_set_xp_creates_profile_if_absent(as_admin, monkeypatch):
    card = routes_admin.GamePlayerOut(
        telegram_id=5, name="Митян", xp=800, level=9, rank_name="Пахан",
        prestige=0, achievements=[], counters={},
    )

    async def _player(*_a, **_k):
        return SimpleNamespace(id=5, telegram_id=5, display_name="Митян")

    async def _out(*_a, **_k):
        return card

    monkeypatch.setattr(routes_admin, "_game_player", _player)
    monkeypatch.setattr(routes_admin, "_game_player_out", _out)
    session = _FakeSession()
    await routes_admin.admin_game_set_xp(
        routes_admin.GameXpIn(telegram_id=5, xp_total=800), session, _admin()
    )
    assert [type(row).__name__ for row in session.added] == ["GameProfile"]
    assert session.added[0].xp == 800


@pytest.mark.asyncio
async def test_set_xp_overwrites_existing_profile(as_admin, monkeypatch):
    async def _player(*_a, **_k):
        return SimpleNamespace(id=5, telegram_id=5, display_name="Митян")

    async def _out(*_a, **_k):
        return None

    monkeypatch.setattr(routes_admin, "_game_player", _player)
    monkeypatch.setattr(routes_admin, "_game_player_out", _out)
    session = _FakeSession()
    session.store[("GameProfile", 5)] = GameProfile(user_id=5, xp=100)
    await routes_admin.admin_game_set_xp(
        routes_admin.GameXpIn(telegram_id=5, xp_total=900), session, _admin()
    )
    profile = session.store[("GameProfile", 5)]
    assert profile.xp == 900
    # Ручная правка не подсовывает игроку окно «ты поднял ранг».
    assert profile.pending_level_up_from is None


# --- роут доната -------------------------------------------------------------

def _game_flag(monkeypatch, enabled: bool) -> None:
    async def _flag(_session):
        return enabled

    monkeypatch.setattr(routes_game, "is_game_enabled", _flag)


@pytest.mark.asyncio
async def test_donate_blocked_when_game_disabled(monkeypatch):
    _game_flag(monkeypatch, False)
    with pytest.raises(HTTPException) as exc:
        await routes_game.donate_xp(
            routes_game.DonationIn(telegram_id=5), _FakeSession(), _admin()
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_donate_unknown_recipient(monkeypatch):
    _game_flag(monkeypatch, True)
    with pytest.raises(HTTPException) as exc:
        await routes_game.donate_xp(
            routes_game.DonationIn(telegram_id=999), _FakeSession(), _admin()
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_donate_refusal_is_teased_in_chat(monkeypatch):
    _game_flag(monkeypatch, True)
    teased: list[tuple] = []

    async def _donate(*_a, **_k):
        return donations.DonationResult(code=donations.NOT_ENOUGH_XP, donor_xp=0)

    async def _tease(name, *, xp_now):
        teased.append((name, xp_now))

    monkeypatch.setattr(routes_game.donations, "donate", _donate)
    monkeypatch.setattr(routes_game, "_tease_in_chat", _tease)
    session = _FakeSession(scalar=[SimpleNamespace(id=5, display_name="Митян")])
    with pytest.raises(HTTPException) as exc:
        await routes_game.donate_xp(
            routes_game.DonationIn(telegram_id=5), session, _admin()
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == donations.NOT_ENOUGH_XP
    # Спека: попытку подарить то, чего нет, высмеиваем в чат.
    assert teased == [("Серж-NEO", 0)]


@pytest.mark.asyncio
async def test_donate_success_returns_balances(monkeypatch):
    _game_flag(monkeypatch, True)

    async def _donate(*_a, **_k):
        return donations.DonationResult(
            code=donations.OK, ok=True, amount=100, donor_xp=400, recipient_xp=100
        )

    monkeypatch.setattr(routes_game.donations, "donate", _donate)
    session = _FakeSession(scalar=[SimpleNamespace(id=5, display_name="Митян")])
    out = await routes_game.donate_xp(
        routes_game.DonationIn(telegram_id=5), session, _admin()
    )
    assert out.ok is True
    assert out.amount == 100
    assert out.donor_xp == 400 and out.recipient_xp == 100
    assert out.recipient_name == "Митян"


@pytest.mark.asyncio
async def test_donate_already_donated_maps_to_409(monkeypatch):
    _game_flag(monkeypatch, True)

    async def _donate(*_a, **_k):
        return donations.DonationResult(code=donations.ALREADY_DONATED)

    monkeypatch.setattr(routes_game.donations, "donate", _donate)
    session = _FakeSession(scalar=[SimpleNamespace(id=5, display_name="Митян")])
    with pytest.raises(HTTPException) as exc:
        await routes_game.donate_xp(
            routes_game.DonationIn(telegram_id=5), session, _admin()
        )
    assert exc.value.status_code == 409
