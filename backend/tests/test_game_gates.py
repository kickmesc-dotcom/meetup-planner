"""GHG10 (этап 8): гейтинг по рангам.

Проверяем три правила `gates`: выключенная игра снимает гейт, «Серж нео»
обходит гейт, реальный ранг берётся из опыта. Плюс — API-обёртка отдаёт 403
`rank_required:<N>`, а правка «своего» в профиле гейтится по каждому полю.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import routes_game
from app.db.models import GameProfile
from app.schemas.game import GameCustomizePatch, GameProfileOut
from app.services.game import gates


class _Rows:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)


class _FakeSession:
    def __init__(self) -> None:
        self.store: dict[tuple, object] = {}
        self.added: list[object] = []
        self.commits = 0
        self.scalar_queue: list = []

    async def get(self, model, key):  # noqa: ANN001
        return self.store.get((model.__name__, key))

    def add(self, row) -> None:  # noqa: ANN001
        self.added.append(row)
        self.store[(type(row).__name__, getattr(row, "user_id", None))] = row

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def scalar(self, *_a, **_k):  # noqa: ANN002
        return self.scalar_queue.pop(0) if self.scalar_queue else None


class _User:
    id = 1
    telegram_id = 111
    avatar_manual_url = None
    display_name = "Русланище"


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


def _flag(monkeypatch, *, enabled: bool = True, debug: bool = False) -> None:
    async def _en(_session):  # noqa: ANN001
        return enabled

    async def _db(_session, _tg):  # noqa: ANN001
        return debug

    monkeypatch.setattr(gates, "is_game_enabled", _en)
    monkeypatch.setattr(gates, "is_debug_exempt", _db)


# --------------------------------------------------------------------------
# check_feature
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_game_removes_the_gate(monkeypatch, session):
    """Рубильник выключен → базовые функции НЕ должны блокироваться."""
    _flag(monkeypatch, enabled=False)
    res = await gates.check_feature(session, "chukhan_immunity", user_id=1)
    assert res.allowed is True


@pytest.mark.asyncio
async def test_debug_exempt_bypasses_the_gate(monkeypatch, session):
    _flag(monkeypatch, enabled=True, debug=True)
    res = await gates.check_feature(session, "chukhan_immunity", user_id=1)
    assert res.allowed is True


@pytest.mark.asyncio
async def test_low_level_is_blocked_with_required_level(monkeypatch, session):
    _flag(monkeypatch)
    session.store[("GameProfile", 1)] = GameProfile(user_id=1, xp=0)
    res = await gates.check_feature(session, "loser_roulette", user_id=1)
    assert res.allowed is False
    assert res.required_level == 2
    assert res.level == 1


@pytest.mark.asyncio
async def test_enough_xp_unlocks_the_feature(monkeypatch, session):
    _flag(monkeypatch)
    session.store[("GameProfile", 1)] = GameProfile(user_id=1, xp=100)  # 2 уровень
    res = await gates.check_feature(session, "loser_roulette", user_id=1)
    assert res.allowed is True


@pytest.mark.asyncio
async def test_ungated_feature_is_allowed(monkeypatch, session):
    """Опечатка в коде фичи не должна ломать старое поведение."""
    _flag(monkeypatch)
    res = await gates.check_feature(session, "no_such_feature", user_id=1)
    assert res.allowed is True


@pytest.mark.asyncio
async def test_telegram_id_is_resolved_to_user(monkeypatch, session):
    _flag(monkeypatch)
    session.scalar_queue = [7]  # select(User.id) по telegram_id
    session.store[("GameProfile", 7)] = GameProfile(user_id=7, xp=900)  # 10 уровень
    res = await gates.check_feature(session, "chukhan_immunity", telegram_id=555)
    assert res.allowed is True and res.level == 10


@pytest.mark.asyncio
async def test_missing_profile_counts_as_level_one(monkeypatch, session):
    _flag(monkeypatch)
    res = await gates.check_feature(session, "loser_roulette", user_id=99)
    assert res.allowed is False and res.level == 1


# --------------------------------------------------------------------------
# Текст отказа и HTTP-обёртка
# --------------------------------------------------------------------------


def test_denial_detail_and_message():
    res = gates.GateResult(
        allowed=False, feature="loser_roulette", level=1, required_level=2
    )
    assert gates.denial_detail(res) == "rank_required:2"
    assert "2 ранга" in gates.denial_message(res)


@pytest.mark.asyncio
async def test_require_feature_raises_403_with_detail(monkeypatch, session):
    _flag(monkeypatch)
    session.store[("GameProfile", 1)] = GameProfile(user_id=1, xp=0)
    with pytest.raises(HTTPException) as exc:
        await gates.require_feature(session, _User(), "loser_roulette")
    assert exc.value.status_code == 403
    assert exc.value.detail == "rank_required:2"


@pytest.mark.asyncio
async def test_require_feature_passes_when_unlocked(monkeypatch, session):
    _flag(monkeypatch)
    session.store[("GameProfile", 1)] = GameProfile(user_id=1, xp=100)
    await gates.require_feature(session, _User(), "loser_roulette")  # не бросает


# --------------------------------------------------------------------------
# Э8.5/8.7: правка «своего» в профиле
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customize_is_a_403_when_rank_is_too_low(monkeypatch, session):
    _flag(monkeypatch)
    session.store[("GameProfile", 1)] = GameProfile(user_id=1, xp=0)  # 1 уровень
    with pytest.raises(HTTPException) as exc:
        await routes_game.update_profile(
            GameCustomizePatch(custom_name="Митян"), session, _User()
        )
    assert exc.value.detail == "rank_required:8"


@pytest.mark.asyncio
async def test_customize_saves_each_field(monkeypatch, session):
    _flag(monkeypatch)
    profile = GameProfile(user_id=1, xp=900)  # 10 уровень: всё открыто
    session.store[("GameProfile", 1)] = profile
    user = _User()

    async def _stub(_s, _u):  # noqa: ANN001
        return GameProfileOut(enabled=True)

    monkeypatch.setattr(routes_game, "my_game", _stub)
    await routes_game.update_profile(
        GameCustomizePatch(
            custom_name="Митян",
            custom_rank_title="Босс шестёрки",
            avatar_manual_url="https://example.test/a.png",
        ),
        session,
        user,
    )
    assert profile.custom_name == "Митян"
    assert profile.custom_rank_title == "Босс шестёрки"
    assert user.avatar_manual_url == "https://example.test/a.png"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_customize_empty_string_clears_the_field(monkeypatch, session):
    _flag(monkeypatch)
    profile = GameProfile(user_id=1, xp=900)
    profile.custom_name = "Старое"
    session.store[("GameProfile", 1)] = profile

    async def _stub(_s, _u):  # noqa: ANN001
        return GameProfileOut(enabled=True)

    monkeypatch.setattr(routes_game, "my_game", _stub)
    await routes_game.update_profile(
        GameCustomizePatch(custom_name="   "), session, _User()
    )
    assert profile.custom_name is None
