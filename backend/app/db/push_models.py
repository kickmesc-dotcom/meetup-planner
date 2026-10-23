"""Подписки на web push (B2B_PLATFORM_PLAN, шаг 2.4).

Зачем отдельная таблица, а не поле в `users`. Подписка — это **браузер**, а не
человек: телефон, домашний компьютер и планшет дают три разных endpoint, и
каждый умирает сам (человек удалил приложение, почистил данные, сменил
браузер). Один общий ключ в `users` пришлось бы перезаписывать, теряя два
устройства из трёх.

Почему `endpoint_hash`, а не сам endpoint в уникальном индексе. Endpoint — это
длинный URL (иногда 400+ символов), а btree в Postgres ограничен ~2700 байтами
на строку; хеш (SHA-256, 64 символа) даёт стабильный уникальный ключ и заодно
не раздувает индекс. Сам endpoint храним в `Text`: он нужен для отправки.

`org_id` обязателен: таблица тенантная, как все бизнес-таблицы. Подписка
привязывается к организации, в которой человек её включил, — иначе фильтр
запросов не смог бы отличить клиентов.
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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PushSubscription(Base):
    """Одно устройство, согласившееся получать уведомления в браузере."""

    __tablename__ = "push_subscriptions"
    __table_args__ = (
        # Выборка всегда «все подписки этих пользователей» в рамках организации.
        Index("ix_push_subscriptions_org_user", "org_id", "user_id"),
        # Endpoint глобально уникален: один браузер — одна строка. Повторная
        # подписка (например, после смены ключей) обновляет её, а не плодит дубли.
        UniqueConstraint("endpoint_hash", name="uq_push_subscription_endpoint"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    org_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Ключи шифрования push-сообщения. Не секреты аккаунта: без них сервер не
    # может зашифровать payload, но и войти с ними нельзя.
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    auth: Mapped[str] = mapped_column(String(255), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Обновляем при каждой успешной отправке — видно, жива ли подписка.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
