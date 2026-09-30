"""GHG10: тесты ядра игровой системы (этап 1).

Async-БД-стенда в проекте нет — как и в остальных тестах, подменяем сессию
лёгким фейком поверх dict (контракт `session.get` / `add` / `commit`).
Покрываем: арифметику уровней/рангов/престижа, полноту каталога рангов,
чистый гейтинг и идемпотентность начисления опыта по окнам.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.services.game import levels
from app.services.game.config import (
    ANNIVERSARY_TIERS,
    LEVEL_UNLOCKS,
    MAX_LEVEL,
    RANKS,
    XP_PER_LEVEL,
    points_for,
    tier_title,
    unlocks_for_level,
)
from app.services.game.flags import has_feature, required_level
from app.services.game.xp import (
    DailyBucket,
    award,
    idem_key,
    total_for_day,
    utc_day,
    window_key,
)
from tests.game_fakes import assert_single_column_pk_get, grant_lookup

# --------------------------------------------------------------------------
# Фейк сессии
# --------------------------------------------------------------------------


class _FakeSession:
    """Стенд: dict по (имя модели, ключ). Ключ может быть кортежем (сostavной PK)."""

    def __init__(self) -> None:
        self.store: dict[tuple, object] = {}
        self.commits = 0

    async def get(self, model, key):  # noqa: ANN001
        # Ведём себя как настоящая сессия: она собирает PK по метаданным модели
        # и падает, если значений не столько, сколько колонок.
        assert_single_column_pk_get(model, key)
        return self.store.get((model.__name__, key))

    async def scalar(self, stmt, *_a, **_k):  # noqa: ANN001, ANN002
        # Поиск маркера окна в `xp_grants` отвечаем из store — как база по
        # уникальному индексу. Иначе тест молча соглашается с любой формой
        # запроса (этим и прощался `session.get(XpGrant, (user_id, key))`).
        handled, value = grant_lookup(stmt, self.store)
        return value if handled else None

    def add(self, row) -> None:  # noqa: ANN001
        # Повторяем поведение session.add: объект попадает «в БД» по своему PK.
        if type(row).__name__ == "GameProfile":
            key = row.user_id
        elif type(row).__name__ == "XpGrant":
            key = (row.user_id, row.idem_key)
        elif type(row).__name__ == "XpDaily":
            key = (row.user_id, row.day, row.event)
        else:  # pragma: no cover — неизвестная модель в тесте
            raise AssertionError(f"unexpected model {type(row).__name__}")
        self.store[(type(row).__name__, key)] = row

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def session():
    return _FakeSession()


# --------------------------------------------------------------------------
# Уровни и ранг
# --------------------------------------------------------------------------


def test_level_from_zero_is_first():
    assert levels.level_for_xp(0) == 1
    assert levels.level_for_xp(-5) == 1


def test_level_thresholds():
    """Прогрессивная шкала: переход N→N+1 стоит `XP_PER_LEVEL * N`.

    Отсюда пороги 100 / 300 / 600 / 1000 / … — первые уровни берутся легко.
    """
    assert levels.xp_for_level(1) == 0
    assert levels.xp_for_level(2) == XP_PER_LEVEL
    assert levels.xp_for_level(3) == XP_PER_LEVEL * 3
    assert levels.xp_for_level(4) == XP_PER_LEVEL * 6
    assert levels.level_for_xp(XP_PER_LEVEL - 1) == 1
    assert levels.level_for_xp(XP_PER_LEVEL) == 2
    assert levels.level_for_xp(levels.xp_for_level(9) - 1) == 8
    assert levels.level_for_xp(levels.xp_for_level(9)) == 9


def test_level_is_capped_at_max():
    assert levels.level_for_xp(999_999) == MAX_LEVEL


def test_prestige_starts_when_bar_is_full_not_after():
    """Регресс: престиж должен начинаться ровно на полной шкале, не за ней."""
    assert levels.xp_cap() == levels.xp_for_level(MAX_LEVEL)
    assert levels.level_for_xp(levels.xp_cap()) == MAX_LEVEL
    assert levels.prestige_for_xp(levels.xp_cap()) == 0
    assert levels.prestige_for_xp(levels.xp_cap() + 250) == 250


def test_progress_shape():
    # 150 XP — второй уровень (пороги 0 / 100 / 300), до третьего ещё 150.
    p = levels.progress_for_xp(150)
    assert p.level == 2
    assert p.xp_into_level == 50
    assert p.xp_to_next == 150
    assert not p.at_max
    # Знаменатель шкалы — цена ИМЕННО этого перехода, а не 100 для всех уровней.
    assert levels.xp_span_for_level(2) == 200
    assert levels.xp_span_for_level(9) == 900


def test_progress_at_max_has_no_next():
    p = levels.progress_for_xp(levels.xp_cap() + 40)
    assert p.at_max
    assert p.xp_to_next is None
    assert p.prestige == 40
    assert p.rank.level == MAX_LEVEL


def test_levels_gained_lists_every_crossed_level():
    assert levels.levels_gained(0, 100) == [2]
    # одно начисление может закрыть сразу несколько уровней (0 → 600 = 4-й)
    assert levels.levels_gained(90, 600) == [2, 3, 4]
    assert levels.levels_gained(100, 100) == []
    assert levels.levels_gained(200, 100) == []


def test_levels_gained_stops_at_max():
    assert levels.levels_gained(levels.xp_cap() - 10, levels.xp_cap() + 500) == [MAX_LEVEL]


def test_rank_catalog_is_complete_and_ordered():
    assert len(RANKS) == MAX_LEVEL
    assert [r.level for r in RANKS] == list(range(1, MAX_LEVEL + 1))
    assert len({r.hex for r in RANKS}) == MAX_LEVEL  # цвета не дублируются
    # «выделен жирным» из задания — только ранги 8..10
    assert [r.level for r in RANKS if r.bold] == [8, 9, 10]


def test_custom_rank_only_on_last_level():
    assert [r.level for r in RANKS if r.custom_rank_unlock] == [MAX_LEVEL]


def test_supreme_chukhan_overrides_level_rank():
    """«Верховный чухан» — единственный ранг приоритетнее ранга за уровень."""
    assert levels.effective_rank_name(0, supreme_chukhan=False) == "Подшконарь"
    assert levels.effective_rank_name(0, supreme_chukhan=True) == "Верховный чухан"
    assert levels.effective_rank_name(9999, supreme_chukhan=True) == "Верховный чухан"


# --------------------------------------------------------------------------
# Гейтинг
# --------------------------------------------------------------------------


def test_required_level_matches_spec():
    """Пороги из задания (рулетка 2 / фразы лоха 3 / чухана 4 / реролл 5 и т.д.)."""
    assert required_level("loser_roulette") == 2
    assert required_level("loser_phrases_editor") == 3
    assert required_level("chukhan_phrases_editor") == 4
    assert required_level("chukhan_reroll") == 5
    assert required_level("custom_avatar") == 6
    assert required_level("forced_loser_reroll") == 7
    assert required_level("custom_name") == 8
    assert required_level("loser_immunity") == 9
    assert required_level("chukhan_immunity") == 10


def test_has_feature_boundaries():
    assert has_feature(1, "loser_roulette") is False
    assert has_feature(2, "loser_roulette") is True
    assert has_feature(10, "loser_roulette") is True


def test_debug_exempt_bypasses_every_gate():
    assert has_feature(1, "chukhan_immunity", debug=True) is True


def test_unknown_feature_is_not_gated():
    """Гейтинг — дополнительный слой: опечатка в коде фичи не должна ломать старое."""
    assert required_level("nonexistent") is None
    assert has_feature(1, "nonexistent") is True


def test_unlocks_accumulate():
    assert unlocks_for_level(1) == ()
    assert set(unlocks_for_level(3)) == {"loser_roulette", "loser_phrases_editor"}
    assert len(unlocks_for_level(MAX_LEVEL)) == sum(
        len(v) for v in LEVEL_UNLOCKS.values()
    )


# --------------------------------------------------------------------------
# Конфиг
# --------------------------------------------------------------------------


def test_points_table_matches_spec():
    assert points_for("message") == 1
    assert points_for("quote") == 1
    assert points_for("became_loser") == 10
    assert points_for("became_chukhan") == 100
    assert points_for("achievement") == 50
    assert points_for("availability") == 10
    assert points_for("birthday") == 100
    assert points_for("holiday") == 50
    assert points_for("meeting") == 50


def test_unknown_event_gives_no_points():
    assert points_for("nope") == 0


def test_anniversary_tiers_and_titles():
    assert ANNIVERSARY_TIERS == (10, 20, 30, 50, 100)
    assert tier_title("с почином", 50) == "с почином ×50"


# --------------------------------------------------------------------------
# Окна идемпотентности
# --------------------------------------------------------------------------


def _at(y, m, d):
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)


def test_window_keys():
    assert window_key(None, _at(2026, 9, 28)) is None
    assert window_key("day", _at(2026, 9, 28)) == "2026-09-28"
    assert window_key("year", _at(2026, 9, 28)) == "2026"
    assert window_key("once", _at(2026, 9, 28)) == "all"
    assert window_key("week", _at(2026, 9, 28)).startswith("2026-W")


def test_idem_key_without_limit_is_none():
    assert idem_key("message", None) is None


def test_idem_key_includes_discriminator():
    a = idem_key("meeting", "day", at=_at(2026, 9, 28), discriminator=1)
    b = idem_key("meeting", "day", at=_at(2026, 9, 28), discriminator=2)
    assert a != b
    # …но одна и та же встреча в один день — тот же ключ
    assert a == idem_key("meeting", "day", at=_at(2026, 9, 28), discriminator=1)


def test_utc_day_uses_utc():
    assert utc_day(_at(2026, 9, 28)) == date(2026, 9, 28)
    # 23:30 UTC — ещё те же сутки (сдвиг часового пояса не должен уезжать)
    assert utc_day(datetime(2026, 9, 28, 23, 30, tzinfo=timezone.utc)) == date(
        2026, 9, 28
    )


# --------------------------------------------------------------------------
# Начисление опыта
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_award_creates_profile_and_daily_bucket(session):
    res = await award(session, 1, "message", at=_at(2026, 9, 28))
    assert res.awarded and res.points == 1
    assert res.xp_before == 0 and res.xp_after == 1
    assert res.levels_gained == ()
    bucket = session.store[("XpDaily", (1, utc_day(_at(2026, 9, 28)), "message"))]
    assert bucket.count == 1 and bucket.points == 1


@pytest.mark.asyncio
async def test_messages_accumulate_and_aggregate(session):
    for _ in range(3):
        await award(session, 1, "message", at=_at(2026, 9, 28))
    profile = session.store[("GameProfile", 1)]
    assert profile.xp == 3
    bucket = session.store[("XpDaily", (1, utc_day(_at(2026, 9, 28)), "message"))]
    assert bucket.count == 3
    assert bucket.points == 3


@pytest.mark.asyncio
async def test_daily_limited_event_is_granted_once(session):
    first = await award(session, 1, "availability", at=_at(2026, 9, 28))
    second = await award(session, 1, "availability", at=_at(2026, 9, 28))
    assert first.awarded and first.points == 10
    assert not second.awarded
    assert second.skip_reason == "window-already-granted"
    assert session.store[("GameProfile", 1)].xp == 10


@pytest.mark.asyncio
async def test_weekly_limit_is_per_iso_week(session):
    """Опыт за календарь даётся раз в неделю — в новую неделю снова начисляется."""
    await award(session, 1, "availability", at=_at(2026, 9, 28))
    # 2026-10-05 — следующая ISO-неделя
    res = await award(session, 1, "availability", at=_at(2026, 10, 5))
    assert res.awarded
    assert session.store[("GameProfile", 1)].xp == 20


@pytest.mark.asyncio
async def test_year_limited_event_is_per_calendar_year(session):
    await award(session, 1, "birthday", at=_at(2026, 9, 28))
    again = await award(session, 1, "birthday", at=_at(2026, 9, 29))
    assert not again.awarded
    nextyear = await award(session, 1, "birthday", at=_at(2027, 9, 28))
    assert nextyear.awarded
    assert session.store[("GameProfile", 1)].xp == 200


@pytest.mark.asyncio
async def test_award_reports_level_up(session):
    res = await award(session, 1, "message", at=_at(2026, 9, 28), points=150)
    assert res.xp_after == 150
    assert res.levels_gained == (2,)


@pytest.mark.asyncio
async def test_award_uses_config_points_by_default(session):
    res = await award(session, 1, "became_chukhan", at=_at(2026, 9, 28))
    assert res.points == 100


@pytest.mark.asyncio
async def test_zero_point_event_only_writes_window_marker(session):
    """Донат-перевод: цена 0 (переводится получателю), но окно «раз в год» важно."""
    res = await award(session, 1, "donation_sent", at=_at(2026, 9, 28))
    assert res.awarded and res.points == 0
    assert res.xp_after == 0
    # Профиль под нулевое начисление НЕ создаём — незачем заводить строку.
    assert ("GameProfile", 1) not in session.store
    # Но маркер окна записан, поэтому повтор в том же году не пройдёт.
    again = await award(session, 1, "donation_sent", at=_at(2026, 9, 28))
    assert not again.awarded


@pytest.mark.asyncio
async def test_total_for_day_sums_buckets(session):
    await award(session, 1, "message", at=_at(2026, 9, 28))
    await award(session, 1, "became_loser", at=_at(2026, 9, 28))
    raw = [b for k, b in session.store.items() if k[0] == "XpDaily"]
    buckets = [
        DailyBucket(
            event=r.event, title=r.event, points=r.points, count=r.count
        )
        for r in raw
    ]
    assert total_for_day(buckets) == 11
    assert len(buckets) == 2
