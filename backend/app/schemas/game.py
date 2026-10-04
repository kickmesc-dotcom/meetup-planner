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
    """Открытая возможность (для уведомления о левел-апе и подсказки в профиле).

    `description` — человеческое «куда зайти, что нажать, что будет», а не
    технический термин (требование оператора): с ним уведомление о новом ранге
    объясняет способность сразу, без похода в справку.
    """

    code: str
    title: str
    description: str = ""


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
    # Какие юбилейные тиры уже взяты. База («разовая») и каждый юбилей ×N —
    # РАЗНЫЕ ачивки, поэтому UI показывает их отдельно.
    collected_tiers: list[int] = []


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
    # Э18: собраны 100% ачивок → особый титул «Идеальный червь».
    completionist: bool = False
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


class AchievementStatOut(BaseModel):
    """Сводка по одной ачивке: сколько участников её имеют.

    Задание: «вместо обладателей ачивок — крохотная сводка, сколько % участников
    имеют такую». Поэтому вместо списка имён отдаём число/процент: держать в
    ответе персональные данные для «у кого что» больше не нужно.
    """

    code: str
    title: str
    icon: str
    holders: int
    total: int
    percent: int


class RankRowOut(BaseModel):
    """Строка чарта рангов: у кого какой уровень/ранг (Э5.4)."""

    user_id: int
    xp: int
    level: int
    rank_name: str
    hex: str
    bold: bool = False
    supreme: bool = False


class GuestAchievementOut(BaseModel):
    """Короткая строка собранной ачивки для чужого профиля (без прогресса/тиров)."""

    code: str
    title: str
    icon: str


class GuestProfileOut(BaseModel):
    """Э19: чужой профиль «глазами гостя» — только факты, без настроек.

    В отличие от `GameProfileOut` (свой профиль): нет правил XP, кастомизации,
    истории дня и уведомлений левел-апа — гость смотрит, но не правит.
    """

    enabled: bool = True
    telegram_id: int
    user_id: int
    name: str
    avatar_url: str | None = None
    level: int = 1
    rank: RankOut | None = None
    rank_name: str = ""
    xp: int = 0
    prestige: int = 0
    supreme: bool = False
    completionist: bool = False
    loser_count: int = 0
    chukhan_count: int = 0
    # Место в чарте рангов (1 — первый) и сколько всего игроков.
    rank_position: int | None = None
    ranks_total: int = 0
    achievements_collected: int = 0
    achievements_total: int = 0
    achievements: list[GuestAchievementOut] = []


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
    # Э19: режим публикации ачивок — "instant" (как раньше), "pool" (буфер)
    # или "hybrid" (днём сразу, ночью сводкой). Дефолт — "hybrid".
    achievements_post_mode: str = "hybrid"
    achievements_pool_interval_hours: int = 4
    achievements_pool_morning_hour: int = 10
    achievements_pool_min_items: int = 1
    achievements_pool_gap_minutes: int = 30
    achievements_pool_pending: int = 0
    memorial_enabled: bool = True
    memorial_silence_days: int = 21
    memorial_repeat_days: int = 7
    events_enabled: bool = True
    events_chance_percent: int = 60
    events_max_per_day: int = 2
    events_min_per_day: int = 1
    events_min_gap_hours: int = 6
    # Дневное окно публикации событий (локальное время чата, UTC+3).
    events_day_start_hour: int = 10
    events_day_end_hour: int = 22
    events_open: int = 0
    contraband_enabled: bool = True
    contraband_chance_percent: int = 100
    contraband_daily_cap: int = 1
    contraband_custom_registry: bool = False
    contraband_words: list[GameContrabandWord] = []
    unresolved_owners: list[str] = []
    # Э19: единый бюджет дня — максимум авто-постов бота за сутки (0 — без лимита).
    activity_max_posts_per_day: int = 6
    # Э19: живые часы (локальное время чата) — днём ачивки в hybrid-режиме
    # выдаются сразу, ночью копятся в буфер.
    activity_day_start_hour: int = 10
    activity_day_end_hour: int = 22
    # Э14: голосовые задания.
    voice_enabled: bool = True
    voice_poll_enabled: bool = False
    voice_min_gap_hours: int = 48
    # Э19+: альтернативный режим награды — с шансом 50/50 «только первому».
    voice_alt_mode_enabled: bool = False
    voice_open: int = 0
    # Э20: режим вывода бота в основной чат — "normal" | "achievements" | "all".
    chat_output_mode: str = "normal"


