"""Схемы скрытых ачивок сотрудника.

Общие для двух ручек — «мои ачивки» (`api/routes_hr.py`) и «ачивки сотрудника»
для руководителя (`api/routes_hr_admin.py`), — поэтому вынесены в `schemas/`, а
не объявлены внутри роутов: ответ обязан быть одинаковым у обеих ручек, иначе
мини-апп придётся учить двум форматам.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.services.hr_achievements import AchievementView


class AchievementOut(BaseModel):
    """Выданная ачивка."""

    code: str
    title: str
    emoji: str
    awarded_at: datetime


class NextGoalOut(BaseModel):
    """Ближайший невзятый порог: «сколько осталось»."""

    code: str
    title: str
    emoji: str
    metric: str
    threshold: int
    done: int
    left: int
    text: str


class AchievementsOut(BaseModel):
    """Блок личного прогресса в профиле.

    `visible=false` — блок скрыт (обычный сотрудник). Тогда остальные поля
    пустые, и это не «ошибка», а нормальное состояние системы: решение о
    публичной видимости ещё не принято.
    """

    model_config = ConfigDict(from_attributes=True)

    visible: bool
    awarded: list[AchievementOut] = []
    stats: dict[str, int] = {}
    next_goals: list[NextGoalOut] = []
    note: str = ""


def to_out(view: AchievementView) -> AchievementsOut:
    """Единственная точка превращения сервисного вью в ответ обеих ручек."""
    return AchievementsOut(
        visible=view.visible,
        awarded=[
            AchievementOut(
                code=a.code, title=a.title, emoji=a.emoji, awarded_at=a.awarded_at
            )
            for a in view.awarded
        ],
        stats=view.stats.as_dict() if view.visible else {},
        next_goals=[
            NextGoalOut(
                code=g.code,
                title=g.title,
                emoji=g.emoji,
                metric=g.metric,
                threshold=g.threshold,
                done=g.done,
                left=g.left,
                text=g.text(),
            )
            for g in view.next_goals
        ],
        note=view.note,
    )
