"""Схемы KPI-геймификации смены.

Один формат на обе ручки — личную (`/api/kpi`) и админскую (`/api/admin/kpi`):
админка показывает ровно то же звание и тот же опыт, что видит сотрудник, иначе
правила настройки и карточка начинали бы жить разной жизнью.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.hr_kpi import (
    MAX_MIN_XP,
    MAX_XP_WEIGHT,
    Candidate,
    Counts,
    MyKpi,
    Rules,
    Winner,
)


class CountsOut(BaseModel):
    """Следы работы за окно: то, из чего складывается опыт."""

    checklist_items: int
    shifts_done: int
    tasks_done: int
    tasks_on_time: int


class RulesOut(BaseModel):
    """Веса опыта, как их сейчас видит сервер."""

    xp_checklist_item: int
    xp_shift_done: int
    xp_task: int
    xp_on_time: int
    min_xp_winner: int


class RulesPatch(BaseModel):
    """Частичная правка весов из админки (все поля опциональны)."""

    xp_checklist_item: int | None = Field(None, ge=0, le=MAX_XP_WEIGHT)
    xp_shift_done: int | None = Field(None, ge=0, le=MAX_XP_WEIGHT)
    xp_task: int | None = Field(None, ge=0, le=MAX_XP_WEIGHT)
    xp_on_time: int | None = Field(None, ge=0, le=MAX_XP_WEIGHT)
    min_xp_winner: int | None = Field(None, ge=0, le=MAX_MIN_XP)


class WinnerOut(BaseModel):
    """Номинация «сотрудник недели»."""

    employee_id: int
    display_name: str
    department: str | None
    xp: int
    tasks_done: int


class RankOut(BaseModel):
    code: str
    title: str
    emoji: str
    threshold: int


class MyKpiOut(BaseModel):
    """Личная карточка опыта: всё время, текущая неделя, место в рейтинге."""

    xp: int
    rank: RankOut
    next_rank: RankOut | None
    left: int
    percent: int
    week_xp: int
    week_counts: CountsOut
    week_place: int | None
    week_total: int
    employee_of_week: WinnerOut | None
    rules: RulesOut


class LeaderRowOut(BaseModel):
    """Строка недельного рейтинга."""

    place: int
    employee_id: int
    display_name: str
    department: str | None
    xp: int
    counts: CountsOut


class KpiAdminOut(BaseModel):
    """Админский экран: правила + рейтинг недели + номинант."""

    week_start: str
    week_end: str
    rules: RulesOut
    leaderboard: list[LeaderRowOut]
    employee_of_week: WinnerOut | None


def _counts_out(counts: Counts) -> CountsOut:
    return CountsOut(**counts.as_dict())


def _rules_out(rules: Rules) -> RulesOut:
    return RulesOut(**rules.as_dict())


def to_winner_out(winner: Winner | None) -> WinnerOut | None:
    if winner is None:
        return None
    return WinnerOut(
        employee_id=winner.employee_id,
        display_name=winner.display_name,
        department=winner.department,
        xp=winner.xp,
        tasks_done=winner.tasks_done,
    )


def to_my_out(data: MyKpi) -> MyKpiOut:
    progress = data.progress
    rank = RankOut(
        code=progress.rank.code,
        title=progress.rank.title,
        emoji=progress.rank.emoji,
        threshold=progress.rank.threshold,
    )
    nxt = progress.next_rank
    return MyKpiOut(
        xp=progress.xp,
        rank=rank,
        next_rank=None
        if nxt is None
        else RankOut(code=nxt.code, title=nxt.title, emoji=nxt.emoji, threshold=nxt.threshold),
        left=progress.left,
        percent=progress.percent,
        week_xp=data.week_xp,
        week_counts=_counts_out(data.week_counts),
        week_place=data.week_place,
        week_total=data.week_total,
        employee_of_week=to_winner_out(data.winner),
        rules=_rules_out(data.rules),
    )


def to_leaderboard(candidates: list[Candidate]) -> list[LeaderRowOut]:
    return [
        LeaderRowOut(
            place=index,
            employee_id=c.employee_id,
            display_name=c.display_name,
            department=c.department,
            xp=c.xp,
            counts=_counts_out(c.counts),
        )
        for index, c in enumerate(candidates, start=1)
    ]


__all__ = [
    "CountsOut",
    "KpiAdminOut",
    "LeaderRowOut",
    "MyKpiOut",
    "RankOut",
    "RulesOut",
    "RulesPatch",
    "WinnerOut",
    "to_leaderboard",
    "to_my_out",
    "to_winner_out",
]
