from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    color_hex: Mapped[str] = mapped_column(String(7), nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="Europe/Moscow")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ranges: Mapped[list[AvailabilityRange]] = relationship(back_populates="user")


class AvailabilityRange(Base):
    __tablename__ = "availability_ranges"
    __table_args__ = (
        CheckConstraint("confidence BETWEEN 1 AND 5", name="ck_avail_confidence"),
        Index("ix_avail_user_time", "user_id", "starts_at", "ends_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    confidence: Mapped[int] = mapped_column(SmallInteger, default=3, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="ranges")


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="proposed", nullable=False)
    auto_picked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # E6: 'game' для встреч-игр; NULL для обычных встреч.
    tag: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MeetingAttendance(Base):
    __tablename__ = "meeting_attendance"

    meeting_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    rsvp: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    showed_up: Mapped[bool | None] = mapped_column(Boolean)


class Poll(Base):
    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)
    tg_poll_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    # E6: 'game_choice' (Во что сыграем) / 'game_when' (Когда играем). NULL для
    # старых meetup-полов с datetime-опциями.
    kind: Mapped[str | None] = mapped_column(String(32))
    # E6: для game_when — id игры-победителя, чтобы знать, какую игру кладём
    # в Meeting после выбора даты.
    game_nomination_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PollOption(Base):
    __tablename__ = "poll_options"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    poll_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("polls.id", ondelete="CASCADE"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    label: Mapped[str | None] = mapped_column(Text)


class PollVote(Base):
    __tablename__ = "poll_votes"
    __table_args__ = (
        UniqueConstraint("poll_option_id", "user_id", name="uq_poll_vote"),
    )

    poll_option_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("poll_options.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    voted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LoserRoll(Base):
    __tablename__ = "loser_rolls"
    __table_args__ = (Index("ix_loser_rolled_at", "rolled_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    rolled_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    loser_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    reason_text: Mapped[str | None] = mapped_column(Text)


class WormAssignment(Base):
    """Особая номинация «Червь-пидор» (E8, GHG6).

    Звание переходящее: в любой момент существует ≤1 активной строки
    (`ended_at IS NULL`) — обеспечено partial unique index на (1) в миграции
    0008. При новом назначении старая активная строка получает
    `ended_at=now()` и затем создаётся новая (внутри одной транзакции).
    """
    __tablename__ = "worm_assignments"
    __table_args__ = (
        Index("ix_worm_user_started", "user_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_loser_roll_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("loser_rolls.id", ondelete="SET NULL")
    )


class BotPause(Base):
    """GHG6 E11 — глобальная пауза публикаций бота.

    Активная запись — `ended_at IS NULL`. В любой момент существует
    не более одной активной строки (партиальный unique index на (1) WHERE
    ended_at IS NULL — как в worm_assignments).

    `settings_snapshot` — JSONB-копия master-toggles и интервалов на момент
    старта паузы. При снятии паузы (по времени или вручную) — состояние
    восстанавливается из snapshot.
    """

    __tablename__ = "bot_pause"
    __table_args__ = (
        Index("ix_bot_pause_started", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_by_tg_id: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(32), nullable=False, default="manual_admin")
    settings_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class WeeklyChukhan(Base):
    __tablename__ = "weekly_chukhan"
    __table_args__ = (
        UniqueConstraint("week_start", name="uq_weekly_chukhan_week"),
        Index("ix_weekly_chukhan_week", "week_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    week_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    weights_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MeetingReminder(Base):
    __tablename__ = "meeting_reminders"
    __table_args__ = (
        UniqueConstraint("meeting_id", "offset_minutes", name="uq_meeting_reminder"),
        Index("ix_reminder_due_at", "due_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    offset_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminConfig(Base):
    """Runtime-настройки, которые админ меняет из Mini App.
    Перекрывают значения из env vars. Ключи: chukhan_weight:{tg_id} → float."""
    __tablename__ = "admin_config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ChatMessage(Base):
    """Кэш последних сообщений из общей группы — нужен для «рандомных фраз»."""
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "tg_message_id", name="uq_chat_msg"),
        Index("ix_chat_msg_user_sent", "user_id", "sent_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tg_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Birthday(Base):
    """Дата рождения участника + пер-юзерные флаги напоминаний.
    bday хранится с реальным годом (nullable: год может быть неизвестен —
    тогда напоминания работают по месяцу/дню, возраст не показываем)."""
    __tablename__ = "birthdays"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    bday: Mapped[date | None] = mapped_column(Date)
    year_known: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remind_month: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remind_week: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remind_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remind_on_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remind_hint_week: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class BirthdayNotification(Base):
    """Журнал отправленных напоминаний — чтобы не слать дубли в один и тот же день."""
    __tablename__ = "birthday_notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "year", "kind", name="uq_birthday_notif"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProxyEntry(Base):
    """Пул прокси для аутgoing-трафика бота (P2 Smart Proxy).

    Используется AiohttpSession-фолбэком: при ошибке direct connect к
    api.telegram.org session пробует следующий enabled+живой прокси.
    """
    __tablename__ = "proxy_entries"
    __table_args__ = (
        UniqueConstraint("server", "port", name="uq_proxy_server_port"),
        Index("ix_proxy_enabled_dead", "enabled", "dead_until"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    server: Mapped[str] = mapped_column(Text, nullable=False)
    port: Mapped[int] = mapped_column(nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="mtproto")
    secret: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fail_count: Mapped[int] = mapped_column(nullable=False, default=0)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_fail_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EventLog(Base):
    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class GameNomination(Base):
    """GHG6 E6 — номинированные игры для голосования «Во что сыграем».

    Лимит активных (10) и проверка на дубль по `name` (case-insensitive)
    обеспечиваются на уровне сервиса (`services/games.py`), не БД — чтобы
    при ре-добавлении удалённой игры можно было «вернуть» строку из soft-delete.
    """

    __tablename__ = "game_nominations"
    __table_args__ = (
        Index("ix_game_nomination_active", "removed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    added_by_tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

# Цвет для User: если перед insert color_hex пустой — заполнить детерминированно
# из telegram_id (палитра в app.db.seed.color_for_user).
from sqlalchemy import event as _sa_event


@_sa_event.listens_for(User, "before_insert")
def _user_default_color(_mapper, _conn, target: User) -> None:
    if not target.color_hex:
        from app.db.seed import color_for_user  # ленивый импорт, цикл

        target.color_hex = color_for_user(target.telegram_id)