class GameSocialIn(BaseModel):
    """Частичная правка: что не передали — не трогаем.

    `contraband_words` заменяет реестр целиком (пустой список — «правил нет», а
    не «верни дефолты»: иначе вычистить реестр было бы невозможно).
    """

    digest_enabled: bool | None = None
    digest_interval_hours: int | None = None
    achievements_post_mode: str | None = None
    achievements_pool_interval_hours: int | None = Field(None, ge=1, le=24)
    achievements_pool_morning_hour: int | None = Field(None, ge=0, le=23)
    achievements_pool_min_items: int | None = Field(None, ge=0, le=100)
    achievements_pool_gap_minutes: int | None = Field(None, ge=0, le=240)
    memorial_enabled: bool | None = None
    memorial_silence_days: int | None = Field(None, ge=1, le=365)
    memorial_repeat_days: int | None = Field(None, ge=1, le=365)
    events_enabled: bool | None = None
    events_chance_percent: int | None = Field(None, ge=0, le=100)
    events_max_per_day: int | None = Field(None, ge=0, le=50)
    events_min_per_day: int | None = Field(None, ge=0, le=50)
    events_min_gap_hours: int | None = Field(None, ge=0, le=168)
    events_day_start_hour: int | None = Field(None, ge=0, le=23)
    events_day_end_hour: int | None = Field(None, ge=0, le=24)
    contraband_enabled: bool | None = None
    contraband_chance_percent: int | None = Field(None, ge=0, le=100)
    contraband_daily_cap: int | None = Field(None, ge=0, le=100)
    contraband_words: list[GameContrabandWord] | None = None
    activity_max_posts_per_day: int | None = Field(None, ge=0, le=200)
    activity_day_start_hour: int | None = Field(None, ge=0, le=23)
    activity_day_end_hour: int | None = Field(None, ge=0, le=24)
    voice_enabled: bool | None = None
    voice_poll_enabled: bool | None = None
    voice_min_gap_hours: int | None = Field(None, ge=1, le=720)
    voice_alt_mode_enabled: bool | None = None
    chat_output_mode: str | None = None


class DeliveryFeatureOut(BaseModel):
    """GHG11: одна фича в единой модели доставки."""

    key: str
    label: str
    module: str = "general"
    mode: str = "chat"
    hint: str = ""


class DeliveryOut(BaseModel):
    """Состояние мастер-свитчеров и всех фич.

    `master_*` — одно из четырёх состояний либо `custom` (фичи разъехались).
    """

    modes: list[str]
    mode_labels: dict[str, str]
    master_general: str = "chat"
    master_achievements: str = "chat"
    features: list[DeliveryFeatureOut] = []


class DeliveryIn(BaseModel):
    """Частичная правка: мастер(ы) и/или одна фича и/или пачка фич."""

    master_general: str | None = None
    master_achievements: str | None = None
    feature: str | None = None
    mode: str | None = None
    features: dict[str, str] | None = None


class DeliveryApplyIn(BaseModel):
    """Применить один режим ко ВСЕМ фичам обоих мастеров."""

    mode: str


class FeedItemOut(BaseModel):
    """Э20: одна запись ленты активности в мини-аппе.

    Источник отдаёт готовыми поля (см. `services/game/feed.py`): тип, иконка,
    текст, кто и когда. `user_id` — внутренний id для перехода в чужой профиль.
    """

    id: str
    source: str = ""
    kind: str = "other"
    icon: str = "📌"
    title: str = ""
    text: str = ""
    at: datetime
    user_id: int | None = None
    user_name: str | None = None
    user_telegram_id: int | None = None
    avatar_url: str | None = None
    # Э22: подробности для раскрытия карточки в ленте — «за что дана ачивка»,
    # условия и окно голосового задания, треки подборки с лайками. Свободный
    # словарь: у разных типов записей разный состав, фронт читает по `kind`.
    detail: dict | None = None


