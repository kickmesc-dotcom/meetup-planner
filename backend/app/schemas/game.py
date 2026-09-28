"""GHG10 Э5: схемы поверхностей игровой системы (профиль, чарты).

Всё, что отдаётся фронту — уже готовое к отрисовке: ранг с цветом и жирностью,
прогресс/престиж, открытые фичи, уведомление о левел-апе и список ачивок.
Клиенту не нужно знать числа из `config.py` — он их не пересчитывает.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RankOut(BaseModel):
    """Ранг за уровень: имя + как рисовать плашку (фон + контраст — на клиенте)."""

    level: int
    name: str
    hex: str
    bold: bool = False


class FeatureOut(BaseModel):
    """Открытая возможность (для уведомления о левел-апе и подсказки в профиле)."""

    code: str
    title: str


class LevelUpOut(BaseModel):
    """Непоказанное уведомление: какой ранг был, какой стал, что открылось."""

    from_level: int
    from_rank: str
    to_level: int
    to_rank: str
    unlocked: list[FeatureOut]


class DailyEventOut(BaseModel):
    """Строка дневной истории: «сообщения ×12 → +12 XP»."""

    event: str
    title: str
    points: int
    count: int


class AchievementItemOut(BaseModel):
    """Одна ачивка для листа профиля.

    `progress`/`threshold`/`tiers` — сколько накоплено и до чего; `None`/пусто
    у разовых ачивок без счётчика. `collected` — взята ли уже (по базовому коду).
    """

    code: str
    title: str
    description: str
    icon: str
    points: int
    kind: str
    collected: bool = False
    unlocked_at: datetime | None = None
    progress: int | None = None
    threshold: int | None = None
    tiers: list[int] = []


class XpRuleOut(BaseModel):
    """«За что дают опыт» — кнопка в профиле (требование задания)."""

    code: str
    title: str
    points: int
    limit: str | None = None


class GameProfileOut(BaseModel):
    """Полный игровой профиль игрока. `enabled=False` → остальное не заполнено."""

    enabled: bool
    xp: int = 0
    level: int = 1
    max_level: int = 10
    rank: RankOut | None = None
    rank_name: str = ""
    # Спец-ранг «Верховный чухан» приоритетнее ранга за уровень (Э3.4).
    supreme: bool = False
    custom_rank_title: str | None = None
    # Э8.7: своё имя внутри приложения (ранг 8).
    custom_name: str | None = None
    # Э8.5: своя аватарка внутри мини-аппа (ранг 6), хранится на `users`.
    avatar_manual_url: str | None = None
    xp_into_level: int = 0
    xp_to_next: int | None = None
    at_max: bool = False
    prestige: int = 0
    unlocked: list[FeatureOut] = []
    level_up: LevelUpOut | None = None
    today: list[DailyEventOut] = []
    today_total: int = 0
    achievements: list[AchievementItemOut] = []
    xp_rules: list[XpRuleOut] = []


class GameCustomizePatch(BaseModel):
    """Правка «своего» в профиле (Э8.5/8.7/10). Каждое поле гейтится отдельно.

    `None` в значении = очистить; отсутствие ключа = не трогать (эндпоинт
    смотрит `model_fields_set`).
    """

    custom_name: str | None = Field(None, max_length=64)
    custom_rank_title: str | None = Field(None, max_length=32)
    avatar_manual_url: str | None = Field(None, max_length=512)


class AchievementHolderOut(BaseModel):
    """Строка чарта обладателей ачивок (Э5.3)."""

    user_id: int
    count: int


class RankRowOut(BaseModel):
    """Строка чарта рангов: у кого какой уровень/ранг (Э5.4)."""

    user_id: int
    xp: int
    level: int
    rank_name: str
    hex: str
    bold: bool = False
    supreme: bool = False
