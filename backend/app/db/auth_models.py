"""Вход без Telegram: сессии и сброс пароля (B2B_PLATFORM_PLAN, шаг 2.1).

Почему отдельный модуль, а не поля в `users`. Сессия — это устройство, а не
человек: их несколько, каждую можно отозвать, у каждой свой срок. Держать это
в `users` значило бы хранить один токен и терять историю входов.

Почему таблицы НЕ тенантные (`org_id` есть только у сессии и он nullable).
Аутентификация происходит до того, как известно, в какую организацию идёт
запрос: человек может состоять в двух. Тенант выбирается при выдаче сессии
(`org_id`) или из членства — но сама проверка токена обязана работать без
фильтра, иначе вход в приложение зависел бы от того, угадал ли клиент
организацию.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthSession(Base):
    """Живой вход: «это устройство уже подтвердило пароль».

    В базе лежит только SHA-256 от токена. Сам токен знает лишь клиент —
    утечка дампа не даёт возможности войти.
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (
        # Один человек — несколько устройств; выборка всегда по user_id.
        Index("ix_auth_sessions_user", "user_id"),
        Index("ix_auth_sessions_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Организация, в которой выдан вход. NULL — человек ещё без членства
    # (зарегистрировался, но приглашения не получил).
    org_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="SET NULL")
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Отзыв: выход, смена пароля, «выйти на всех устройствах». Строку не
    # удаляем — иначе нечем ответить на вопрос «когда истёк этот вход».
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailVerification(Base):
    """Ссылка «подтвердить почту» (B2B_PLATFORM_PLAN, шаг 2.1).

    Зачем отдельная таблица, а не флаг в `users`. Ссылку можно запросить
    повторно с другого устройства, она живёт двое суток и должна работать
    ровно один раз; в `users` для этого пришлось бы держать четыре поля и
    терять историю. Здесь — как у сброса пароля: только хеш токена.

    Таблица глобальная (без `org_id`): подтверждение относится к личности, а
    организация на момент перехода по ссылке ещё может быть неизвестна.
    """

    __tablename__ = "email_verifications"
    __table_args__ = (
        Index("ix_email_verifications_user", "user_id"),
        Index("ix_email_verifications_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordReset(Base):
    """Одноразовая ссылка сброса пароля (живёт час).

    Храним хеш по той же причине, что и у сессии. `used_at` делает ссылку
    одноразовой: после успешной смены пароля повторный переход не сработает.
    """

    __tablename__ = "password_resets"
    __table_args__ = (
        Index("ix_password_resets_user", "user_id"),
        Index("ix_password_resets_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