class FeedOut(BaseModel):
    """Лента + признак наличия следующей страницы."""

    enabled: bool = True
    items: list[FeedItemOut] = []
    next_offset: int | None = None
    # Э21: доступные типы записей (для чипов-фильтров на фронте).
    kinds: list[str] = []


class GameDigestFlushOut(BaseModel):
    """Сколько записей журнала уехало в чат по кнопке «отправить сейчас»."""

    sent: int = 0


class GameObservabilityRow(BaseModel):
    """Строка разбивки опыта: за какое событие сколько XP набежало за окно."""

    event: str
    title: str
    points: int = 0
    count: int = 0


class GameObservabilityOut(BaseModel):
    """Э19: сводка активности игры за окно — «не спамит ли бот», без чтения чата."""

    window_days: int = 7
    events: int = 0
    events_answered: int = 0
    voice_tasks: int = 0
    achievements_granted: int = 0
    digest_flushes: int = 0
    xp_total: int = 0
    by_event: list[GameObservabilityRow] = []


class MusicTrackOut(BaseModel):
    """Трек в пуле предложки (Э15). Ссылка или `file_id`, не файл."""

    id: int
    user_id: int
    kind: str
    title: str | None = None
    performer: str | None = None
    url: str | None = None
    duration: int | None = None
    status: str = "pool"
    selection_id: int | None = None


class MusicSelectionOut(BaseModel):
    """Выпущенная подборка или неудачная попытка (Э15)."""

    id: int
    tg_message_id: int | None = None
    track_count: int = 0
    note: str | None = None
    created_at: datetime | None = None


class MusicStateOut(BaseModel):
    """Состояние музыкальной предложки: настройки + пул + история."""

    enabled: bool = False
    weekday: int = 1
    hour: int = 12
    attribute: bool = True
    min_tracks: int = 4
    max_tracks: int = 10
    per_user_weekly: int = 5
    # Э16: мьюзик-гейм «угадай, кто предложил трек» — авто-вызов.
    game_enabled: bool = False
    game_weekday: int = 6
    game_hour: int = 12
    pool: list[MusicTrackOut] = []
    history: list[MusicSelectionOut] = []


class MusicSettingsIn(BaseModel):
    """Частичная правка настроек предложки: что не передали — не трогаем."""

    enabled: bool | None = None
    weekday: int | None = Field(None, ge=0, le=6)
    hour: int | None = Field(None, ge=0, le=23)
    attribute: bool | None = None
    game_enabled: bool | None = None
    game_weekday: int | None = Field(None, ge=0, le=6)
    game_hour: int | None = Field(None, ge=0, le=23)


class MusicMineTrackOut(BaseModel):
    """Трек, сданный самим участником на текущей неделе (Э16, мини-апп)."""

    id: int
    kind: str
    title: str | None = None
    performer: str | None = None
    url: str | None = None
    status: str = "pool"
    added_at: datetime | None = None


class MusicWeekTrackOut(BaseModel):
    """Трек выпущенной подборки с лайками (Э17).

    `liked` — лайкнул ли его СМОТРЯЩИЙ, чтобы фронт сразу рисовал состояние
    кнопки; `likes` — общее число. Показываем только опубликованные треки.
    """

    id: int
    kind: str
    title: str | None = None
    performer: str | None = None
    url: str | None = None
    likes: int = 0
    liked: bool = False


class MusicWeekOut(BaseModel):
    """Свежая выпущенная подборка недели (Э17) — с треками и лайками."""

    id: int
    created_at: datetime | None = None
    track_count: int = 0
    tracks: list[MusicWeekTrackOut] = []


