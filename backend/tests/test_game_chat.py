"""GHG10 Э5.4 (отчёты в чат) и Э10.3 (праздники): чистая логика и ручки.

Проверяем то, что нельзя увидеть в чате глазами разработчика: формат баров,
перевод лимитов, состав подсказки «за что дают опыт», валидацию дат праздников и
поведение ручек при выключенном рубильнике и на занятой дате.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import routes_game
from app.bot import commands_catalog
from app.db.models import GameHoliday
from app.services.game import achievements_catalog as catalog
from app.services.game import holidays, report
from app.services.game.achievements import COUNTER_WORM_TAMER
from app.services.game.config import MAX_LEVEL, XP_PER_LEVEL, XP_RULES


def _game(monkeypatch, enabled: bool) -> None:
    async def _flag(_session):
        return enabled

    monkeypatch.setattr(report, "is_game_enabled", _flag)
    monkeypatch.setattr(routes_game, "is_game_enabled", _flag)
    # Праздники проверяют админство (ADMIN_TG_IDS). Тесты не поднимают настоящее
    # окружение, поэтому подменяем настройки: пусто = пользователь не админ.
    monkeypatch.setattr(
        routes_game, "get_settings", lambda: SimpleNamespace(admin_tg_id_set=set())
    )


# --- Э5.4: отчёты ------------------------------------------------------------

def test_progress_bar_edges():
    assert report.progress_bar(0, XP_PER_LEVEL) == "░" * report.BAR_WIDTH
    assert report.progress_bar(XP_PER_LEVEL, XP_PER_LEVEL) == "█" * report.BAR_WIDTH
    assert report.progress_bar(50, 100) == "█" * 5 + "░" * 5
    # Нет шкалы (максимум) — рисуем заполненной, а не пустой.
    assert report.progress_bar(0, 0) == "█" * report.BAR_WIDTH


def test_limit_labels_are_human():
    assert report.limit_label(None) == ""
    assert report.limit_label("week") == "раз в неделю"
    assert report.limit_label("year") == "раз в год"
    assert report.limit_label("неведомый") == ""


def test_ordinal():
    assert report.ordinal(3) == "3-й"
    assert report.ordinal(10) == "10-й"


def test_xp_rules_text_lists_every_rule():
    text = report.xp_rules_text()
    for rule in XP_RULES.values():
        assert rule.title in text
    assert "раз в неделю" in text  # лимит «Разметил свободные дни»
    assert str(XP_PER_LEVEL) in text


@pytest.mark.asyncio
async def test_my_rank_is_silent_when_game_disabled(monkeypatch):
    _game(monkeypatch, False)
    assert await report.my_rank_text(None, user_id=1, display_name="Митян") is None


@pytest.mark.asyncio
async def test_my_rank_shows_rank_and_bar(monkeypatch):
    _game(monkeypatch, True)

    class _Session:
        async def get(self, *_a, **_k):
            return SimpleNamespace(xp=340, custom_rank_title=None)

    async def _rank_name(*_a, **_k):
        return "Терпила средней руки"

    async def _history(*_a, **_k):
        return []

    monkeypatch.setattr(report, "effective_rank_name", _rank_name)
    monkeypatch.setattr(report.xp, "daily_history", _history)
    text = await report.my_rank_text(_Session(), user_id=1, display_name="Митян")
    assert "Митян" in text
    # 340 XP — это 3-й ранг (пороги 0/100/300), внутри уровня 40/300: знаменатель
    # шкалы — цена текущего перехода, а не «100 для всех».
    assert "3-й ранг" in text and "Терпила средней руки" in text
    assert "до 4-й ранга" in text
    assert "40/300" in text


@pytest.mark.asyncio
async def test_my_rank_marks_maximum(monkeypatch):
    _game(monkeypatch, True)

    class _Session:
        async def get(self, *_a, **_k):
            # Кап прогрессивной шкалы — 4500 (порог 10 уровня).
            return SimpleNamespace(xp=4800, custom_rank_title=None)

    async def _rank_name(*_a, **_k):
        return "Сигма икона"

    async def _history(*_a, **_k):
        return []

    monkeypatch.setattr(report, "effective_rank_name", _rank_name)
    monkeypatch.setattr(report.xp, "daily_history", _history)
    text = await report.my_rank_text(_Session(), user_id=1, display_name="X")
    assert "Максимум взят" in text
    assert "300" in text  # престиж = 4800 − 4500


@pytest.mark.asyncio
async def test_ranks_chart_silent_when_game_disabled(monkeypatch):
    _game(monkeypatch, False)
    assert await report.ranks_chart_text(None) is None


@pytest.mark.asyncio
async def test_ranks_chart_lists_everyone_with_medals(monkeypatch):
    _game(monkeypatch, True)
    rows = [(1, "Митян", 250, None), (2, "Никита", 0, None), (3, "Сомов", None, None)]

    class _Rows:
        def all(self):
            return rows

    class _Session:
        async def execute(self, *_a, **_k):
            return _Rows()

    async def _supreme(*_a, **_k):
        return set()

    monkeypatch.setattr(report.achievements, "supreme_holders", _supreme)
    text = await report.ranks_chart_text(_Session())
    assert "🥇" in text and "🥈" in text
    # Участники без профиля тоже в списке — иначе чарт выглядит обрезанным.
    assert "Сомов" in text
    assert "1-й «Подшконарь»" in text


# --- Э5.4: команды зарегистрированы в каталоге -------------------------------

def test_game_commands_are_visible_in_group_help():
    visible = {c.cmd for c in commands_catalog.visible_for("group", is_admin=False)}
    assert {"rank", "ranks", "xp", "levels", "ach"} <= visible


# --- /ach: полный список ачивок с описаниями ---------------------------------

def test_tier_marks_show_which_anniversaries_are_taken():
    codes = catalog.tier_codes("chin_up")
    marks = report.tier_marks("chin_up", {codes[0]})
    assert "×10 ✅" in marks
    assert "×20 ▫️" in marks
    # У ачивки без юбилеев строки нет вообще — не рисуем пустое «юбилеи:».
    assert report.tier_marks("self_shot", set()) == ""


def test_is_collected_counts_a_tier_as_the_base():
    assert report._is_collected("chin_up", (10, 20), set()) is False
    assert report._is_collected("chin_up", (10, 20), {"chin_up:10"}) is True
    assert report._is_collected("chin_up", (10,), {"chin_up"}) is True


@pytest.mark.asyncio
async def test_ach_lists_every_base_achievement_with_description(monkeypatch):
    _game(monkeypatch, True)
    text = await report.achievements_guide_text(None)
    for base in catalog.base_achievements():
        if base.secret:
            continue
        assert base.title in text
        assert base.description in text
    assert "юбилейные ачивки:" in text
    # Секретную ачивку без личных отметок не спойлерим.
    assert "Скрытых ачивок: 1" in text
    assert "Верховный чухан" not in text


@pytest.mark.asyncio
async def test_ach_marks_own_progress_and_reveals_collected_secret(monkeypatch):
    _game(monkeypatch, True)

    async def _collected(_session, _user_id):
        return {"chin_up:10", "supreme_chukhan"}

    async def _progress(_session, _user_id):
        return {"chin_up": 12, COUNTER_WORM_TAMER: 0}

    monkeypatch.setattr(report.achievements, "collected_codes", _collected)
    monkeypatch.setattr(report.achievements, "progress", _progress)
    text = await report.achievements_guide_text(None, user_id=1)
    assert f"У тебя: <b>2</b>/{catalog.catalog_size()}" in text
    assert "×10 ✅" in text and "×20 ▫️" in text
    # Накопитель: «разовая» и «случаев» — разные строки (первый раз vs счётчик).
    assert "случаев: <b>12</b>" in text
    assert "разовая:" in text
    # Нулевой счётчик тоже показываем: это «трекер существует», а не “нет данных».
    assert "сейчас: <b>0</b>" in text
    # Полученную секретную ачивку показываем как обычную.
    assert "Верховный чухан" in text
    assert "Скрытых ачивок" not in text


@pytest.mark.asyncio
async def test_ach_shows_rarity_percent(monkeypatch):
    """Вместо списка обладателей в /ach — «имеют: N% (holders/total)»."""
    _game(monkeypatch, True)

    async def _empty(*_a, **_k):
        return {}

    async def _rarity(*_a, **_k):
        from app.services.game.achievements import AchievementStat

        return [AchievementStat("chin_up", 3, 6), AchievementStat("first_worm", 0, 6)]

    monkeypatch.setattr(report.achievements, "progress", _empty)
    monkeypatch.setattr(report.achievements, "collected_codes", _empty)
    monkeypatch.setattr(report.achievements, "rarity_stats", _rarity)
    text = await report.achievements_guide_text(object(), user_id=1)
    assert "имеют: <b>50%</b> (3/6)" in text
    # Ноль тоже показываем — это «ачивку пока никто не взял», а не пропуск.
    assert "имеют: <b>0%</b> (0/6)" in text


@pytest.mark.asyncio
async def test_ach_survives_rarity_failure(monkeypatch):
    """Сбой редкости не должен ронять подсказку (best-effort, как и всё остальное)."""
    _game(monkeypatch, True)

    async def _empty(*_a, **_k):
        return {}

    async def _boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(report.achievements, "progress", _empty)
    monkeypatch.setattr(report.achievements, "collected_codes", _empty)
    monkeypatch.setattr(report.achievements, "rarity_stats", _boom)
    text = await report.achievements_guide_text(object(), user_id=1)
    assert "Ачивки" in text


@pytest.mark.asyncio
async def test_ach_is_silent_when_game_disabled(monkeypatch):
    _game(monkeypatch, False)
    assert await report.achievements_guide_text(None, user_id=1) is None


def test_every_achievement_sits_in_exactly_one_group():
    """Разделы листа ачивок — часть каталога, а не отчёта.

    Без этой проверки новая ачивка молча уезжает в «Разное» (или, хуже,
    пропадает из листа) — а заметить это можно только глазами в живом чате.
    """
    codes = [code for _key, _title, group in catalog.GROUPS for code in group]
    assert len(codes) == len(set(codes)), "один код в двух разделах"
    base_codes = {a.code for a in catalog.base_achievements()}
    assert set(codes) == base_codes, (
        f"в каталоге без раздела: {sorted(base_codes - set(codes))}; "
        f"в разделах лишнее: {sorted(set(codes) - base_codes)}"
    )
    # Тиры наследуют раздел базовой ачивки, а неизвестный код не проваливается.
    assert catalog.group_of("chin_up:10") == catalog.group_of("chin_up")
    assert catalog.group_of("nope") == catalog.GROUP_FALLBACK


@pytest.mark.asyncio
async def test_ach_report_is_devided_into_labelled_blocks(monkeypatch):
    """Стена текста → разделы с воздухом (прод-фидбек 29.09)."""
    _game(monkeypatch, True)

    async def _empty(_session, _user_id):
        return {}

    monkeypatch.setattr(report.achievements, "progress", _empty)
    monkeypatch.setattr(report.achievements, "collected_codes", _empty)
    text = await report.achievements_guide_text(None, user_id=1)
    for _key, title, _codes in catalog.GROUPS:
        assert title in text, f"нет раздела «{title}»"
    # Каждый раздел отделён пустой строкой — иначе блоки слипаются в стену.
    assert "\n\n" in text
    # Ачивки одного раздела тоже разделены пустой строкой.
    assert "\n\n▫️" in text or "\n\n✅" in text
    # И всё это влезает в ОДНО сообщение Telegram.
    assert len(text) <= 4096


# --- /levels: своя стата + левелы участников ---------------------------------

@pytest.mark.asyncio
async def test_levels_text_has_stats_place_and_the_whole_chart(monkeypatch):
    _game(monkeypatch, True)
    # Митян — 0 XP (1-й ранг), чтобы имя ранга «Терпила» в тексте встречалось
    # ровно дважды: своя стата + своя строка чарта.
    rows = [
        (1, "Митян", 0, None),
        (2, "Серж-NEO", 340, "Терпила средней руки"),
        (3, "Сомов", 0, None),
    ]

    class _Session:
        async def get(self, *_a, **_k):
            return SimpleNamespace(xp=340, custom_rank_title=None)

    async def _rows(_session):
        return rows

    async def _rank_name(*_a, **_k):
        return "Терпила средней руки"

    async def _supreme(*_a, **_k):
        return set()

    async def _ach_count(*_a, **_k):
        return 7

    async def _history(*_a, **_k):
        return [SimpleNamespace(title="Сообщение в чате", points=12, count=12)]

    monkeypatch.setattr(report, "chart_rows", _rows)
    monkeypatch.setattr(report, "effective_rank_name", _rank_name)
    monkeypatch.setattr(report.achievements, "supreme_holders", _supreme)
    monkeypatch.setattr(report.achievements, "count_for_user", _ach_count)
    monkeypatch.setattr(report.xp, "daily_history", _history)

    text = await report.levels_text(_Session(), user_id=2, display_name="Серж-NEO")
    assert "3-й ранг" in text and "Терпила средней руки" in text
    assert "40/300" in text
    assert "Всего <b>340</b> XP" in text
    assert f"Уровень 3/{MAX_LEVEL}" in text
    assert "место 2 из 3" in text
    assert f"ачивок 7/{catalog.catalog_size()}" in text
    # Сегодняшний опыт показываем с источниками, а не просто числом.
    assert "+12</b> XP" in text
    assert "сообщение в чате ×12" in text
    assert "Левелы участников" in text and "🥇" in text and "Сомов" in text
    # В чарте — то же имя ранга, что и в своей стате (иначе «я тут другой»).
    assert text.count("Терпила средней руки") == 2


@pytest.mark.asyncio
async def test_levels_text_is_silent_when_game_disabled(monkeypatch):
    _game(monkeypatch, False)
    assert await report.levels_text(None, user_id=1, display_name="X") is None


def test_chart_lines_mark_medals_and_supreme_title():
    rows = [(1, "Митян", 950, None), (2, "Сомов", 0, None)]
    lines = report.chart_lines(rows, {1})
    assert "🥇" in lines[0] and "🥈" in lines[1]
    # Спец-ранг перекрывает ранг за уровень — в чате и в мини-аппе одинаково.
    assert "Верховный чухан" in lines[0]
    assert "Сомов" in lines[1]
    assert report.chart_lines([], set()) == ["⚠️ В чате пока никто не зарегистрирован."]


def test_chart_lines_prefer_custom_title_over_level_name():
    # 4500 XP — кап прогрессивной шкалы (10-й ранг).
    rows = [(1, "Митян", 4500, "Король мемов"), (2, "Сомов", 4500, None)]
    lines = report.chart_lines(rows, set())
    assert "Король мемов" in lines[0]
    assert "Сигма икона" in lines[1]  # максимум, у кого нет своего ранга
    # Спец-ранг всё равно главнее своего названия.
    supreme = report.chart_lines(rows, {1})
    assert "Верховный чухан" in supreme[0]


# --- Э10.3: валидация праздников --------------------------------------------

def test_validate_month_day_accepts_valid_dates():
    for month, day in ((1, 1), (2, 29), (12, 31)):
        holidays.validate_month_day(month, day)  # не бросает


@pytest.mark.parametrize(
    "month,day,code",
    [
        (0, 1, "holiday_month_invalid"),
        (13, 1, "holiday_month_invalid"),
        (4, 31, "holiday_day_invalid"),
        (2, 30, "holiday_day_invalid"),
        (1, 0, "holiday_day_invalid"),
    ],
)
def test_validate_month_day_rejects(month, day, code):
    with pytest.raises(holidays.HolidayError) as exc:
        holidays.validate_month_day(month, day)
    assert exc.value.code == code


def test_normalize_message_trims_and_requires_text():
    assert holidays.normalize_message("  Ура  ") == "Ура"
    assert len(holidays.normalize_message("x" * 500)) == holidays.MAX_HOLIDAY_MESSAGE
    with pytest.raises(holidays.HolidayError):
        holidays.normalize_message("   ")


@pytest.mark.asyncio
async def test_add_holiday_rejects_taken_date():
    class _Session:
        async def scalar(self, *_a, **_k):
            return 1  # дата занята

    with pytest.raises(holidays.HolidayError) as exc:
        await holidays.add_holiday(_Session(), month=1, day=1, message="Новый год")
    assert exc.value.code == "holiday_date_taken"


# --- Э10.3: ручки -----------------------------------------------------------

def _holiday_row() -> GameHoliday:
    return GameHoliday(
        id=7, month=1, day=1, message="Новый год", enabled=True,
        created_by_user_id=None,
    )


def _user():
    return SimpleNamespace(id=1, telegram_id=777, display_name="Серж-NEO")


@pytest.mark.asyncio
async def test_holidays_list_empty_when_game_disabled(monkeypatch):
    _game(monkeypatch, False)
    out = await routes_game.holidays_list(None, _user())
    assert out.items == [] and out.can_manage is False


@pytest.mark.asyncio
async def test_holidays_list_reports_manage_rights(monkeypatch):
    _game(monkeypatch, True)

    async def _gate(*_a, **_k):
        return SimpleNamespace(allowed=True, required_level=6)

    async def _list(*_a, **_k):
        return [_holiday_row()]

    monkeypatch.setattr(routes_game.gates, "check_feature", _gate)
    monkeypatch.setattr(routes_game.holidays, "list_holidays", _list)
    out = await routes_game.holidays_list(None, _user())
    assert out.can_manage is True
    assert out.required_level == 6
    assert [h.message for h in out.items] == ["Новый год"]


@pytest.mark.asyncio
async def test_admin_manages_holidays_without_the_rank(monkeypatch):
    """Админ из ADMIN_TG_IDS правит праздники даже без 6 ранга (иначе блок не открыть)."""
    _game(monkeypatch, True)

    async def _deny(*_a, **_k):
        return SimpleNamespace(allowed=False, required_level=6)

    async def _list(*_a, **_k):
        return [_holiday_row()]

    monkeypatch.setattr(
        routes_game, "get_settings", lambda: SimpleNamespace(admin_tg_id_set={777})
    )
    monkeypatch.setattr(routes_game.gates, "check_feature", _deny)
    monkeypatch.setattr(routes_game.holidays, "list_holidays", _list)
    out = await routes_game.holidays_list(None, _user())
    assert out.can_manage is True


@pytest.mark.asyncio
async def test_admin_holiday_add_skips_the_rank_gate(monkeypatch):
    _game(monkeypatch, True)

    async def _forbidden(*_a, **_k):
        raise AssertionError("гейт не должен вызываться для админа")

    async def _add(*_a, **_k):
        return _holiday_row()

    monkeypatch.setattr(
        routes_game, "get_settings", lambda: SimpleNamespace(admin_tg_id_set={777})
    )
    monkeypatch.setattr(routes_game.gates, "require_feature", _forbidden)
    monkeypatch.setattr(routes_game.holidays, "add_holiday", _add)
    body = routes_game.HolidayCreate(month=1, day=1, message="Новый год")
    out = await routes_game.holiday_add(body, None, _user())
    assert out.message == "Новый год"


@pytest.mark.asyncio
async def test_holiday_add_blocked_when_game_disabled(monkeypatch):
    _game(monkeypatch, False)
    body = routes_game.HolidayCreate(month=5, day=9, message="День победы")
    with pytest.raises(HTTPException) as exc:
        await routes_game.holiday_add(body, None, _user())
    assert exc.value.status_code == 403
    assert exc.value.detail == "game_disabled"


@pytest.mark.asyncio
async def test_holiday_add_requires_rank(monkeypatch):
    _game(monkeypatch, True)

    async def _deny(*_a, **_k):
        raise HTTPException(403, "rank_required:6")

    monkeypatch.setattr(routes_game.gates, "require_feature", _deny)
    body = routes_game.HolidayCreate(month=5, day=9, message="День победы")
    with pytest.raises(HTTPException) as exc:
        await routes_game.holiday_add(body, None, _user())
    assert exc.value.detail == "rank_required:6"


@pytest.mark.asyncio
async def test_holiday_add_maps_taken_date_to_409(monkeypatch):
    _game(monkeypatch, True)

    async def _allow(*_a, **_k):
        return None

    async def _taken(*_a, **_k):
        raise holidays.HolidayError("holiday_date_taken")

    monkeypatch.setattr(routes_game.gates, "require_feature", _allow)
    monkeypatch.setattr(routes_game.holidays, "add_holiday", _taken)
    body = routes_game.HolidayCreate(month=1, day=1, message="Новый год")
    with pytest.raises(HTTPException) as exc:
        await routes_game.holiday_add(body, None, _user())
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_holiday_add_maps_bad_input_to_400(monkeypatch):
    _game(monkeypatch, True)

    async def _allow(*_a, **_k):
        return None

    async def _bad(*_a, **_k):
        raise holidays.HolidayError("holiday_day_invalid")

    monkeypatch.setattr(routes_game.gates, "require_feature", _allow)
    monkeypatch.setattr(routes_game.holidays, "add_holiday", _bad)
    body = routes_game.HolidayCreate(month=2, day=30, message="X")
    with pytest.raises(HTTPException) as exc:
        await routes_game.holiday_add(body, None, _user())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_holiday_delete_404_when_missing(monkeypatch):
    _game(monkeypatch, True)

    async def _allow(*_a, **_k):
        return None

    async def _gone(*_a, **_k):
        return False

    monkeypatch.setattr(routes_game.gates, "require_feature", _allow)
    monkeypatch.setattr(routes_game.holidays, "remove_holiday", _gone)
    with pytest.raises(HTTPException) as exc:
        await routes_game.holiday_delete(5, None, _user())
    assert exc.value.status_code == 404
