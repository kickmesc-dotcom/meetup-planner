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

from contextvars import ContextVar, Token
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
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.db.base import Base

# Организация, в которую попадают данные до появления второго клиента.
# Держим одной константой: её используют миграция, модели и сервис.
DEFAULT_ORG_ID = 1
DEFAULT_ORG_SLUG = "default"

# "Текущая" организация выполнения. Контекстная переменная, а не поле сессии:
# один и тот же `AsyncSession` может обслуживать запросы разных людей, а
# запросы бота и планировщика идут вообще без HTTP. Значение по умолчанию —
# первая организация: ровно то поведение, что было до тенантов.
current_org_id: ContextVar[int] = ContextVar("current_org_id", default=DEFAULT_ORG_ID)

# Сентинел «без фильтра»: только для платформенных задач (обход всех
# организаций в планировщике, админка платформы). Обычный код его не ставит.
ALL_ORGS = 0


def set_org(org_id: int) -> Token[int]:
    """Включить тенантский фильтр на время запроса."""
    return current_org_id.set(org_id)


def reset_org(token: Token[int]) -> None:
    current_org_id.reset(token)


# Отрасли, под которые есть (или будут) пакеты. Строка, а не enum: новый пакет
# не должен требовать миграции.
INDUSTRIES: tuple[str, ...] = ("restaurant", "salon", "autoservice", "retail", "other")

# Роли внутри организации. Не путать с HR-ролью сотрудника
# (`employee`/`aup`/`admin`): здесь — уровень доступа к самой организации.
ORG_ROLES: tuple[str, ...] = ("owner", "manager", "staff")


class OrgScoped:
    """Миксин «эта таблица принадлежит организации».

    Зачем миксин, а не колонка в каждой модели. Колонок восемь десятков, и
    руками их легко «забыть» в одной — именно так и появляются таблицы без
    тенанта. Здесь определение одно: `org_id` с FK на `organizations`, индексом
    и серверным дефолтом, чтобы деплой на заполненную базу не требовал простоя.

    Порядок наследования: `class Foo(OrgScoped, Base)` — миксин первым, иначе
    declarative не увидит `declared_attr`.

    Дефолт берётся из контекстной переменной, а не из константы: строка,
    созданная в запросе второй организации, обязана уехать во вторую. Статичный
    дефолт молча складывал бы всё в первую — это самый неприятный вид утечки.
    """

    @declared_attr
    def org_id(cls) -> Mapped[int]:  # noqa: N805  (cls — требование SQLAlchemy)
        return mapped_column(
            BigInteger,
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            default=lambda _ctx: current_org_id.get(),
            server_default=str(DEFAULT_ORG_ID),
            index=True,
        )


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
        index=True,
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