class MusicTopTrackOut(BaseModel):
    """Строка «топа треков недели»: трек + его лайки за окно (Э17)."""

    id: int
    title: str | None = None
    performer: str | None = None
    url: str | None = None
    likes: int = 0


class MusicLikeOut(BaseModel):
    """Результат тапа по лайку: новое состояние + счётчик (Э17)."""

    ok: bool = True
    liked: bool = False
    likes: int = 0


class MusicMineOut(BaseModel):
    """Экран «Предложка недели» в мини-аппе.

    Участник видит свои сданные треки, остаток недельного лимита, историю уже
    выпущенных подборок, свежую подборку с лайками и топ треков недели — без
    админских ручек.
    """

    enabled: bool = False
    per_user_weekly: int = 5
    week_count: int = 0
    # «audio» или «link» — как присылать треки (подсказка в шапке).
    tracks: list[MusicMineTrackOut] = []
    history: list[MusicSelectionOut] = []
    # Э17: свежая подборка с лайками + топ недели (задел H.8).
    week: MusicWeekOut | None = None
    top: list[MusicTopTrackOut] = []


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


# --------------------------------------------------------------------------
# Э21: активности в мини-аппе (вопросы и голосовые) — когда бот молчит в чате
# --------------------------------------------------------------------------


class ActivityOptionOut(BaseModel):
    """Вариант ответа на вопрос — кнопкой в ленте. `label` — что напишется."""

    label: str
    xp: int = 0


class ActivityOut(BaseModel):
    """Открытый вопрос (случайное событие), ждущий ответа.

    `options` — варианты для кнопок; `needs_text` — нужен свободный ответ
    (или вариант без кнопки). Одно из двух обычно непустое.
    """

    id: int
    code: str = ""
    text: str = ""
    options: list[ActivityOptionOut] = []
    needs_text: bool = False
    expires_at: datetime | None = None
    answered_by_me: bool = False


class ActivitiesOut(BaseModel):
    """Список активных вопросов + признак включённой игры."""

    enabled: bool = True
    items: list[ActivityOut] = []


class ActivityAnswerIn(BaseModel):
    """Ответ в мини-аппе: либо выбранный вариант, либо свободный текст."""

    text: str = Field(min_length=1, max_length=1000)


class ActivityAnswerOut(BaseModel):
    """Итог ответа: ок/нет и сколько выпало (текст ошибки — на клиенте)."""

    ok: bool = False
    status: str = ""
    xp: int = 0


class VoiceSubmissionOut(BaseModel):
    """Одна сдача голосового в списке текущего задания."""

    id: int
    user_id: int
    user_name: str | None = None
    duration: int | None = None
    submitted_at: datetime | None = None
    is_mine: bool = False


class VoiceCurrentOut(BaseModel):
    """Текущее голосовое задание и сдачи по нему (для ленты)."""

    enabled: bool = True
    task_id: int | None = None
    title: str = ""
    text: str = ""
    reward: int = 0
    expires_at: datetime | None = None
    my_submission_id: int | None = None
    submissions: list[VoiceSubmissionOut] = []


class VoiceSubmitOut(BaseModel):
    """Итог сдачи голосового из мини-аппа.

    `detail` — машиночитаемый код причины отказа (Э22): фронт переводит его в
    человеческий текст, а не полагается на HTTP-статус. Нужен прежде всего для
    ошибок Telegram (`user_unreachable`, `bad_format`, …), когда участник должен
    понять, что именно поправить.
    """

    ok: bool = False
    status: str = ""
    reward: int = 0
    detail: str | None = None


class MusicAddIn(BaseModel):
    """Э21: трек ссылкой из мини-аппа (аудиофайлом по-прежнему в личку боту)."""

    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=200)
    performer: str | None = Field(default=None, max_length=200)


class MusicAddOut(BaseModel):
    """Итог приёма трека: статус сервиса + остаток недельного лимита."""

    ok: bool = False
    status: str = ""
    week_count: int = 0
