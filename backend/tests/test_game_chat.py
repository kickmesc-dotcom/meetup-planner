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
from app.services.game import holidays, report
from app.services.game.config import XP_PER_LEVEL, XP_RULES


def _game(monkeypatch, enabled: bool) -> None:
    async def _flag(_session):
        return enabled

    monkeypatch.setattr(report, "is_game_enabled", _flag)
    monkeypatch.setattr(routes_game, "is_game_enabled", _flag)


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
    # 340 XP — это уже 4 ранг (3-й начинался на 200), внутри уровня 40/100.
    assert "4-й ранг" in text and "Терпила средней руки" in text
    assert "до 5-й ранга" in text
    assert "40/100" in text


@pytest.mark.asyncio
async def test_my_rank_marks_maximum(monkeypatch):
    _game(monkeypatch, True)

    class _Session:
        async def get(self, *_a, **_k):
            return SimpleNamespace(xp=1200, custom_rank_title=None)

    async def _rank_name(*_a, **_k):
        return "Сигма икона"

    async def _history(*_a, **_k):
        return []

    monkeypatch.setattr(report, "effective_rank_name", _rank_name)
    monkeypatch.setattr(report.xp, "daily_history", _history)
    text = await report.my_rank_text(_Session(), user_id=1, display_name="X")
    assert "Максимум взят" in text
    assert "300" in text  # престиж = 1200 − 900


@pytest.mark.asyncio
async def test_ranks_chart_silent_when_game_disabled(monkeypatch):
    _game(monkeypatch, False)
    assert await report.ranks_chart_text(None) is None


@pytest.mark.asyncio
async def test_ranks_chart_lists_everyone_with_medals(monkeypatch):
    _game(monkeypatch, True)
    rows = [(1, "Митян", 250), (2, "Никита", 0), (3, "Сомов", None)]

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
    assert {"rank", "ranks", "xp"} <= visible


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
