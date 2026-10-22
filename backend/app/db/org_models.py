"""Организации: первый слой мультитенантности (B2B_PLATFORM_PLAN, фаза 1).

Зачем отдельный модуль, а не колонки в `users`. Люди — глобальные: один человек
может работать в двух салонах сети и не должен заводить второй Telegram. Поэтому
личность живёт в `users` без привязки к организации, а членство — в
`organization_members`. Бизнес-данные (сотрудники, подразделения, а дальше
смены, задачи, чек-листы) получают `org_id`.

Почему `DEFAULT_ORG_ID = 1`. Пока контур один, и все существующие строки уже
«принадлежат» ему. Колонки добавляются с `server_default='1'`, чтобы деплой не
требовал простоя и не ломал фоновые задачи. Это осознанный долг: как только
все таблицы получат `org_id`, серверный дефолт убирается, а строки обязаны
приносить организацию явно — иначе новый клиент молча уедет в первую.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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

# Организация, в которую попадают данные до появления второго клиента.
# Держим одной константой: её используют миграция, модели и сервис.
DEFAULT_ORG_ID = 1
DEFAULT_ORG_SLUG = "default"

# Отрасли, под которые есть (или будут) пакеты. Строка, а не enum: новый пакет
# не должен требовать миграции.
INDUSTRIES: tuple[str, ...] = ("restaurant", "salon", "autoservice", "retail", "other")

# Роли внутри организации. Не путать с HR-ролью сотрудника
# (`employee`/`aup`/`admin`): здесь — уровень доступа к самой организации.
ORG_ROLES: tuple[str, ...] = ("owner", "manager", "staff")


class Organization(Base):
    """Клиент платформы: ресторан, салон, автосервис, сеть магазинов."""

    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_organization_slug"),
        Index("ix_organizations_active", "is_active"),
    )

    # На проде — BIGSERIAL, в sqlite-тестах — INTEGER: BIGINT-первичник в
    # sqlite не автоинкрементится, и `create_org` нельзя было бы проверить.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    # Стабильный машинный код: попадает в ссылки и конфиги, поэтому не имя.
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    industry: Mapped[str] = mapped_column(
        String(32), nullable=False, default="restaurant", server_default="restaurant"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrganizationMember(Base):
    """Кто из людей имеет доступ к организации и на каком уровне.

    `role` — уровень доступа к организации (`owner`/`manager`/`staff`), а не
    HR-роль. HR-роль остаётся в `employees.role` и отвечает за рабочие права
    внутри организации.
    """

    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_member"),
        Index("ix_org_members_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    org_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="staff", server_default="staff"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
