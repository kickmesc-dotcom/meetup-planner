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


class HolidayOut(BaseModel):
    """Праздник: ежегодная дата (месяц+день) + текст поздравления (Э10)."""

    id: int
    month: int
    day: int
    message: str
    enabled: bool = True


class HolidayCreate(BaseModel):
    """Добавление праздника. Правку сообщения не даём: проще удалить и завести."""

    month: int = Field(..., ge=1, le=12)
    day: int = Field(..., ge=1, le=31)
    message: str = Field(..., max_length=200)


class HolidaysOut(BaseModel):
    """Список праздников + можно ли текущему юзеру их править (с 6 ранга)."""

    can_manage: bool = False
    required_level: int | None = None
    items: list[HolidayOut] = []


class DonationIn(BaseModel):
    """Подарок опыта имениннику (Э11).

    Получателя можно задать и внутренним `user_id` (так зовёт мини-апп — он
    оперирует участниками из `/api/users`), и `telegram_id` (удобно из админки
    и отладки). Достаточно одного.
    """

    user_id: int | None = None
    telegram_id: int | None = None


class GameContrabandWord(BaseModel):
    """Слово-контрабанда: чьё, сколько платит и в каких формулировках ловится.

    `owner_tg_id` — основной способ привязки (надёжен при смене имени), `owner`
    — подпись для чата и запасной путь (поиск по display_name). `variants` —
    регулярки, `labels` — те же формулировки человеческим языком: показывать
    людям регулярку нельзя, а объяснить, что именно ловится, нужно.
    """

    word: str = Field(..., min_length=2, max_length=40)
    owner: str | None = Field(None, max_length=60)
    owner_tg_id: int | None = None
    variants: list[str] = []
    labels: list[str] = []
    xp: int = Field(5, ge=0, le=1000)
    note: str | None = Field(None, max_length=80)
    enabled: bool = True
    chance: int | None = Field(None, ge=0, le=100)


class GameSocialOut(BaseModel):
    """Э13: состояние четырёх «социальных» фич одним ответом.

    `unresolved_owners` — владельцы слов, которых нет среди участников: без
    этого списка «контрабанда не срабатывает» выглядело бы как поломка, хотя
    на деле слово просто некому начислить.
    """

    digest_enabled: bool = False
    digest_interval_hours: int = 6
    digest_pending: int = 0
    memorial_enabled: bool = True
    memorial_silence_days: int = 21
    memorial_repeat_days: int = 7
    events_enabled: bool = True
    events_chance_percent: int = 60
    events_max_per_day: int = 2
    events_min_gap_hours: int = 6
    events_open: int = 0
    contraband_enabled: bool = True
    contraband_chance_percent: int = 100
    contraband_daily_cap: int = 1
    contraband_custom_registry: bool = False
    contraband_words: list[GameContrabandWord] = []
    unresolved_owners: list[str] = []


class GameSocialIn(BaseModel):
    """Частичная правка: что не передали — не трогаем.

    `contraband_words` заменяет реестр целиком (пустой список — «правил нет», а
    не «верни дефолты»: иначе вычистить реестр было бы невозможно).
    """

    digest_enabled: bool | None = None
    digest_interval_hours: int | None = None
    memorial_enabled: bool | None = None
    memorial_silence_days: int | None = Field(None, ge=1, le=365)
    memorial_repeat_days: int | None = Field(None, ge=1, le=365)
    events_enabled: bool | None = None
    events_chance_percent: int | None = Field(None, ge=0, le=100)
    events_max_per_day: int | None = Field(None, ge=0, le=50)
    events_min_gap_hours: int | None = Field(None, ge=0, le=168)
    contraband_enabled: bool | None = None
    contraband_chance_percent: int | None = Field(None, ge=0, le=100)
    contraband_daily_cap: int | None = Field(None, ge=0, le=100)
    contraband_words: list[GameContrabandWord] | None = None


class GameDigestFlushOut(BaseModel):
    """Сколько записей журнала уехало в чат по кнопке «отправить сейчас»."""

    sent: int = 0


class DonationOut(BaseModel):
    """Итог доната: код + балансы, чтобы клиент сразу показал новое состояние.

    `code` при успехе — `ok`, а отказы уезжают как HTTP-ошибки с тем же кодом
    в `detail` (фронт переводит их своим `humanizeApiError`).
    """

    ok: bool = False
    code: str = ""
    amount: int = 0
    donor_xp: int = 0
    recipient_xp: int = 0
    recipient_name: str = ""
