from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field


class AutoPickRequest(BaseModel):
    """Request body for /api/meetings/auto-pick."""

    window_start: datetime
    window_end: datetime
    duration_minutes: int = Field(120, ge=30, le=24 * 60)
    step_minutes: int = Field(60, ge=15, le=24 * 60)
    top_n: int = Field(5, ge=1, le=20)
    # GHG5 POLL-HOURS1: использовать пресеты времени из admin_config вместо
    # фиксированных duration/step. True по умолчанию — никаких больше 00-04.
    use_presets: bool = True


class AutoPickSlotOut(BaseModel):
    starts_at: datetime
    ends_at: datetime
    score: float
    available_user_ids: list[int]
    maybe_user_ids: list[int]


class AutoPickResponse(BaseModel):
    slots: list[AutoPickSlotOut]


class MeetingCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    starts_at: datetime
    ends_at: datetime
    location: str | None = None
    auto_picked: bool = False
    score: float | None = None


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_by: int
    title: str
    starts_at: datetime
    ends_at: datetime
    location: str | None = None
    status: str
    auto_picked: bool
    score: float | None = None


class RsvpRequest(BaseModel):
    rsvp: int = Field(..., ge=0, le=3)  # 0=не ответил, 1=да, 2=может, 3=нет


class MeetingAttendeeOut(BaseModel):
    user_id: int
    rsvp: int


class MeetingDetail(MeetingOut):
    attendees: list[MeetingAttendeeOut]
    my_rsvp: int = 0


class LoserRollOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rolled_at: datetime
    rolled_by: int
    loser_user_id: int
    reason_text: str | None = None


class LoserStatsOut(BaseModel):
    counts: dict[int, int]
    last: LoserRollOut | None
    cooldown_remaining_seconds: int


class LoserRollResponse(BaseModel):
    roll: LoserRollOut
    sent_to_chat: bool


class PollCreateRequest(BaseModel):
    """GHG6 PL5: вариант может быть либо `datetime` ISO, либо строка-дата `YYYY-MM-DD`.

    Date-only означает, что время не задано (опросник без чекбокса «указать время»):
    backend хранит `starts_at = date 00:00 локали`, `ends_at = 23:59`, label
    «вс 17.05» — без часа.
    """

    question: str = Field(..., min_length=1, max_length=255)
    # Принимаем строки (ISO datetime или YYYY-MM-DD). Парсинг — в services/polls.py.
    options: list[str] = Field(..., min_length=2, max_length=6)
    closes_in_hours: int | None = Field(None, ge=1, le=72)
    chat_id: int | None = None
    # G2: закрепить сообщение с опросом. None → дефолт из admin_config.
    pin: bool | None = None


class PollAutoPickRequest(BaseModel):
    """Авто-публикация TG-опроса по найденным top-N слотам."""

    window_start: datetime
    window_end: datetime
    duration_minutes: int = Field(120, ge=30, le=24 * 60)
    step_minutes: int = Field(60, ge=15, le=24 * 60)
    top_n: int = Field(3, ge=2, le=5)
    question: str = Field("Когда соберёмся?", min_length=1, max_length=255)
    closes_in_hours: int | None = Field(24, ge=1, le=72)
    chat_id: int | None = None
    # GHG5 POLL-HOURS1: использовать пресеты времени из admin_config.
    use_presets: bool = True
    # G2: закрепить сообщение. None → дефолт из admin_config.
    pin: bool | None = None


class PollOptionOut(BaseModel):
    id: int
    starts_at: datetime
    label: str | None = None
    voter_user_ids: list[int] = []


class PollOut(BaseModel):
    id: int
    question: str
    closes_at: datetime | None
    options: list[PollOptionOut]
    my_vote_option_id: int | None = None


def fmt_remaining(td: timedelta) -> str:
    total = int(td.total_seconds())
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}ч {m}мин" if h else f"{m}мин"
