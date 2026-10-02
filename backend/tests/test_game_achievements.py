"""GHG10 (этапы 2 и 4): тесты ачивок, трекеров и фасада начисления.

Async-БД-стенда в проекте нет — снова фейк-сессия (см. `test_game_core.py`),
но расширенная: ачивкам нужны не только `get/add/commit`, но и `scalar`/`scalars`,
иначе трекеры (которые считают по существующим таблицам) не проверить.

Программируемые очереди: `scalar_queue` — ответы на последовательные `scalar`,
`execute_queue` — строки для `execute(...).all()`. Пустая очередь → None/[],
что ровно соответствует «записи нет» / «пустая таблица».
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import ChatActivityDaily, UserAchievement
from types import SimpleNamespace

from app.services.game import achievements, awards
from app.services.game.achievements_catalog import (
    ANNIVERSARY_TIERS,
    CATALOG,
    KIND_COUNTER,
    KIND_INSTANT,
    KIND_THRESHOLD,
    KINDS,
    SUPREME_CHUKHAN_CODE,
    all_achievements,
    base_achievements,
    catalog_size,
    get,
    tier_codes,
    tiers_reached,
)
from app.services.game.holidays import holiday_announcement
from tests.game_fakes import assert_single_column_pk_get, grant_lookup

# --------------------------------------------------------------------------
# Расширенный фейк сессии
# --------------------------------------------------------------------------


def _key_for(row) -> tuple:  # noqa: ANN001
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
    if name == "EventLog":
        # Э19: журнал кары. PK автоинкрементный, а в фейке `get` по EventLog не
        # делается — хватает уникального ключа (identity объекта).
        return (name, id(row))
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
        self.rollbacks = 0
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
        self.rollbacks += 1

    async def scalar(self, stmt=None, *_a, **_k):  # noqa: ANN001, ANN002
        # См. `tests/game_fakes.py`: маркер окна ищем по store, как база.
        handled, value = grant_lookup(stmt, self.store)
        if handled:
            return value
        return self.scalar_queue.pop(0) if self.scalar_queue else None

    async def scalars(self, *_a, **_k):  # noqa: ANN002
        rows = self.scalars_queue.pop(0) if self.scalars_queue else []
        return _Rows(rows)

    async def execute(self, *_a, **_k):  # noqa: ANN002
        rows = self.execute_queue.pop(0) if self.execute_queue else []
        return _Rows(rows)

    # --- удобные пробники ---
    def xp_of(self, user_id: int) -> int:
        row = self.store.get(("GameProfile", user_id))
        return row.xp if row else 0

    def codes_of(self, user_id: int) -> set[str]:
        return {
            row.code
            for row in self.added
            if isinstance(row, UserAchievement) and row.user_id == user_id
        }


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


def _now() -> datetime:
    return datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Каталог (Э4.1, Э4.4)
# --------------------------------------------------------------------------


def test_catalog_has_expected_number_of_base_achievements():
    """Исходное задание — 20 ачивок; Э14/Э15/Э16 добавили 6 под соц-механики.

    Тиры — отдельные записи, но база считается по ним ровно один раз.
    """
    bases = base_achievements()
    assert len(bases) == 32  # +punish_day3, punish_all, punish_bot (Э19)
    # База + все юбилейные тиры.
    assert catalog_size() == len(bases) + sum(len(a.tiers) for a in bases)


def test_all_codes_unique_and_kinds_valid():
    codes = [a.code for a in all_achievements()]
    assert len(codes) == len(set(codes))
    for ach in all_achievements():
        assert ach.kind in KINDS, ach.code
        assert ach.title and ach.description and ach.icon, ach.code
        assert ach.points > 0


def test_first_time_and_anniversary_are_always_separate():
    """Жёсткое правило оператора: «впервые» и «юбилей» — ДВЕ разные ачивки.

    Всякий раз, где в описании базовой ачивки есть «впервые», она обязана быть
    накопительной (`counter`) с юбилеями, а сами юбилейные тиры — не повторять
    слово «впервые» (иначе «впервые — 10-й раз»).
    """
    import re

    seen = 0
    for base in base_achievements():
        if not re.search(r"впервые", base.description, re.IGNORECASE):
            continue
        seen += 1
        assert base.kind == KIND_COUNTER, base.code
        # Обязателен непустой набор юбилеев. У «недельных» званий он короче
        # (3/5/10 — из-за RNG 100 нереально), у остальных — стандартный плюс
        # свой порог (напр. ×3 у «Агента ВЦИОМ-а»).
        assert base.tiers, base.code
        for code in tier_codes(base.code):
            tier = get(code)
            assert not re.search(r"впервые", tier.description, re.IGNORECASE), code
            assert tier.tier is not None and tier.base == base.code
    assert seen >= 10  # голос/музыка/лох/чухан/рулетка/активность/донаты


def test_anniversary_tiers_expand_to_separate_entries():
    """«Отдельный поздравительный статус и уровень ачивки для каждого юбилея»."""
    # Недельные звания выпадают по RNG — у них короткие достижимые тиры.
    for base in ("first_worm", "generation_mouthpiece", "read_only"):
        assert get(base).tiers == (3, 5, 10)
    for base in (
        "chin_up",
        "truth_seeker",
        "cashback",
        "worm_lord",
        "punisher",
    ):
        assert get(base) is not None
        assert get(base).tiers == ANNIVERSARY_TIERS
        codes = tier_codes(base)
        assert len(codes) == len(ANNIVERSARY_TIERS)
        # Тиры ссылаются на родителя — по этому полю считается спец-ранг.
        assert all(get(c).base == base for c in codes)
        assert get(codes[-1]).tier == max(ANNIVERSARY_TIERS)
    # у разовых и пороговых тиров нет
    assert get("self_shot").tiers == ()
    assert tier_codes("self_shot") == []


def test_thresholds_expanded_to_first_plus_tiers():
    """Бывшие пороги разведены на «впервые» + юбилеи (правило оператора).

    Где старый порог не совпадал со стандартным юбилеем (3), он добавлен в НАБОР
    тиров конкретной ачивки, поэтому ничего не потеряно.
    """
    for code in ("vciom_agent", "nominal_nominal", "opium_for_nobody"):
        assert get(code).kind == KIND_COUNTER, code
        assert get(code).threshold is None, code
        assert 3 in get(code).tiers, code
    for code in ("worm_tamer", "successful_success"):
        assert get(code).kind == KIND_COUNTER, code
        assert get(code).tiers == ANNIVERSARY_TIERS, code
    # Серия остаётся пороговой — «первый раз» покрывает `music_guess`.
    assert get("music_streak").kind == KIND_THRESHOLD
    assert get("music_streak").threshold == 5
    # Мем-ачивки и донаты ждут своей телеметрии (Э7/Э11) — это зафиксировано в каталоге.
    for code in ("memelog", "forever_alone", "successful_success", "cashback", "don_corleone"):
        assert get(code).needs_telemetry is True, code
    assert get("self_shot").needs_telemetry is False


def test_kind_distribution_matches_spec():
    kinds = [a.kind for a in base_achievements()]
    # 11 счётчиков (базовые + Э14–Э17) + 5 бывших порогов, ставших счётчиками;
    # 1 порог — music_streak (серия); 9 разовых.
    assert kinds.count(KIND_COUNTER) == 18  # + worm_lord, punisher (Э18)
    assert kinds.count(KIND_THRESHOLD) == 1  # music_streak
    assert kinds.count(KIND_INSTANT) == 13  # + punisher-дня/всех/бота (Э19)


def test_tiers_reached_is_pure_and_monotonic():
    assert tiers_reached("chin_up", 1) == []
    assert tiers_reached("chin_up", 9) == []
    assert tiers_reached("chin_up", 10) == ["chin_up:10"]
    assert tiers_reached("chin_up", 30) == ["chin_up:10", "chin_up:20", "chin_up:30"]
    assert tiers_reached("chin_up", 10_000) == tier_codes("chin_up")


def test_supreme_chukhan_is_secret_capstone():
    ach = get(SUPREME_CHUKHAN_CODE)
    assert ach.secret is True
    assert ach.title == "Верховный чухан"


# --------------------------------------------------------------------------
# Чистые помощники
# --------------------------------------------------------------------------


def test_build_announcement_has_title_description_and_points():
    text = achievements.build_announcement("Русланище", [get("self_shot")])
    assert "Самострел" in text
    assert "Закрутить рулетку" in text
    assert "+50 XP" in text


def test_build_announcement_batches_multiple():
    text = achievements.build_announcement(
        "Русланище", [get("chin_up"), get("chin_up:10")]
    )
    assert "2 ачивок" in text
    assert "×10" in text


def test_covered_days_counts_multiday_range():
    from datetime import date

    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows = [
        # полоса 1–4 сентября включительно (4 дня)
        (start, start + timedelta(days=3), True),
        (start + timedelta(days=10), start + timedelta(days=10), False),
    ]
    # окно 30 дней: 4 дня полосы + 1 отдельный = 5
    assert achievements.covered_days(rows, date(2026, 9, 1), 30) == 5
    # окно 2 дня: только 1 и 2 сентября
    assert achievements.covered_days(rows, date(2026, 9, 1), 2) == 2
    # полоса целиком за окном не считается
    assert achievements.covered_days(rows, date(2026, 8, 1), 5) == 0


def test_pick_week_extremes_ignores_week_without_data():
    assert achievements.pick_week_extremes({}) == (None, None)
    # один живой участник — «самый активный» и «самый неактивный» один и тот же: не выдаём
    assert achievements.pick_week_extremes({1: 5}) == (None, None)
    assert achievements.pick_week_extremes({1: 5, 2: 0}) == (None, None)


def test_pick_week_extremes_picks_mouthpiece_and_read_only():
    counts = {1: 100, 2: 5, 3: 7}
    assert achievements.pick_week_extremes(counts) == (1, 2)
    # равенство разрешается детерминированно (меньший id)
    assert achievements.pick_week_extremes({7: 3, 4: 3, 9: 1}) == (4, 9)


def test_holiday_announcement_text():
    from app.db.models import GameHoliday

    h = GameHoliday(month=1, day=1, message="С Новым годом!")
    text = holiday_announcement(h, points=50)
    assert "С Новым годом!" in text and "+50 XP" in text


# --------------------------------------------------------------------------
# Выдача ачивок
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_awards_row_and_xp(session: _FakeSession):
    ach = await achievements.grant(session, 1, "self_shot", announce=False)
    assert ach is not None and ach.code == "self_shot"
    assert session.codes_of(1) == {"self_shot"}
    assert session.xp_of(1) == 50  # «ачивка = 50 очков»


@pytest.mark.asyncio
async def test_grant_is_idempotent(session: _FakeSession):
    await achievements.grant(session, 1, "self_shot", announce=False)
    session.scalar_queue = [123]  # has() → «уже есть»
    again = await achievements.grant(session, 1, "self_shot", announce=False)
    assert again is None
    assert session.xp_of(1) == 50  # второй раз опыта не появилось


@pytest.mark.asyncio
async def test_grant_unknown_code_is_noop(session: _FakeSession):
    assert await achievements.grant(session, 1, "no_such_achievement", announce=False) is None
    assert session.added == []


@pytest.mark.asyncio
async def test_grant_counter_grants_base_and_reached_tier(session: _FakeSession):
    granted = await achievements._grant_counter(session, 1, "chin_up", 10, announce=False)
    assert {a.code for a in granted} == {"chin_up", "chin_up:10"}
    # База 50 + юбилей ×10 (весомее базы: ANNIVERSARY_TIER_POINTS).
    assert session.xp_of(1) == 50 + 150


@pytest.mark.asyncio
async def test_grant_counter_skips_everything_at_zero(session: _FakeSession):
    assert await achievements._grant_counter(session, 1, "chin_up", 0, announce=False) == []
    assert session.added == []


@pytest.mark.asyncio
async def test_last_tier_grants_supreme_chukhan_rank(session: _FakeSession):
    """Капстоун: юбилей ×100 автоматически даёт спец-ранг «Верховный чухан»."""
    granted = await achievements._grant_counter(session, 1, "chin_up", 100, announce=False)
    codes = {a.code for a in granted}
    assert "chin_up:100" in codes
    assert SUPREME_CHUKHAN_CODE in codes
    assert SUPREME_CHUKHAN_CODE in session.codes_of(1)
    # База 50 + юбилеи ×10/20/30/50/100 (150/250/350/500/1000) + капстоун 100.
    assert session.xp_of(1) == 50 + 150 + 250 + 350 + 500 + 1000 + 100
    session.scalar_queue = [1]
    assert await achievements.is_supreme_chukhan(session, 1) is True


@pytest.mark.asyncio
async def test_grant_threshold_needs_enough_count(session: _FakeSession):
    assert await achievements._grant_threshold(session, 1, "music_streak", 4, 5, announce=False) == []
    got = await achievements._grant_threshold(session, 1, "music_streak", 5, 5, announce=False)
    assert [a.code for a in got] == ["music_streak"]


@pytest.mark.asyncio
async def test_grant_counter_custom_tier_at_three(session: _FakeSession):
    """«Агент ВЦИОМ-а»: база за первый опрос + свой юбилей ×3 (из tiers)."""
    granted = await achievements._grant_counter(
        session, 1, "vciom_agent", 3, announce=False
    )
    assert {a.code for a in granted} == {"vciom_agent", "vciom_agent:3"}
    assert session.codes_of(1) == {"vciom_agent", "vciom_agent:3"}


# --------------------------------------------------------------------------
# Трекеры
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_loser_duel_gives_no_becoming_loser_but_awards_self_shot(
    session: _FakeSession,
):
    """Дуэль: «лох дня» не начисляется, но «Самострел» — да (крутил и выпал сам)."""
    session.scalar_queue = [None]  # has(self_shot)
    granted = await achievements.on_loser(
        session, loser_id=1, roller_id=1, source="duel", announce=False
    )
    assert [a.code for a in granted] == ["self_shot"]
    # «С почином» не выдан: официальным лохом не был
    assert "chin_up" not in session.codes_of(1)


@pytest.mark.asyncio
async def test_on_loser_official_grants_chin_up_and_truth_seeker(session: _FakeSession):
    session.scalar_queue = [1, None, 1, None]  # count_losers, has, count_rolls, has
    granted = await achievements.on_loser(
        session, loser_id=1, roller_id=2, source="auto", announce=False
    )
    assert {a.code for a in granted} == {"chin_up", "truth_seeker"}


@pytest.mark.asyncio
async def test_on_chukhan_grants_first_worm(session: _FakeSession):
    session.scalar_queue = [1]  # count_chukhan
    granted = await achievements.on_chukhan(session, 7, announce=False)
    assert [a.code for a in granted] == ["first_worm"]


@pytest.mark.asyncio
async def test_on_bot_reply_grants_base_then_anniversary_at_ten(session: _FakeSession):
    """Первый ответ — база «впервые», 10-й — отдельный юбилей ×10."""
    first = await achievements.on_bot_reply(session, 3, announce=False)
    assert [a.code for a in first] == ["worm_tamer"]
    for _ in range(8):
        await achievements.on_bot_reply(session, 3, announce=False)
    granted = await achievements.on_bot_reply(session, 3, announce=False)  # 10-й
    assert "worm_tamer:10" in {a.code for a in granted}
    assert await achievements.get_counter(session, 3, achievements.COUNTER_WORM_TAMER) == 10


@pytest.mark.asyncio
async def test_on_availability_grants_informant_when_month_is_covered(
    session: _FakeSession,
):
    """Информатор: 30 дней вперёд размечены → ачивка."""
    today = datetime.now(timezone.utc).date()
    start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    session.execute_queue = [
        [(start, start + timedelta(days=30), True)],  # одна длинная полоса
        [],
    ]
    session.scalars_queue = [[]]  # нет недельных маркеров → «безработный» не выдан
    granted = await achievements.on_availability(session, 5, announce=False)
    assert [a.code for a in granted] == ["informant"]


@pytest.mark.asyncio
async def test_on_week_activity_uses_counter_for_tiers(session: _FakeSession):
    """Недельные звания: счётчик в БД, а не число записей ачивки (иначе тиры не растут)."""
    for _ in range(2):
        granted = await achievements.on_week_activity(
            session, most_active_id=1, least_active_id=2, announce=False
        )
    codes = {a.code for a in granted}
    assert "generation_mouthpiece" in codes and "read_only" in codes
    assert await achievements.get_counter(session, 1, achievements.COUNTER_MOUTHPIECE) == 2
    assert await achievements.get_counter(session, 2, achievements.COUNTER_READ_ONLY) == 2


@pytest.mark.asyncio
async def test_on_voice_submitted_grants_debut(session: _FakeSession):
    session.scalar_queue = [1, None]  # count_voice_submissions, has
    granted = await achievements.on_voice_submitted(session, 4, announce=False)
    assert [a.code for a in granted] == ["voice_debut"]


@pytest.mark.asyncio
async def test_on_voice_winner_grants_best_voice(session: _FakeSession):
    session.scalar_queue = [2, None]  # count_voice_wins, has
    granted = await achievements.on_voice_winner(session, 4, announce=False)
    assert [a.code for a in granted] == ["voice_winner"]


@pytest.mark.asyncio
async def test_on_music_published_grants_dj(session: _FakeSession):
    session.scalar_queue = [1, None]  # count_music_published, has
    granted = await achievements.on_music_published(session, 4, announce=False)
    assert [a.code for a in granted] == ["music_dj"]


@pytest.mark.asyncio
async def test_on_music_spotlight_grants(session: _FakeSession):
    session.scalar_queue = [1, None]  # count_music_spotlights, has
    granted = await achievements.on_music_spotlight(session, 4, announce=False)
    assert [a.code for a in granted] == ["music_spotlight"]


@pytest.mark.asyncio
async def test_music_streak_grants_after_five_in_a_row(session: _FakeSession):
    # На каждой догадке `grant` проверяет «уже есть?» — queue с запасом.
    session.scalar_queue = [None] * 20
    got: list[str] = []
    for _ in range(5):
        got += [
            a.code
            for a in await achievements.on_music_guess(session, 4, announce=False)
        ]
    assert "music_streak" in got
    assert await achievements.get_counter(session, 4, achievements.COUNTER_MUSIC_STREAK) == 5


@pytest.mark.asyncio
async def test_music_miss_resets_current_streak_but_keeps_best(session: _FakeSession):
    session.scalar_queue = [None] * 20
    for _ in range(3):
        await achievements.on_music_guess(session, 4, announce=False)
    assert (
        await achievements.get_counter(
            session, 4, achievements.COUNTER_MUSIC_STREAK_CURRENT
        )
        == 3
    )
    await achievements.on_music_miss(session, 4)
    assert (
        await achievements.get_counter(
            session, 4, achievements.COUNTER_MUSIC_STREAK_CURRENT
        )
        == 0
    )
    # Рекорд не сбрасывается — ачивка смотрится по нему.
    assert await achievements.get_counter(session, 4, achievements.COUNTER_MUSIC_STREAK) == 3


@pytest.mark.asyncio
async def test_consecutive_availability_weeks_counts_backwards(session: _FakeSession):
    now = datetime.now(timezone.utc)
    keys = []
    for delta in range(3):
        iso = (now - timedelta(weeks=delta)).isocalendar()
        keys.append(f"availability:{iso.year}-W{iso.week:02d}")
    session.scalars_queue = [keys]
    assert await achievements.consecutive_availability_weeks(session, 1) == 3


# --------------------------------------------------------------------------
# Фасад: рубильник и защита от ошибок (Э2)
# --------------------------------------------------------------------------


def _flag(monkeypatch, value: bool) -> None:
    async def _fake(_session):  # noqa: ANN001
        return value

    monkeypatch.setattr(awards, "is_game_enabled", _fake)


@pytest.mark.asyncio
async def test_message_is_silent_when_game_disabled(monkeypatch, session: _FakeSession):
    _flag(monkeypatch, False)
    await awards.message(session, 1, at=_now())
    assert session.added == [] and session.commits == 0


@pytest.mark.asyncio
async def test_message_writes_xp_and_activity_in_one_commit(
    monkeypatch, session: _FakeSession
):
    _flag(monkeypatch, True)
    await awards.message(session, 1, at=_now())
    assert session.xp_of(1) == 1
    activity = session.store[("ChatActivityDaily", (1, _now().date()))]
    assert isinstance(activity, ChatActivityDaily) and activity.messages == 1
    # Самый горячий путь: одно сообщение = один commit, а не два.
    assert session.commits == 1


@pytest.mark.asyncio
async def test_message_accumulates_activity(session: _FakeSession, monkeypatch):
    _flag(monkeypatch, True)
    for _ in range(3):
        await awards.message(session, 1, at=_now())
    assert session.xp_of(1) == 3
    assert session.store[("ChatActivityDaily", (1, _now().date()))].messages == 3


@pytest.mark.asyncio
async def test_all_event_entrypoints_respect_the_flag(monkeypatch, session: _FakeSession):
    """Рубильник выключен → НИ ОДНА точка входа не трогает БД."""
    _flag(monkeypatch, False)
    await awards.quote(session, 1)
    await awards.loser(session, loser_id=1, roller_id=2, source="auto", roll_id=5)
    await awards.chukhan(session, 1, week_start=_now())
    await awards.availability(session, 1, at=_now())
    await awards.birthday(session, 1, at=_now())
    assert await awards.holiday(session, [1, 2], holiday_id=1) == 0
    await awards.meeting(session, 1, 9, at=_now())
    await awards.poll_created(session, 1)
    await awards.nomination_by_tg(session, 111)
    await awards.game_winner_by_tg(session, 111)
    await awards.chukhan_reroll(session, 1)
    await awards.bot_reply_by_tg(session, 111)
    await awards.meme_reactions(session, 1)
    await awards.dead_post(session, 1)
    await awards.donation_sent(session, 1, recipients_this_year=6, live_participants=6)
    await awards.week_activity(session, most_active_id=1, least_active_id=2)
    await awards.achievement(session, 1, "self_shot")
    # Э14/Э15/Э16: новые точки входа тоже уважают рубильник.
    await awards.voice(session, 1, points=50, task_id=7)
    await awards.voice_best(session, 1, points=50, task_id=7)
    await awards.music_author(session, 1, points=30, round_id=3)
    await awards.music_guess(session, 1, points=20, round_id=3)
    await awards.music_published(session, 1, track_id=5)
    await awards.music_miss(session, 1)
    assert session.added == [] and session.commits == 0


@pytest.mark.asyncio
async def test_guarded_swallows_failures_and_rolls_back(monkeypatch, session: _FakeSession):
    """Игра не может ломать бота: ошибка внутри → warning + rollback, без raise."""

    async def _boom(*_a, **_k):  # noqa: ANN002
        raise RuntimeError("db is on fire")

    _flag(monkeypatch, True)
    monkeypatch.setattr(achievements, "on_poll_created", _boom)
    await awards.poll_created(session, 1)  # не должно бросить
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_meeting_award_is_idempotent_per_meeting(monkeypatch, session: _FakeSession):
    """Дискриминатор = id встречи: та же встреча не даёт второй раз +50."""
    _flag(monkeypatch, True)
    await awards.meeting(session, 1, 42, at=_now())
    assert session.xp_of(1) == 50
    await awards.meeting(session, 1, 42, at=_now())
    assert session.xp_of(1) == 50
    # Другая встреча в тот же день — снова 50
    await awards.meeting(session, 1, 43, at=_now())
    assert session.xp_of(1) == 100


# --------------------------------------------------------------------------
# Ссылка на «свои ачивки» в анонсе (Э4.2)
# --------------------------------------------------------------------------


class _FakeMe:
    username = "meetup_planner_bot"


class _FakeBot:
    _me = _FakeMe()


class _FakeSettings:
    mini_app_url = "https://mini-app.example.test/"


@pytest.fixture(autouse=True)
def _settings_stub(monkeypatch):
    """Настройки в тестах не поднимаются без env — подменяем на заглушку."""
    monkeypatch.setattr(achievements, "get_settings", lambda: _FakeSettings())


@pytest.mark.asyncio
async def test_achievements_url_prefers_bot_deeplink():
    url = await achievements.achievements_url(_FakeBot())
    assert url == "https://t.me/meetup_planner_bot?startapp=achievements"


@pytest.mark.asyncio
async def test_achievements_url_falls_back_to_mini_app():
    url = await achievements.achievements_url(None)
    assert url == _FakeSettings.mini_app_url


@pytest.mark.asyncio
async def test_achievements_url_survives_broken_bot():
    """Бот без username/с падающим getMe не ломает анонс — просто прямая ссылка."""

    class _Broken:
        _me = None

        @property
        def me(self):
            raise RuntimeError("no network")

    assert await achievements.achievements_url(_Broken()) == _FakeSettings.mini_app_url


def test_catalog_icons_are_nonempty_for_every_entry():
    assert all(get(c).icon for c in CATALOG)


# --------------------------------------------------------------------------
# Э18: честные серии, червь-господин и «идеальный червь»
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opium_is_a_real_streak_reset_by_live_post(session: _FakeSession):
    """«Опиум для никого» — три поста ПОДРЯД: живой пост рвёт серию, рекорд нет."""
    for _ in range(3):
        await achievements.on_dead_post(session, 1, announce=False)
    assert await achievements.get_counter(session, 1, achievements.COUNTER_OPIUM) == 3
    assert (
        await achievements.get_counter(session, 1, achievements.COUNTER_OPIUM_BEST) == 3
    )
    assert "opium_for_nobody:3" in session.codes_of(1)
    # Живой пост (с реакциями) обнуляет ТЕКУЩУЮ серию, рекорд остаётся.
    await achievements.on_meme_reactions(session, 1, announce=False)
    assert await achievements.get_counter(session, 1, achievements.COUNTER_OPIUM) == 0
    assert (
        await achievements.get_counter(session, 1, achievements.COUNTER_OPIUM_BEST) == 3
    )


@pytest.mark.asyncio
async def test_music_streak_resets_on_missed_round(session: _FakeSession):
    row = SimpleNamespace(user_id=5, count=3)
    session.scalars_queue = [[row]]
    assert (
        await achievements.on_music_round_closed(
            session, guessed_ids={7}, poll_arrived=True
        )
        == 1
    )
    assert row.count == 0
    # Сбой доставки (stale-раунд) игрока не наказывает.
    row2 = SimpleNamespace(user_id=5, count=3)
    session.scalars_queue = [[row2]]
    assert (
        await achievements.on_music_round_closed(
            session, guessed_ids=set(), poll_arrived=False
        )
        == 0
    )
    assert row2.count == 3


@pytest.mark.asyncio
async def test_worm_lord_and_punisher_are_counters(session: _FakeSession):
    assert [a.code for a in await achievements.on_worm_lord(session, 1, announce=False)] == [
        "worm_lord"
    ]
    assert [a.code for a in await achievements.on_punish(session, 1, announce=False)] == [
        "punisher"
    ]


@pytest.mark.asyncio
async def test_punish_on_bot_grants_joke_achievement(session: _FakeSession):
    """Э19: попытка наказать самого бота → «Не по чину» (шутка оператора)."""
    codes = [
        a.code
        for a in await achievements.on_punish(
            session, 1, target_is_bot=True, announce=False
        )
    ]
    assert "punisher" in codes
    assert "punish_bot" in codes


@pytest.mark.asyncio
async def test_punish_day3_after_three_punishes(session: _FakeSession):
    """Э19: три применения кары за сутки → «Тройная кара».

    Считается по журналу `event_log`: три строки за локальные сутки.
    """
    rows = [
        SimpleNamespace(payload={"target_user_id": 2}),
        SimpleNamespace(payload={"target_user_id": 3}),
        SimpleNamespace(payload={"target_user_id": 4}),
    ]
    session.scalars_queue = [rows]
    codes = [
        a.code
        for a in await achievements.on_punish(
            session, 1, target_user_id=4, now=_now(), announce=False
        )
    ]
    assert "punish_day3" in codes


@pytest.mark.asyncio
async def test_completionist_grants_on_full_collection(session: _FakeSession):
    import app.services.game.achievements_catalog as catalog

    # has(completionist) → None; коллекция — всё, кроме самого капстоуна.
    session.scalar_queue = [None]
    session.scalars_queue = [
        [c for c in catalog.CATALOG if c != catalog.COMPLETIONIST_CODE]
    ]
    assert (
        await achievements.reconcile_completionist(session, 1, announce=False) is True
    )
    assert catalog.COMPLETIONIST_CODE in session.codes_of(1)


@pytest.mark.asyncio
async def test_completionist_not_granted_without_full_collection(session: _FakeSession):
    session.scalar_queue = [None]
    session.scalars_queue = [["chin_up", "first_worm"]]
    assert (
        await achievements.reconcile_completionist(session, 1, announce=False) is False
    )
    assert session.added == []
