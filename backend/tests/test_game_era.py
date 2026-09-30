"""GHG10: эра геймификации и сводка редкости ачивок.

Два требования оператора, которые проверяются здесь:

1. **«Отсчёт с чистого листа».** Счётчики накопительных ачивок считают только
   записи С МОМЕНТА внедрения геймификации (`config.ACHIEVEMENTS_ERA_START`),
   а не всю историю чата. Топы/опыт при этом не обнуляются — их мы не трогаем.
2. **«Вместо обладателей — сколько % участников имеют такую».** `rarity_stats`
   сворачивает тиры (×10/×20) в базовый код, чтобы ачивка не считалась дважды,
   и делит на число участников.

Проверяем не «результат подменённой сессии», а сам SQL: что дата-эра реально
попала в `WHERE` каждой счётной функции. Иначе регресс («забыли фильтр в одной
из пяти») прошёл бы молча.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.dialects import postgresql

from app.services.game import achievements
from app.services.game.achievements import AchievementStat
from app.services.game.config import ACHIEVEMENTS_ERA_START

_ERA_ISO = ACHIEVEMENTS_ERA_START.date().isoformat()


class _CaptureSession:
    """Сессия-заглушка: запоминает переданный `scalar(stmt)` и отдаёт 0."""

    def __init__(self) -> None:
        self.statements: list = []

    async def scalar(self, stmt=None, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
        if stmt is not None:
            self.statements.append(stmt)
        return 0


def _sql(stmt) -> str:  # noqa: ANN001
    return str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


_COUNTERS = (
    ("loser", achievements.count_losers, "loser_rolls"),
    ("started_rolls", achievements.count_started_rolls, "loser_rolls"),
    ("chukhan", achievements.count_chukhan, "weekly_chukhan"),
    ("polls", achievements.count_polls, "polls"),
    ("nominations", achievements.count_nominations, "game_nominations"),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("label,func,table", _COUNTERS, ids=[c[0] for c in _COUNTERS])
async def test_every_counter_is_scoped_to_the_era(label, func, table):
    session = _CaptureSession()
    await func(session, 1)
    assert session.statements, f"{label}: запрос не выполнен"
    sql = _sql(session.statements[0])
    assert table in sql
    assert _ERA_ISO in sql, f"{label}: в WHERE нет даты эры геймификации"


def test_era_is_a_timezone_aware_utc_moment():
    """Дата-эра должна быть aware UTC — иначе сравнение с тимстампами в БД врёт."""
    assert ACHIEVEMENTS_ERA_START.tzinfo is not None
    assert ACHIEVEMENTS_ERA_START.utcoffset().total_seconds() == 0
    # Страховка: если эру случайно сдвинут в прошлое, тест заметит.
    assert ACHIEVEMENTS_ERA_START > datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_achievement_stat_percent_rounds_and_guards_zero():
    assert AchievementStat("chin_up", 3, 6).percent == 50
    assert AchievementStat("chin_up", 1, 3).percent == 33
    assert AchievementStat("chin_up", 0, 6).percent == 0
    # Пустой чат — не деление на ноль.
    assert AchievementStat("chin_up", 0, 0).percent == 0


@pytest.mark.asyncio
async def test_rarity_stats_folds_tiers_into_the_base_code():
    """Тир (×10) не считается отдельной ачивкой в сводке редкости."""

    class _Rows:
        def __init__(self, rows):  # noqa: ANN001
            self._rows = rows

        def all(self):  # noqa: ANN201
            return list(self._rows)

    class _Session:
        async def scalar(self, *_a, **_k):  # noqa: ANN002, ANN003
            return 4

        async def execute(self, *_a, **_k):  # noqa: ANN002, ANN003
            # У одного человека есть и база, и тир — в сводке это одно «есть».
            return _Rows([("chin_up", 1), ("chin_up:10", 1), ("chin_up:20", 1)])

    stats = await achievements.rarity_stats(_Session())
    chin = next(s for s in stats if s.code == "chin_up")
    assert chin.holders == 1
    assert chin.total == 4
    assert chin.percent == 25
