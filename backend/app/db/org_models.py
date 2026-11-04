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
# «cafe» есть в мастере настройки (`services/org_setup`), поэтому должен быть и
# здесь: иначе организация кофейни создаётся, а `create_org` считает отрасль
# неизвестной.
INDUSTRIES: tuple[str, ...] = (
    "restaurant",
    "cafe",
    "salon",
    "autoservice",
    "retail",
    "other",
)

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
        # Один Telegram-бот не может обслуживать два клиента: у каждого свой
        # токен и свой секрет вебхука. NULL'ы в PG уникальности не мешают,
        # поэтому организация без своего бота живёт на общем (env).
        Index("uq_organization_bot_token", "bot_token", unique=True),
        Index("uq_organization_webhook_secret", "webhook_secret", unique=True),
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
    # Тариф организации (шаг 4.1). `trial` ставится явно при создании
    # (`orgs.create_with_owner`), а серверный дефолт `business` нужен
    # старым строкам: ограничивать действующего клиента датой в
    # календаре — поломка, а не введение тарифов.
    plan: Mapped[str] = mapped_column(
        String(16), nullable=False, default="trial", server_default="business"
    )
    # Конец пробного периода. Пусто у платных тарифов и у старых
    # организаций: срок есть только у `trial`.
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # До какого срока подписка оплачена (шаг 4.2). Пусто у триала и у
    # существующих организаций: «Бизнес» без срока — это бессрочно, а не
    # «истекло вчера». Срок ставит только `billing.mark_paid`: ручка
    # организации лишь просит подтвердить оплату, иначе кнопка «я оплатил»
    # стала бы бесплатным безлимитом.
    plan_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # Бренд клиента (шаг 4.4). Пусто — видно имя организации; заполнено —
    # имя, цвет ссылок и логотип клиента вместо платформенных. Цвет хранится
    # текстом `#rrggbb`: это CSS-значение, его сравнивают и логируют как текст.
    brand_name: Mapped[str | None] = mapped_column(String(64))
    brand_color: Mapped[str | None] = mapped_column(String(9))
    # Логотип — ссылка на CDN клиента: загрузка файла потребовала бы хранилища
    # и чистки сирот, а поле при появлении загрузки останется тем же.
    brand_logo_url: Mapped[str | None] = mapped_column(Text)
    # Свой бот клиента (B2B_PLATFORM_PLAN, шаг 1.6). Пусто — организация
    # работает на боте из env (текущий контур). Токен здесь только потому, что
    # у каждой организации свой BotFather-бот; отдавать его наружу нельзя.
    bot_token: Mapped[str | None] = mapped_column(Text)
    bot_username: Mapped[str | None] = mapped_column(String(64))
    # Секрет вебхука: по нему входящий апдейт находит свою организацию, не
    # доверяя ничему из тела запроса.
    webhook_secret: Mapped[str | None] = mapped_column(Text)
    # Чат, куда бот пишет отчёты и напоминания. Пусто — значение из env.
    group_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    # Приватность (B2B_PLATFORM_PLAN, шаг 5.5): удаление по запросу.
    # `deleted_at` — когда попросили, `purge_after` — когда данные
    # исчезнут. Между ними владелец может отменить: удаление
    # необратимо, и мгновенная кнопка была бы ловушкой.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    purge_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
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


