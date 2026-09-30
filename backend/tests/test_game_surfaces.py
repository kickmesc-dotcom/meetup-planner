"""GHG10 (этапы 3, 5, 6): уведомление о левел-апе, недельный job и поверхности.

Как и в остальных игровых тестах — лёгкий фейк сессии поверх dict с
программируемыми очередями (`scalar`/`scalars`/`execute`). Покрываем:

* `unlocks_between` и запись «непоказанного» левел-апа в `xp.award`;
* окно/ключ недели и подсчёт активности (`weekly.py`);
* идемпотентность недельных званий по ISO-неделе;
* payload профиля и чарты поверхностей (`routes_game.py`) при включённом
  и выключенном рубильнике.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

import pytest

from app.api import routes_game
from app.db.models import GameProfile, UserAchievement
from app.services.game import achievements, awards, levels, weekly, xp
from app.services.game.config import SUPREME_CHUKHAN_TITLE, unlocks_between
from tests.game_fakes import assert_single_column_pk_get, grant_lookup

# --------------------------------------------------------------------------
# Фейк сессии (dict + очереди ответов)
# --------------------------------------------------------------------------


def _key_for(row):  # noqa: ANN001
    name = type(row).__name__
    if name == "GameProfile":
        return (name, row.user_id)
    if name == "XpGrant":
        return (name, (row.user_id, row.idem_key))
    if name == "XpDaily":
        return (name, (row.user_id, row.day, row.event))
    if name == "UserAchievement":
        return (name, (row.user_id, row.code))
    if name == "AchievementCounter":
        return (name, (row.user_id, row.code))
    if name == "ChatActivityDaily":
        return (name, (row.user_id, row.day))
    raise AssertionError(f"unexpected model {name}")


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
        self.scalars_queue: list[list] = []
        self.execute_queue: list[list] = []

    async def get(self, model, key):  # noqa: ANN001
        assert_single_column_pk_get(model, key)
        return self.store.get((model.__name__, key))

    def add(self, row) -> None:  # noqa: ANN001
        self.added.append(row)
        self.store[_key_for(row)] = row

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None

    async def scalar(self, stmt=None, *_a, **_k):  # noqa: ANN001, ANN002
        # Поиск маркера окна в `xp_grants` — из store (как в базе по уникальному
        # индексу), чтобы форма запроса в коде была под тестом, а не «мимо».
        handled, value = grant_lookup(stmt, self.store)
        if handled:
            return value
        return self.scalar_queue.pop(0) if self.scalar_queue else None

    async def scalars(self, *_a, **_k):  # noqa: ANN002
        return _Rows(self.scalars_queue.pop(0) if self.scalars_queue else [])

    async def execute(self, *_a, **_k):  # noqa: ANN002
        return _Rows(self.execute_queue.pop(0) if self.execute_queue else [])


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


class _User:
    id = 5


def _at(y, m, d) -> datetime:
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Э3: уведомление о левел-апе
# --------------------------------------------------------------------------


def test_unlocks_between_lists_only_new_levels():
    assert unlocks_between(1, 2) == ("loser_roulette",)
    assert unlocks_between(5, 6) == ("custom_avatar", "holidays_manage")
    # несколько уровней разом — всё подряд
    assert set(unlocks_between(7, 10)) == {
        "custom_name",
        "loser_immunity",
        "chukhan_immunity",
        "custom_rank",
    }
    # границы включительные, «от» не входит
    assert unlocks_between(2, 2) == ()


@pytest.mark.asyncio
async def test_award_records_pending_level_up(session: _FakeSession):
    res = await xp.award(session, 1, "message", at=_at(2026, 9, 28), points=150)
    assert res.levels_gained == (2,)
    profile = session.store[("GameProfile", 1)]
    assert profile.pending_level_up_from == 1
    assert profile.pending_level_up_to == 2


@pytest.mark.asyncio
async def test_pending_level_up_keeps_the_earliest_from(session: _FakeSession):
    """Одно начисление закрыло несколько уровней, потом ещё — «from» не едет вверх."""
    await xp.award(session, 1, "message", at=_at(2026, 9, 28), points=150)  # 1→2
    await xp.award(session, 1, "message", at=_at(2026, 9, 28), points=450)  # 600 → 4
    profile = session.store[("GameProfile", 1)]
    assert profile.pending_level_up_from == 1  # самое раннее
    assert profile.pending_level_up_to == 4  # самое позднее


@pytest.mark.asyncio
async def test_no_level_up_notification_below_threshold(session: _FakeSession):
    await xp.award(session, 1, "message", at=_at(2026, 9, 28), points=50)
    profile = session.store[("GameProfile", 1)]
    assert profile.pending_level_up_from is None
    assert profile.pending_level_up_to is None


@pytest.mark.asyncio
async def test_prestige_at_max_does_not_create_notification(session: _FakeSession):
    """9→10 даёт уведомление, дальше опыт уходит в престиж и больше не уведомляет."""
    await xp.award(session, 1, "message", at=_at(2026, 9, 28), points=levels.xp_cap())  # 1→10
    profile = session.store[("GameProfile", 1)]
    assert profile.pending_level_up_to == 10
    await xp.award(session, 1, "message", at=_at(2026, 9, 28), points=100)  # престиж
    assert profile.pending_level_up_to == 10  # не поехало


# --------------------------------------------------------------------------
# Э6: окно недели и подсчёт активности
# --------------------------------------------------------------------------


def test_week_bounds_is_previous_iso_week():
    # среда 2026-09-30 → предыдущая неделя 21..27 сентября
    start, end = weekly.week_bounds(_at(2026, 9, 30))
    assert start == date(2026, 9, 21)
    assert end == date(2026, 9, 27)
    assert start.weekday() == 0 and end.weekday() == 6


def test_iso_week_key_matches_xp_window_format():
    iso = date(2026, 9, 21).isocalendar()
    assert weekly.iso_week_key(date(2026, 9, 21)) == f"{iso.year}-W{iso.week:02d}"


@pytest.mark.asyncio
async def test_week_activity_counts_groups_by_user(session: _FakeSession):
    session.execute_queue = [[(1, 42), (2, 7)]]
    counts = await achievements.week_activity_counts(
        session, date(2026, 9, 21), date(2026, 9, 27)
    )
    assert counts == {1: 42, 2: 7}


@pytest.mark.asyncio
async def test_week_titles_are_idempotent_per_week(session: _FakeSession):
    first = await achievements.on_week_activity(
        session, most_active_id=1, least_active_id=2, week_key="2026-W39", announce=False
    )
    assert {a.code for a in first} == {"generation_mouthpiece", "read_only"}
    # Повторный прогон за ту же неделю — ни ачивок, ни роста счётчиков.
    again = await achievements.on_week_activity(
        session, most_active_id=1, least_active_id=2, week_key="2026-W39", announce=False
    )
    assert again == []
    assert await achievements.get_counter(
        session, 1, achievements.COUNTER_MOUTHPIECE
    ) == 1
    assert await achievements.get_counter(
        session, 2, achievements.COUNTER_READ_ONLY
    ) == 1


@pytest.mark.asyncio
async def test_week_activity_job_wires_bounds_counts_and_key(monkeypatch):
    """Job: считает по предыдущей неделе, отдаёт extremes и ключ ISO-недели."""
    calls: dict = {}

    async def _fake_week_activity(session, *, most_active_id, least_active_id, week_key=None):
        calls["most"] = most_active_id
        calls["least"] = least_active_id
        calls["week_key"] = week_key

    async def _enabled(_session):  # noqa: ANN001
        return True

    sess = _FakeSession()
    sess.execute_queue = [[(1, 50), (2, 3), (3, 9)]]

    @asynccontextmanager
    async def _cm():
        yield sess

    monkeypatch.setattr(weekly, "get_sessionmaker", lambda: _cm)
    monkeypatch.setattr(weekly, "is_game_enabled", _enabled)
    monkeypatch.setattr(weekly.awards, "week_activity", _fake_week_activity)

    most, least = await weekly.run_week_activity_job(now=_at(2026, 9, 30))
    assert (most, least) == (1, 2)
    assert calls["week_key"] == weekly.iso_week_key(date(2026, 9, 21))


@pytest.mark.asyncio
async def test_week_activity_job_noop_without_data(monkeypatch):
    async def _enabled(_session):  # noqa: ANN001
        return True

    sess = _FakeSession()
    sess.execute_queue = [[]]  # ни одного сообщения за неделю

    @asynccontextmanager
    async def _cm():
        yield sess

    monkeypatch.setattr(weekly, "get_sessionmaker", lambda: _cm)
    monkeypatch.setattr(weekly, "is_game_enabled", _enabled)
    assert await weekly.run_week_activity_job(now=_at(2026, 9, 30)) == (None, None)


# --------------------------------------------------------------------------
# Э5: поверхности
# --------------------------------------------------------------------------


def _disable(monkeypatch) -> None:
    async def _false(_session):  # noqa: ANN001
        return False

    monkeypatch.setattr(routes_game, "is_game_enabled", _false)


@pytest.mark.asyncio
async def test_profile_is_silent_when_game_disabled(monkeypatch, session):
    _disable(monkeypatch)
    out = await routes_game.my_game(session, _User())
    assert out.enabled is False
    assert out.achievements == [] and out.xp_rules == []


@pytest.mark.asyncio
async def test_charts_are_empty_when_game_disabled(monkeypatch, session):
    _disable(monkeypatch)
    assert await routes_game.achievements_stats(session, _User()) == []
    assert await routes_game.ranks_chart(session, _User()) == []


@pytest.mark.asyncio
async def test_profile_payload_has_rank_progress_and_level_up(monkeypatch, session):
    async def _enabled(_session):  # noqa: ANN001
        return True

    monkeypatch.setattr(routes_game, "is_game_enabled", _enabled)
    profile = GameProfile(user_id=_User.id, xp=150)
    profile.pending_level_up_from = 1
    profile.pending_level_up_to = 2
    session.store[("GameProfile", _User.id)] = profile
    # supreme? None; затем 5 счётчиков progressа (loser/chukhan/rolls/polls/nominations)
    session.scalar_queue = [None, 1, 0, 0, 0, 0]
    # daily_status, collected_codes, unlocked_at_map
    session.scalars_queue = [[], [], []]

    out = await routes_game.my_game(session, _User())
    assert out.enabled is True
    assert out.level == 2 and out.rank is not None
    assert out.rank_name == "Воин кринжа"
    # 150 XP — второй уровень, до третьего (300) ещё 150.
    assert out.xp_to_next == 150
    assert out.level_up is not None
    assert out.level_up.from_level == 1 and out.level_up.to_level == 2
    assert [f.code for f in out.level_up.unlocked] == ["loser_roulette"]
    # «за что дают опыт» — полный список правил
    assert {r.code for r in out.xp_rules} >= {"message", "became_loser", "birthday"}


@pytest.mark.asyncio
async def test_ack_level_up_clears_pending(monkeypatch, session):
    profile = GameProfile(user_id=_User.id, xp=150)
    profile.pending_level_up_from = 1
    profile.pending_level_up_to = 2
    session.store[("GameProfile", _User.id)] = profile
    await routes_game.ack_level_up(session, _User())
    assert profile.pending_level_up_from is None
    assert profile.pending_level_up_to is None
    assert session.commits == 1


@pytest.mark.asyncio
async def test_supreme_rank_name_overrides_level_rank(monkeypatch, session):
    async def _enabled(_session):  # noqa: ANN001
        return True

    monkeypatch.setattr(routes_game, "is_game_enabled", _enabled)
    session.store[("GameProfile", _User.id)] = GameProfile(user_id=_User.id, xp=0)
    session.scalar_queue = [1]  # is_supreme_chukhan → True
    session.scalars_queue = [[], [], []]

    out = await routes_game.my_game(session, _User())
    assert out.supreme is True
    assert out.rank_name == SUPREME_CHUKHAN_TITLE


@pytest.mark.asyncio
async def test_ranks_chart_builds_rows_with_ranks(monkeypatch, session):
    async def _enabled(_session):  # noqa: ANN001
        return True

    monkeypatch.setattr(routes_game, "is_game_enabled", _enabled)
    profiles = [
        GameProfile(user_id=1, xp=levels.xp_cap()),
        GameProfile(user_id=2, xp=0),
    ]
    profiles[0].custom_rank_title = None
    session.scalars_queue = [profiles, [1]]  # профили + supreme_holders([1])

    rows = await routes_game.ranks_chart(session, _User())
    assert [r.user_id for r in rows] == [1, 2]
    assert rows[0].level == 10 and rows[0].supreme is True
    assert rows[0].rank_name == SUPREME_CHUKHAN_TITLE
    assert rows[1].level == 1


@pytest.mark.asyncio
async def test_achievements_stats_aggregates_holders_and_percent(session, monkeypatch):
    """Сводка редкости: тиры складываются с базовым кодом, процент — от участников."""
    async def _enabled(_session):  # noqa: ANN001
        return True

    monkeypatch.setattr(routes_game, "is_game_enabled", _enabled)
    session.scalar_queue = [6]  # всего участников
    session.execute_queue = [[("chin_up", 3), ("chin_up:10", 3), ("first_worm", 1)]]

    out = await routes_game.achievements_stats(session, _User())
    by_code = {r.code: r for r in out}
    assert by_code["chin_up"].holders == 3
    assert by_code["chin_up"].percent == 50  # 3 из 6
    assert by_code["chin_up"].title == "С почином"
    assert by_code["first_worm"].holders == 1
    assert by_code["self_shot"].holders == 0  # у кого нет — 0, а не пропуск


# Фасад: недельный вызов проходит через рубильник и week_key (Э6).
@pytest.mark.asyncio
async def test_facade_week_activity_forwards_week_key(monkeypatch, session):
    captured: dict = {}

    async def _capture(session_, *, most_active_id, least_active_id, week_key=None):
        captured.update(most=most_active_id, key=week_key)

    async def _enabled(_session):  # noqa: ANN001
        return True

    monkeypatch.setattr(awards, "is_game_enabled", _enabled)
    monkeypatch.setattr(achievements, "on_week_activity", _capture)
    await awards.week_activity(
        session, most_active_id=1, least_active_id=2, week_key="2026-W39"
    )
    assert captured == {"most": 1, "key": "2026-W39"}


@pytest.mark.asyncio
async def test_facade_week_activity_silent_when_disabled(monkeypatch, session):
    async def _false(_session):  # noqa: ANN001
        return False

    monkeypatch.setattr(awards, "is_game_enabled", _false)
    await awards.week_activity(session, most_active_id=1, least_active_id=2, week_key="x")
    assert session.added == []


def test_user_achievement_codes_are_plain_strings():
    """Каталог в коде: смена ачивок не требует миграции (code без FK)."""
    assert UserAchievement.__table__.c.code.type.length == 64
