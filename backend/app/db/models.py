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
    Integer,
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
    # ⚠️ ПРОТУХАЮЩАЯ TG file-ссылка (`…/file/bot<token>/<file_path>`): TG-овский
    # file_path живёт ≥1ч и затем 404. Колонку читает ТОЛЬКО чухан-постинг
    # (chukhan.py, синкает аватар прямо перед send_photo → ссылка свежая) — она
    # в frozen-зоне, поэтому НЕ меняем её семантику. Для мини-аппа (где ссылка
    # успевала протухнуть → «приложуха забывает аватарки», прод-фидбек 18.06 #2)
    # используем стабильный `avatar_file_id` через прокси /api/avatar/{id}.
    avatar_url: Mapped[str | None] = mapped_column(Text)
    # GHG8 (18.06 #2): СТАБИЛЬНЫЙ TG file_id последнего синканного фото — не
    # протухает (в отличие от file_path). Прокси-роут резолвит по нему свежий
    # file_path на лету. None → фото в TG ещё не запрашивалось.
    avatar_file_id: Mapped[str | None] = mapped_column(Text)
    # GHG8 (18.06 #2): ручная аватарка-ссылка (перекрывает TG для ОТОБРАЖЕНИЯ в
    # мини-аппе; принудительный синк тянет TG-шную и пишет file_id, ручную не
    # трогает). Кейс Серж/Митян: приватность TG → подставлены смешные картинки.
    avatar_manual_url: Mapped[str | None] = mapped_column(Text)
    # GHG8 (18.06 #2): когда последний раз успешно синкали TG-аватар (для меню).
    avatar_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class MeetingFeedback(Base):
    """GHG6 N2: пост-фактум 5★ оценка встречи + опция «меня не было»."""

    __tablename__ = "meeting_feedback"
    __table_args__ = (
        UniqueConstraint("meeting_id", "user_id", name="uq_feedback_meeting_user"),
        Index("ix_feedback_meeting", "meeting_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    meeting_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 1..5; NULL когда was_absent=True (см. CHECK в миграции).
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    was_absent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


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
    # G3: true после bot.stop_poll или TG-уведомления о закрытии. Защита от
    # повторного auto-close при следующем poll_answer.
    is_closed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
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
    __table_args__ = (
        Index("ix_loser_rolled_at", "rolled_at"),
        Index("ix_loser_source_rolled_at", "source", "rolled_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    rolled_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    loser_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    reason_text: Mapped[str | None] = mapped_column(Text)
    # GHG6 H1: 'auto' — scheduler-job (автолох), 'manual' — ручная крутилка и
    # admin force-reroll. Cooldown считается раздельно по семейству источников;
    # «лох дня» в календаре — только source='auto'.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")


class LoserOutbox(Base):
    """GHG7 P0.2 — статус доставки автолох-поста в групповой чат.

    Domain (`LoserRoll`) и delivery (`LoserOutbox`) разделены: при срабатывании
    autoloser-job в `loser_rolls` пишется запись о выпавшем лохе сразу, а
    отдельно — строка в `loser_outbox` со `status='pending'`. Send в TG
    пробуется внутри той же транзакции; результат обновляет outbox-строку,
    но НЕ откатывает loser_roll. Так нет «фантомных» записей без поста: пока
    `status != 'sent'`, корона на календаре не показывается (см.
    `routes_calendar.py`).

    Ретрай-job `loser_outbox_retry` каждую минуту повторяет SELECT FOR UPDATE
    SKIP LOCKED по WHERE status='pending' AND attempts<12 AND
    next_retry_at<=now(). После 12 fail-ов → `status='expired'`.

    Ручные роллы (UI/chat-команда/admin force-reroll) outbox НЕ пишут — там
    best-effort send как было после GHG6 E3, юзер видит результат сам.
    """
    __tablename__ = "loser_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'expired')",
            name="ck_loser_outbox_status",
        ),
        Index("ix_loser_outbox_pending", "status", "next_retry_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    loser_roll_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("loser_rolls.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    loser_roll: Mapped["LoserRoll"] = relationship("LoserRoll")


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
    # GHG8 T1.2: фраза-причина, выбранная для этого чухана (кастомная из
    # admin_config или дефолтный CHUKHAN_TAGLINE). Сохраняется при успешном
    # постинге, чтобы история (профиль) показывала причину — как у лоха.
    reason_text: Mapped[str | None] = mapped_column(Text)
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


class ParticipantPersona(Base):
    """GHG8 P6.1 — типаж участника для генератора фраз v2.

    Тексты живут ТОЛЬКО в Neon (проект — открытый git, персоналии в репо
    нельзя; GHG7.txt стр. 160). Сидинг — руками через админку (P6.1.b),
    не миграцией. Формат `persona_text` (секции [слоты]/[шаблоны]) —
    парсер в `services/personas.py`.
    """

    __tablename__ = "participant_personas"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    persona_text: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# GHG10 — геймификация (опыт, уровни, ранги, ачивки).
#
# Каталог ачивок живёт В КОДЕ (`services/game/achievements_catalog.py`), а не в
# таблице: у каждой ачивки есть трекер в коде, и держать рядом ещё и строку в
# БД — это два источника правды. `user_achievements.code` — обычная строка без
# FK, поэтому переделка каталога не требует миграции (требование задания
# «перелопатить систему в один промт»).
# ---------------------------------------------------------------------------


class GameProfile(Base):
    """GHG10: игровой профиль участника.

    Единственный источник правды по опыту — `xp`. Уровень, ранг и престиж
    ВЫВОДЯТСЯ из него (`services/game/levels.py`), а не хранятся: иначе они
    разъезжаются при любой правке баланса в `config.py`.
    """

    __tablename__ = "game_profiles"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Суммарный опыт за всё время. Никогда не обнуляется (в отличие от дневной
    # истории, которая просто фильтруется по дате).
    xp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Ранг 8/10: своё имя и своё название ранга в приложении (гейтинг по уровню).
    custom_name: Mapped[str | None] = mapped_column(Text)
    custom_rank_title: Mapped[str | None] = mapped_column(Text)
    # Э3: непоказанное уведомление о левел-апе. `from` = уровень до подъёма,
    # `to` = уровень после. Обе None = уведомления нет. Если одно начисление
    # закрыло несколько уровней — храним весь диапазон (from самый ранний).
    # Сбрасывается, когда юзер посмотрел профиль (POST /me/game/level-up/ack).
    pending_level_up_from: Mapped[int | None] = mapped_column(Integer)
    pending_level_up_to: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class XpDaily(Base):
    """GHG10: дневная история начислений (агрегат).

    Задание: «по ходу дня у пользователя накапливается история действий и
    пополнения опыта... в 00-00 история обнуляется (но не опыт!)».
    Обнуление — это просто фильтр по `day`, а не удаление: история нужна для
    «зашёл в 23:30 и посмотрел, за что плюсануло».

    Агрегат (а не строка на каждое сообщение): 1 сообщение = 1 опыт, и держать
    по строке на сообщение — это тысячи строк в месяц на шестерых.
    """

    __tablename__ = "xp_daily"
    __table_args__ = (
        Index("ix_xp_daily_user_day", "user_id", "day"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # UTC-сутки (как везде в проекте — aware UTC).
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    # Код события из `config.XP_RULES`.
    event: Mapped[str] = mapped_column(String(32), primary_key=True)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class XpGrant(Base):
    """GHG10: маркеры идемпотентности для лимитированных начислений.

    `config.XpRule.limit` = "day"/"week"/"year"/"once" → пишем маркер с
    оконным ключом, и повторное событие в том же окне опыта не даёт. Строк
    мало (недельный календарь = 6/неделю, ДР = 6/год), поэтому таблица не
    растёт заметно.
    """

    __tablename__ = "xp_grants"
    __table_args__ = (
        Index("ix_xp_grant_key", "user_id", "idem_key", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Например "availability:2026-W39" или "birthday:2026".
    idem_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserAchievement(Base):
    """GHG10: собранные ачивки. Каждую можно взять только один раз на юзера.

    `code` — код из каталога в коде; для юбилейных тиров код включает тир
    ("first_loser:10"), поэтому одна и та же база даёт несколько записей.
    """

    __tablename__ = "user_achievements"
    __table_args__ = (
        Index("uq_user_achievement", "user_id", "code", unique=True),
        Index("ix_user_achievement_unlocked", "unlocked_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    unlocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatActivityDaily(Base):
    """GHG10: счётчик сообщений по дням — для недельных званий.

    Почему не из `chat_messages`: та таблица чистится через 7 дней и хранит
    только текст, а для «рупор поколения» / «Read only» и для «сообщение = 1
    опыт» нужен durable счётчик (включая медиа и стикеры).
    """

    __tablename__ = "chat_activity_daily"
    __table_args__ = (
        Index("ix_chat_activity_day", "day"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AchievementCounter(Base):
    """GHG10: накопители ачивок, которые НЕ выводятся из существующих таблиц.

    Большинство трекеров считает по уже имеющимся данным (`loser_rolls`,
    `weekly_chukhan`, `polls`, `availability_ranges`, `xp_grants`) — дублировать
    их счётчиками нельзя. Здесь живут только те, для которых источника нет:
    ответы боту (`worm_tamer`), посты с реакциями (`successful_success`),
    мёртвые посты (`opium_for_nobody`). Строк мало и они не растут на каждое
    сообщение (обновляем `count` одной строки).
    """

    __tablename__ = "achievement_counters"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Код трекера (не обязательно код ачивки — см. `achievements.COUNTER_*`).
    code: Mapped[str] = mapped_column(String(48), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class GameHoliday(Base):
    """GHG10: пул праздников (дата + сообщение). По умолчанию — Новый год.

    `month`/`day` без года — праздник ежегодный, как ДР в `birthdays`
    (сравнение месяц+день).
    """

    __tablename__ = "game_holidays"
    __table_args__ = (
        UniqueConstraint("month", "day", name="uq_game_holiday_md"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GameMediaPost(Base):
    """GHG10 Э7: телеметрия мем-постов (мемолог / успешный успех / опиум).

    Живёт в БД, а не в памяти: HF Space перезапускается, а «скинул мем и 12
    часов тишины» — факт, который должен быть помнит дольше процесса (ср.
    `media_reactions`, где in-memory `_reacted` честно эфемерен).

    Два списка откликов, потому что роли у них разные:
    - `window_responders` — кто успел в окно реакции (`MEME_REACTION_WINDOW_MIN`);
      только он решает «Мемолога» («отреагировали все живые»);
    - `responders` — кто откликнулся вообще (реакция/reply в любое время);
      он решает, был ли пост с реакциями, когда истекают 12 часов.

    `memelog_done` — «вердикт по мемологу вынесен»: окно закрылось, состав
    откликнувшихся больше не изменится. Без него job каждые 10 минут заново
    спрашивал бы ачивку у 71 поста до наступления 12-часового рубежа.
    """

    __tablename__ = "game_media_posts"
    __table_args__ = (
        UniqueConstraint(
            "chat_id", "tg_message_id", name="uq_game_media_post_msg"
        ),
        Index("ix_game_media_chat_posted", "chat_id", "posted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tg_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # "single" (одиночный мем) | "collection" (подборка-альбом)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    responders: Mapped[list[int]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    window_responders: Mapped[list[int]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    memelog_done: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # "alive" — пост собрал реакции; "dead" — 12 часов никто не откликнулся.
    outcome: Mapped[str | None] = mapped_column(String(16))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GameJournalEntry(Base):
    """Э13: игровой журнал — сводка вместо спама и «поминальные» сообщения.

    Одна таблица решает две задачи, потому что у них общая механика: «событие
    случилось → его надо (не)показать в чат».

    * **Сводка.** Когда `game.digest.enabled=true`, анонсы не уходят в чат по
      одному, а ложатся сюда (`sent_at IS NULL`) и вываливаются одним дайджестом
      по расписанию. Пустая таблица = пусто в чате.
    * **Поминовения.** Строка `kind='memorial'` с `subject_user_id` — открытое
      поминовение: пока `resolved_at IS NULL`, человек «в розыске», и первое же
      его сообщение закрывает строку и вызывает «⚠️ ОН ЗДЕСЬ».

    `repeat_after` — когда поминовение можно повторить (одно и то же лицо может
    молчать месяцами, а спамить каждый день нельзя).
    """

    __tablename__ = "game_journal"
    __table_args__ = (
        Index("ix_game_journal_pending", "sent_at", "created_at"),
        Index("ix_game_journal_subject", "subject_user_id", "kind"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Кто автор события (для «своих ачивок» и вообще для контекста). None — «никто».
    subject_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # None = ещё не показано (для сводки — «в очереди»).
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Когда поминовение можно повторить; None — только для не-поминовений.
    repeat_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Поминовение закрыто возвращением человека.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GamePrompt(Base):
    """Э13: случайное событие, требующее действия в чате.

    Бот постит призыв («Первый, кто напишет "я", получает 50 XP») и ждёт
    сообщение, подходящее под один из ответов каталога. Победитель — первый
    подходящий ответ до `expires_at`; после этого строка закрывается.

    `matcher` хранится строкой (регэксп), а не ссылкой на код: промпт живёт
    дольше одного релиза, и старые открытые промпты должны доиграть по своим
    правилам, даже если каталог уже переписали.
    """

    __tablename__ = "game_prompts"
    __table_args__ = (
        Index("ix_game_prompts_open", "chat_id", "closed_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # JSONB-список ответов: [{"matcher": "^да$", "xp": 10, "reply": "..."}].
    answers: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    winner_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    # None = промпт ещё в игре. Закрывается победой или истечением срока.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(16))


# Цвет для User: если перед insert color_hex пустой — заполнить детерминированно
# из telegram_id (палитра в app.db.seed.color_for_user).
from sqlalchemy import event as _sa_event


@_sa_event.listens_for(User, "before_insert")
def _user_default_color(_mapper, _conn, target: User) -> None:
    if not target.color_hex:
        from app.db.seed import color_for_user  # ленивый импорт, цикл

        target.color_hex = color_for_user(target.telegram_id)