class OrgInvitation(OrgScoped, Base):
    """Ссылка-приглашение в организацию (B2B_PLATFORM_PLAN, шаг 2.2).

    Почему ссылка, а не запись «сотрудника в ожидании». Приглашённый может
    ещё не иметь аккаунта, и заводить ему строку `users` заранее значит плодить
    дубли: человек зарегистрируется другой почтой или войдёт из Telegram.
    Приглашение — это право присоединиться, а учётка появляется по факту.

    В базе только SHA-256 от токена: ссылка живёт неделю, пересылается в
    мессенджере и попадает в историю — утечка дампа не должна давать вход.

    `email` необязателен. Пусто — ссылка «для всех, у кого она есть» (её кидают
    в чат смены). Заполнен — принять сможет только владелец этой почты, и
    письмо уходит ему.

    Модель тенантная (`OrgScoped`), поэтому выборки в админке фильтруются по
    организации автоматически. Единственное исключение — поиск по токену: он
    идёт до того, как организация известна, и оборачивается в `all_orgs()`.
    """

    __tablename__ = "org_invitations"
    __table_args__ = (
        # Токен ищется глобально, пока организация неизвестна — значит и
        # уникален он глобально, а не внутри тенанта.
        UniqueConstraint("token_hash", name="uq_org_invitation_token"),
        Index("ix_org_invitations_org", "org_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    email: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="staff", server_default="staff"
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Принята: ссылка одноразовая, повторный переход отвечает «уже принято».
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Преднастроенная должность и отдел. Ссылка может нести не только роль:
    # руководитель уже знает, кем человек выходит, и не должен заставлять его
    # выбирать это заново в первый день. Применяются при создании HR-профиля
    # (`services.hr_access.ensure_employee`) — до этого профиля может не быть.
    position: Mapped[str | None] = mapped_column(Text)
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL")
    )

class OrgInvoice(OrgScoped, Base):
    """Счёт на оплату тарифа (B2B_PLATFORM_PLAN, шаг 4.2).

    Почему счёт, а не платёж. Платёжного провайдера подключает владелец, и до
    этого продукт не должен показывать кнопку «Оплатить», которая ничего не
    делает. Счёт — документ, который существует независимо от провайдера:
    номер, тариф, период, сумма и срок. Провайдер, когда появится, будет
    закрывать те же счета, и история платежей не переедет.

    Почему `expired` не хранится. Просроченный счёт — это `pending` с
    прошедшим `expires_at`. Отдельный статус потребовал бы фоновой задачи,
    которая переводит строки, и дал бы расхождение между задачей и фактом.

    `period_start`/`period_end` — что именно оплатили. Они заполняются при
    подтверждении, а не при выставлении: до денег это ещё обещание.
    """

    __tablename__ = "org_invoices"
    __table_args__ = (
        UniqueConstraint("number", name="uq_org_invoice_number"),
        Index("ix_org_invoices_org", "org_id", "created_at"),
        # Идемпотентность кнопки «выставить счёт»: повторный клик ищет открытый
        # счёт на тот же тариф и период по этому индексу.
        Index("ix_org_invoices_open", "org_id", "plan", "period", "status"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    plan: Mapped[str] = mapped_column(String(16), nullable=False)
    # `month` или `year`: период подписки, а не длительность в днях.
    period: Mapped[str] = mapped_column(String(8), nullable=False)
    # Целые рубли. Копейки в B2B-подписке не нужны, а float в деньгах —
    # источник расхождений на копейку, который потом ищут бухгалтерией.
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="RUB", server_default="RUB"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Примечание платформы: «оплатили по счёту №…», реквизиты, номер платёжки.
    comment: Mapped[str | None] = mapped_column(Text)


class AuditEvent(OrgScoped, Base):
    """Событие доступа к данным организации (B2B_PLATFORM_PLAN, шаг 5.5).

    Почему отдельная таблица, а не `structlog`. Лог живёт до ротации
    контейнера и недоступен клиенту; журнал — данные организации: читается
    из кабинета, обрезается по сроку и удаляется вместе с организацией.

    Почему `actor_name` — снимок. Сотрудника можно удалить, а событие «кто
    выгрузил данные» должно остаться читаемым. При `ON DELETE SET NULL`
    ссылка обнуляется, имя сохраняется здесь.

    `details` — JSON текстом: журнал не фильтруют по деталям, а sqlite в
    тестах не знает JSONB.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_org_time", "org_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_name: Mapped[str | None] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

class ApiKey(OrgScoped, Base):
    """Ключ публичного API организации (B2B_PLATFORM_PLAN, шаг 6.1).

    Зачем не пароль владельца. Интегратору нужны люди и график, но не кабинет:
    пароль дал бы ему всё, включая удаление организации. Ключ выписывается на
    подрядчика, имеет свой набор прав и отзывается отдельно.

    Почему в базе хеш и префикс. Ключ показывается один раз при создании;
    утечка дампа не даёт доступа к API, а человек узнаёт ключ в списке по
    началу «stk_live_7fa2…». Тот же приём, что у приглашений и сессий.
    """

    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_token_hash", "token_hash", unique=True),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookEndpoint(OrgScoped, Base):
    """Приёмник событий организации (шаг 6.1).

    `failures` считает подряд идущие неудачи: по нему в кабинете видно, что
    интегратор сломался. Сам приёмник не выключается — иначе клиент чинил бы
    сервер и не понимал, почему события перестали приходить.
    """

    __tablename__ = "webhook_endpoints"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    events: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WebhookDelivery(OrgScoped, Base):
    """Очередь доставки и её журнал (шаг 6.1).

    Почему `payload` снимком, а не ссылкой на данные. Повтор обязан отправить
    то же тело, что и первая попытка: иначе интегратор получит событие
    «сотрудник создан» с уже изменённой должностью.
    """

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index("ix_webhook_deliveries_org_time", "org_id", "created_at"),
        Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    endpoint_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    event: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    response_code: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotifyPref(OrgScoped, Base):
    """Личная подписка на автоматическое уведомление (04.11.2026).

    Автоматическое сообщение приходит человеку только при явном `enabled`.
    Строка создаётся при первом включении; её отсутствие значит «выключено»,
    поэтому миграция не обязана заводить строки на всех.

    Уникальный ключ `(org_id, user_id, kind)` — потому что один человек может
    работать в двух организациях сети, и подписка в одной не включает сводку в
    другой.
    """

    __tablename__ = "notify_prefs"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "user_id", "kind", name="uq_notify_pref_org_user_kind"
        ),
        Index("ix_notify_prefs_user", "org_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
