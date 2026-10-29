"""HR-ядро SemiTaskBot (Этап 1 MVP).

Модели под сценарии [mainPROMT.MD]: подразделения, профиль сотрудника с ролью,
чек-листы адаптации/смены с фотоотчётом, поручения АУП со статусами и историей,
«не успеваю» (проблемы), полезные ссылки и обратная связь по окончании смены.

Модуль намеренно отделён от «наследного» `app.db.models.py`: так видно границу
между переиспользованным движком meetup-planner и новым доменом, а большой
файл моделей остаётся почти нетронутым. Регистрация таблиц для Alembic —
через импорт в конце `app.db.models` (см. `app.db.models` → `hr_models`).

Все статусы/роли — строки с CHECK-констрейнтом, а не PG-enum: правка набора
значений тогда не требует `ALTER TYPE` и переносится между диалектами.
"""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.org_models import OrgScoped

# --------------------------------------------------------------------------
# Роли и состояния (единый источник правды для сервисов и API)
# --------------------------------------------------------------------------

ROLE_EMPLOYEE = "employee"
ROLE_AUP = "aup"
ROLE_ADMIN = "admin"
ROLES: tuple[str, ...] = (ROLE_EMPLOYEE, ROLE_AUP, ROLE_ADMIN)

# Опыт работы из шага 3 онбординга.
EXPERIENCE_NEW = "new"
EXPERIENCE_EXPERIENCED = "experienced"
EXPERIENCES: tuple[str, ...] = (EXPERIENCE_NEW, EXPERIENCE_EXPERIENCED)

# Состояние прохождения первичной настройки.
ONBOARDING_NEW = "new"
ONBOARDING_DEPARTMENT = "department"
ONBOARDING_EXPERIENCE = "experience"
# Этап обучения пользованию приложением: короткие уроки, которые человек
# проходит после выбора подразделения и опыта (см. `services/hr_training.py`).
ONBOARDING_TRAINING = "training"
ONBOARDING_DONE = "done"
ONBOARDING_STATES: tuple[str, ...] = (
    ONBOARDING_NEW,
    ONBOARDING_DEPARTMENT,
    ONBOARDING_EXPERIENCE,
    ONBOARDING_TRAINING,
    ONBOARDING_DONE,
)

# Табель смен: что случилось в этот день. `planned` — смена стоит в графике,
# `worked` — человек отработал, остальное — объяснение пропуска. Учебные смены
# считаются по фактически отработанным (`worked`), а не по календарю.
SHIFT_PLANNED = "planned"
SHIFT_WORKED = "worked"
SHIFT_SICK = "sick"
SHIFT_ABSENT = "absent"
SHIFT_DAYOFF = "dayoff"
SHIFT_VACATION = "vacation"
SHIFT_STATUSES: tuple[str, ...] = (
    SHIFT_PLANNED,
    SHIFT_WORKED,
    SHIFT_SICK,
    SHIFT_ABSENT,
    SHIFT_DAYOFF,
    SHIFT_VACATION,
)
SHIFT_LABELS: dict[str, str] = {
    SHIFT_PLANNED: "Запланирована",
    SHIFT_WORKED: "Отработана",
    SHIFT_SICK: "Больничный",
    SHIFT_ABSENT: "Не пришёл",
    SHIFT_DAYOFF: "Выходной",
    SHIFT_VACATION: "Отпуск",
}
# Короткие метки для сетки табеля: одна буква не ломает узкую колонку.
SHIFT_SHORT: dict[str, str] = {
    SHIFT_PLANNED: "П",
    SHIFT_WORKED: "Р",
    SHIFT_SICK: "Б",
    SHIFT_ABSENT: "Н",
    SHIFT_DAYOFF: "В",
    SHIFT_VACATION: "О",
}

# Ставка сотрудника: полная или частичная. На расписание обучения не влияет —
# это отдельная строка в карточке, которую видит управляющий.
RATE_FULL = "full"
RATE_PARTIAL = "partial"
RATES: tuple[str, ...] = (RATE_FULL, RATE_PARTIAL)

# Вид чек-листа: первый рабочий день / смена (открытие зала) / закрытие смены.
# `close` — общий для всех залов: вечером зал уже не важен.
TEMPLATE_FIRST_DAY = "first_day"
TEMPLATE_SHIFT = "shift"
TEMPLATE_CLOSE = "close"
TEMPLATE_KINDS: tuple[str, ...] = (TEMPLATE_FIRST_DAY, TEMPLATE_SHIFT, TEMPLATE_CLOSE)

# Прогон чек-листа.
RUN_IN_PROGRESS = "in_progress"
RUN_DONE = "done"
RUN_STATUSES: tuple[str, ...] = (RUN_IN_PROGRESS, RUN_DONE)

# Получатель поручения.
TASK_SCOPE_DEPARTMENT = "department"
TASK_SCOPE_EMPLOYEE = "employee"
TASK_SCOPES: tuple[str, ...] = (TASK_SCOPE_DEPARTMENT, TASK_SCOPE_EMPLOYEE)

# Статусы поручения (п.4.3 mainPROMT) + проверка руководителем (MEGAPROMT2):
# `on_review` — сотрудник сдал работу, `rework` — руководитель вернул на
# доработку. Оба статуса появляются только у поручений с `requires_review`.
TASK_ON_REVIEW = "on_review"
TASK_REWORK = "rework"

TASK_NEW = "new"
TASK_ACCEPTED = "accepted"
TASK_IN_PROGRESS = "in_progress"
TASK_DONE = "done"
TASK_OVERDUE = "overdue"
TASK_FAILED = "failed"
TASK_STATUSES: tuple[str, ...] = (
    TASK_NEW,
    TASK_ACCEPTED,
    TASK_IN_PROGRESS,
    TASK_ON_REVIEW,
    TASK_REWORK,
    TASK_DONE,
    TASK_OVERDUE,
    TASK_FAILED,
)

PRIORITY_LOW = "low"
PRIORITY_NORMAL = "normal"
PRIORITY_HIGH = "high"
PRIORITIES: tuple[str, ...] = (PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_HIGH)

# Режим группового поручения (п.4 mainPROMT). До него поручение на
# подразделение жило одной строкой: «подразделение видит и кто-то закрывает».
# Это ломало два живых сценария: «каждый моет своё» (нужны отметки каждого) и
# «части работы» (у каждого свой кусок).
MODE_ONE_OF = "one_of"
MODE_EACH = "each"
MODE_PARTS = "parts"
TASK_MODES: tuple[str, ...] = (MODE_ONE_OF, MODE_EACH, MODE_PARTS)

# Журнал операционных проблем: карточка живёт отдельно от поручения и переживает
# смену. Категория — «что сломалось», зона — «где», срочность — «насколько
# горит». Наборы закрытые, чтобы журнал можно было считать и фильтровать.
ISSUE_CATEGORY_EQUIPMENT = "equipment"
ISSUE_CATEGORY_SUPPLIES = "supplies"
ISSUE_CATEGORY_STAFFING = "staffing"
ISSUE_CATEGORY_GUEST = "guest"
ISSUE_CATEGORY_CLEANLINESS = "cleanliness"
ISSUE_CATEGORY_SAFETY = "safety"
ISSUE_CATEGORY_IT = "it"
ISSUE_CATEGORY_OTHER = "other"
ISSUE_CATEGORIES: tuple[str, ...] = (
    ISSUE_CATEGORY_EQUIPMENT,
    ISSUE_CATEGORY_SUPPLIES,
    ISSUE_CATEGORY_STAFFING,
    ISSUE_CATEGORY_GUEST,
    ISSUE_CATEGORY_CLEANLINESS,
    ISSUE_CATEGORY_SAFETY,
    ISSUE_CATEGORY_IT,
    ISSUE_CATEGORY_OTHER,
)

ISSUE_SEVERITY_LOW = "low"
ISSUE_SEVERITY_NORMAL = "normal"
ISSUE_SEVERITY_HIGH = "high"
ISSUE_SEVERITY_CRITICAL = "critical"
ISSUE_SEVERITIES: tuple[str, ...] = (
    ISSUE_SEVERITY_LOW,
    ISSUE_SEVERITY_NORMAL,
    ISSUE_SEVERITY_HIGH,
    ISSUE_SEVERITY_CRITICAL,
)

# База стандартов: инструкция + короткий тест по ней. Уроки обучения
# (`services/hr_training.py`) знакомят с приложением, стандарты — с работой:
# как мыть руки, как подать блюдо, что делать с гостем-жалобой.
STANDARD_CATEGORY_DISHES = "dishes"
STANDARD_CATEGORY_EQUIPMENT = "equipment"
STANDARD_CATEGORY_SAFETY = "safety"
STANDARD_CATEGORY_SERVICE = "service"
STANDARD_CATEGORY_OTHER = "other"
STANDARD_CATEGORIES: tuple[str, ...] = (
    STANDARD_CATEGORY_DISHES,
    STANDARD_CATEGORY_EQUIPMENT,
    STANDARD_CATEGORY_SAFETY,
    STANDARD_CATEGORY_SERVICE,
    STANDARD_CATEGORY_OTHER,
)

# Порог сдачи теста: по умолчанию 80% правильных ответов.
DEFAULT_PASS_PERCENT = 80

ISSUE_OPEN = "open"
ISSUE_IN_PROGRESS = "in_progress"
ISSUE_RESOLVED = "resolved"
ISSUE_CANCELLED = "cancelled"
ISSUE_STATUSES: tuple[str, ...] = (
    ISSUE_OPEN,
    ISSUE_IN_PROGRESS,
    ISSUE_RESOLVED,
    ISSUE_CANCELLED,
)

# Передача смены: сдающий фиксирует, что не закрыто, и передаёт карточку
# принимающему. Подтверждение — отдельный статус, а не «галочка» в UI: без него
# никто не знает, увидел ли следующий человек чужие хвосты.
HANDOVER_SENT = "sent"
HANDOVER_ACCEPTED = "accepted"
HANDOVER_REJECTED = "rejected"
HANDOVER_STATUSES: tuple[str, ...] = (
    HANDOVER_SENT,
    HANDOVER_ACCEPTED,
    HANDOVER_REJECTED,
)

# Что попадает в сдачу: поручение или операционная проблема.
HANDOVER_ITEM_TASK = "task"
HANDOVER_ITEM_ISSUE = "issue"
HANDOVER_ITEM_KINDS: tuple[str, ...] = (HANDOVER_ITEM_TASK, HANDOVER_ITEM_ISSUE)
# Вид вопроса обратной связи.
QUESTION_SCALE = "scale"
QUESTION_CHOICE = "choice"
QUESTION_TEXT = "text"
QUESTION_KINDS: tuple[str, ...] = (QUESTION_SCALE, QUESTION_CHOICE, QUESTION_TEXT)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    """`col IN ('a','b')` для CHECK-констрейнта (значения — из кода, не из ввода)."""
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


# --------------------------------------------------------------------------
# Подразделения
# --------------------------------------------------------------------------


class Department(OrgScoped, Base):
    """Подразделение (повар/официант/бармен/менеджер и любые новые).

    Редактируется администратором из бота/мини-аппа без разработчика (шаг 2
    mainPROMT). `slug` — устойчивый машинный код (для сидинга и условий),
    `name`/`emoji` — то, что видит сотрудник.
    """

    __tablename__ = "departments"
    __table_args__ = (
        # Слаг уникален ВНУТРИ организации: у салона и у ресторана может быть
        # свой «bar» без конфликта (B2B_PLATFORM_PLAN, шаг 1.4).
        UniqueConstraint("org_id", "slug", name="uq_department_org_slug"),
        Index("ix_departments_active_sort", "is_active", "sort_order"),
    )

    # На проде BIGSERIAL, в sqlite-тестах INTEGER — как у `employees.id`.
    # Без варианта отдел нельзя завести, не задав id вручную, а мастер
    # настройки создаёт его именно вставкой без id.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# --------------------------------------------------------------------------
# Сотрудник
# --------------------------------------------------------------------------


class Employee(OrgScoped, Base):
    """HR-профиль сотрудника: 1:1 к `users` (личность/аватар живут там).

    Отдельная таблица, а не новые колонки в `users`, чтобы не трогать
    наследную модель и не ломать её сидинг. Строка создаётся лениво при первом
    обращении (`ensure_employee`) — тогда же назначается роль по умолчанию.
    """

    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint(_in_list("role", ROLES), name="ck_employee_role"),
        CheckConstraint(_in_list("rate_type", RATES), name="ck_employee_rate"),
        CheckConstraint(
            _in_list("onboarding_state", ONBOARDING_STATES),
            name="ck_employee_onboarding_state",
        ),
        CheckConstraint(
            "experience IS NULL OR " + _in_list("experience", EXPERIENCES),
            name="ck_employee_experience",
        ),
        # Человек может работать в двух организациях сети: одна личность —
        # две строки сотрудника, по одной на тенант (B2B_PLATFORM_PLAN, 1.4).
        UniqueConstraint("org_id", "user_id", name="uq_employee_org_user"),
        Index("ix_employees_department", "department_id", "is_active"),
        Index("ix_employees_demo", "is_demo"),
        Index("ix_employees_simulation", "is_simulation"),
    )

    # На проде BIGSERIAL, в sqlite-тестах INTEGER: без этого профиль
    # сотрудника нельзя создать, не задав id вручную.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    # `org_id` приходит из OrgScoped. `user_id` остаётся глобальным: один
    # человек — одна личность, членство живёт в `organization_members`.
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL")
    )
    # Должность/обязанность (например «су-шеф») — по ней матчатся условные
    # пункты чек-листа (`ChecklistItem.condition_position`).
    position: Mapped[str | None] = mapped_column(Text)
    # Плашка, которую сотрудник видит в боте и мини-аппе: должность или звание
    # («Разработчик», «Управляющий»). Должность (`position`) отвечает за работу
    # (условные пункты чек-листа), плашка — только за то, как человек подписан.
    badge: Mapped[str | None] = mapped_column(Text)
    badge_emoji: Mapped[str | None] = mapped_column(String(8))
    # Тестовый пул: сотрудники-симуляторы с префиксом `[BOT]`. Их активность
    # можно спрятать или снести одним переключателем (services/hr_demo.py).
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Теневой профиль режима проверки (`hr_simulation_sessions`): копия
    # сотрудника для безопасного прохождения сценариев. Все действия такого
    # профиля невидимы остальным и удаляются при выходе из режима.
    is_simulation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ROLE_EMPLOYEE, server_default=ROLE_EMPLOYEE
    )
    # Роль меняли руками (`/api/admin/me/role` или админский PATCH). Тогда
    # `ensure_employee` не повышает её обратно по env-списку — это и позволяет
    # управляющему временно «стать сотрудником» и вернуться.
    role_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    experience: Mapped[str | None] = mapped_column(String(16))
    onboarding_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ONBOARDING_NEW, server_default=ONBOARDING_NEW
    )
    # «Учимся вместе»: сотрудник выбрал продолжать обучение в следующих сменах.
    # Флаг ничего не блокирует — обязательные чек-листы, поручения и
    # уведомления работают одинаково в обоих режимах.
    learning_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # «Профиль открыт»: коллеги могут открыть карточку с активностью. Закрытый
    # профиль всё равно виден руководителю и администратору — иначе им нечем
    # работать (`services/hr_profile`).
    profile_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Последний заход в приложение. Пишется лениво (не чаще раза в пару минут)
    # из `/api/hr/me/employee`, поэтому не создаёт нагрузку на каждый запрос.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Две галочки приватности из профиля: показывать ли коллегам последний
    # заход и последнее медиа. Руководство может запретить их выключать —
    # тогда политика организации сильнее личного выбора (`services/org_setup`).
    show_last_seen: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    show_last_media: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Ставка: полная или частичная (`RATES`). Видна управляющему в расписании
    # обучения и самому сотруднику в профиле.
    rate_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RATE_FULL, server_default=RATE_FULL
    )
    # Сколько первых смен после `hire_date` считаются учебными. Точечные
    # исключения («сделать учебной четвёртую смену») — в `EmployeeTrainingDay`.
    training_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=3, server_default="3"
    )
    hire_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Увольнение (`services/hr_admin_ops`): с этого момента доступ в мини-апп и
    # к боту закрыт (`hr_access.ensure_employee`). Данные при этом НЕ удаляются —
    # руководитель выбирает: корзина на 30 дней или удаление сразу.
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Когда корзина истечёт: планировщик сносит такого сотрудника сам.
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # `trash` — лежит в корзине, `purge` — данные уже удалены (остаётся только
    # строка-надгробие, чтобы доступ не восстановился случайно).
    fired_mode: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class HrShift(OrgScoped, Base):
    """Табель: одна смена сотрудника в конкретный день.

    Строка заводится, когда управляющий ставит смену в график (`planned`), и
    дальше живёт своей жизнью: отработана, больничный, не пришёл, выходной,
    отпуск. `starts_at`/`ends_at` — необязательные часы (смена может пересекать
    полночь), `note` — короткое пояснение, `moved_from` — с какой даты смену
    перенесли, чтобы в табеле не терялась история.

    Уникальность `(employee_id, day)` не даёт двум сменам слипнуться в один
    день; перенос — это update даты с проверкой занятости, а не вторая строка.
    """

    __tablename__ = "hr_shifts"
    __table_args__ = (
        UniqueConstraint("employee_id", "day", name="uq_hr_shift_day"),
        CheckConstraint(_in_list("status", SHIFT_STATUSES), name="ck_hr_shift_status"),
        Index("ix_hr_shifts_day", "day"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SHIFT_PLANNED, server_default=SHIFT_PLANNED
    )
    starts_at: Mapped[time | None] = mapped_column(Time)
    ends_at: Mapped[time | None] = mapped_column(Time)
    note: Mapped[str | None] = mapped_column(Text)
    moved_from: Mapped[date | None] = mapped_column(Date)
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class HrShiftTemplate(OrgScoped, Base):
    """Именованный шаблон недели табеля («Официант · 5/2», «Бармен · выходные»).

    Хранит не смены на датах, а рисунок недели: день недели, статус и часы.
    Поэтому один шаблон применяется на любую неделю и не устаревает вместе с
    календарём. `pattern` — JSONB-список объектов
    `{"weekday": 0..6, "status": "planned", "starts_at": "10:00", "ends_at": "18:00"}`
    (0 = понедельник).

    `department_id IS NULL` — общий шаблон для всех подразделений; иначе
    шаблон принадлежит отделу и виден только его руководителю.
    """

    __tablename__ = "hr_shift_templates"
    __table_args__ = (
        UniqueConstraint(
            "department_id", "name", name="uq_hr_shift_template_name"
        ),
        Index("ix_hr_shift_templates_department", "department_id", "name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL")
    )
    pattern: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class EmployeeTrainingDay(OrgScoped, Base):
    """Точечная правка расписания: «эта смена учебная / обычная».

    По умолчанию учебные — первые `Employee.training_days` дней после
    `hire_date`. Строка здесь сильнее правила: управляющий может сделать
    учебной четвёртую смену или вернуть обычную третью, не меняя план целиком.
    Удаление строки возвращает расчёт по умолчанию.
    """

    __tablename__ = "employee_training_days"
    __table_args__ = (
        UniqueConstraint("employee_id", "day", name="uq_employee_training_day"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    is_training: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    set_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# --------------------------------------------------------------------------
# Чек-листы
# --------------------------------------------------------------------------


class Hall(OrgScoped, Base):
    """Зал ресторана (первый, второй, летняя веранда …).

    Заводится администратором в разделе «Чек-листы». Зал нужен только там, где
    у подразделения есть отдельные шаблоны под залы: официант перед чек-листом
    выбирает, в каком зале он сегодня работает. Если залов нет — выбора нет.
    """

    __tablename__ = "halls"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_hall_org_slug"),
        Index("ix_halls_active_sort", "is_active", "sort_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ChecklistTemplate(OrgScoped, Base):
    """Шаблон чек-листа подразделения.

    `hall_id` разделяет открытие по залам; NULL — общий шаблон (закрытие смены,
    первый день или заведение вообще без залов).
    """

    __tablename__ = "checklist_templates"
    __table_args__ = (
        CheckConstraint(_in_list("kind", TEMPLATE_KINDS), name="ck_checklist_template_kind"),
        Index("ix_checklist_templates_dept", "department_id", "is_active", "kind"),
        Index("ix_checklist_templates_hall", "hall_id", "kind", "is_active"),
    )

    # На проде BIGSERIAL, в sqlite-тестах INTEGER — как у `departments.id`.
    # Без варианта шаблон нельзя завести, не задав id вручную, а стартовую пару
    # шаблонов мастер создаёт именно вставкой без id.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    department_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False
    )
    # NULL — шаблон общий для всех залов подразделения.
    hall_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("halls.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TEMPLATE_SHIFT, server_default=TEMPLATE_SHIFT
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ChecklistItem(OrgScoped, Base):
    """Пункт чек-листа (п.3 mainPROMT).

    `requires_photo=True` — пункт нельзя закрыть без фото; `is_mandatory` — на
    прогресс «выполнено всё» влияют только обязательные; `condition_position`
    (опц.) — пункт показывается только сотрудникам с этой должностью (пример
    mainPROMT: бракераж — только су-шеф).
    """

    __tablename__ = "checklist_items"
    __table_args__ = (
        Index("ix_checklist_items_template", "template_id", "sort_order"),
    )

    # На проде BIGSERIAL, в sqlite-тестах INTEGER — как у `checklist_templates.id`.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    template_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("checklist_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    requires_photo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_mandatory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Показывать только сотрудникам с этой должностью (NULL — всем).
    condition_position: Mapped[str | None] = mapped_column(Text)
    # Дни недели, в которые пункт действует: CSV из ISO-номеров (1 = Пн …
    # 7 = Вс). NULL — каждый день. Пункт «по четвергам» виден всегда, но в
    # остальные дни неактивен и не входит в прогресс (`services/weekdays`).
    weekdays: Mapped[str | None] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ChecklistRun(OrgScoped, Base):
    """Прохождение чек-листа сотрудником за конкретную смену (дату)."""

    __tablename__ = "checklist_runs"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "template_id", "shift_date", name="uq_checklist_run_shift"
        ),
        CheckConstraint(_in_list("status", RUN_STATUSES), name="ck_checklist_run_status"),
        Index("ix_checklist_runs_employee_date", "employee_id", "shift_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("checklist_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    shift_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RUN_IN_PROGRESS, server_default=RUN_IN_PROGRESS
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ShiftHallChoice(OrgScoped, Base):
    """В каком зале сотрудник работает в эту смену.

    Хранится отдельно от прогона: прогон создаётся только при первой отметке, а
    зал нужно помнить сразу после выбора — иначе после перезагрузки экран снова
    спрашивал бы то же самое.
    """

    __tablename__ = "shift_hall_choices"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "shift_date", name="uq_shift_hall_choice"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    shift_date: Mapped[date] = mapped_column(Date, nullable=False)
    hall_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("halls.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChecklistCompletion(OrgScoped, Base):
    """Отметка пункта чек-листа: когда, кем, с фото и/или заметкой."""

    __tablename__ = "checklist_completions"
    __table_args__ = (
        UniqueConstraint("run_id", "item_id", name="uq_checklist_completion_item"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("checklist_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("checklist_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    done_by_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    done_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # TG file_id фотоотчёта (стабильнее протухающего file_path, как у аватарок).
    photo_file_id: Mapped[str | None] = mapped_column(Text)
    # Фото, загруженное прямо в мини-аппе: байты лежат в `media_blobs`, поэтому
    # оно не зависит от доступности Telegram и открывается в `<img>`.
    photo_media_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("media_blobs.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------
# Поручения АУП (задачи)
# --------------------------------------------------------------------------


class Task(OrgScoped, Base):
    """Поручение (п.4 mainPROMT).

    Получатель — подразделение (`scope='department'`) либо конкретный сотрудник
    (`scope='employee'`). Срок `due_at` опционален; просрочку проставляет
    планировщик (`services.tasks.sweep_overdue`).
    """

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(_in_list("scope", TASK_SCOPES), name="ck_task_scope"),
        CheckConstraint(_in_list("status", TASK_STATUSES), name="ck_task_status"),
        CheckConstraint(_in_list("priority", PRIORITIES), name="ck_task_priority"),
        CheckConstraint(_in_list("mode", TASK_MODES), name="ck_task_mode"),
        Index("ix_tasks_assignee_open", "assignee_employee_id", "status"),
        Index("ix_tasks_department_open", "department_id", "status"),
        Index("ix_tasks_due", "status", "due_at"),
        Index("ix_tasks_shift", "shift_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    expected_result: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TASK_SCOPE_EMPLOYEE, server_default=TASK_SCOPE_EMPLOYEE
    )
    # `one_of` — «один за всех» (закрывает любой), `each` — «каждый сам»,
    # `parts` — «части работы» (у каждого своя часть в `task_assignments`).
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MODE_ONE_OF, server_default=MODE_ONE_OF
    )
    # Смена, на которую выдано поручение. `None` — «на общих основаниях»
    # (задача на неделю, а не на конкретную смену).
    shift_date: Mapped[date | None] = mapped_column(Date)
    # Поручение с проверкой: сотрудник сдаёт работу (`on_review`), а принимает
    # руководитель (`done` / `rework`). По умолчанию выключено — старые и
    # простые поручения закрываются отметкой исполнителя, как раньше.
    requires_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Заполнен при scope='department'.
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL")
    )
    # Заполнен при scope='employee'.
    assignee_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PRIORITY_NORMAL, server_default=PRIORITY_NORMAL
    )
    requires_photo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Дни недели, в которые поручение «сегодняшнее» (CSV ISO-номеров, NULL —
    # каждый день). В остальные дни оно остаётся в списке, но помечено как
    # неактивное и не попадает в счётчики «горящего».
    weekdays: Mapped[str | None] = mapped_column(String(32))
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TASK_NEW, server_default=TASK_NEW
    )
    created_by_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TaskAssignment(OrgScoped, Base):
    """Состояние поручения у конкретного исполнителя.

    Одна строка на человека — то, чего не хватало групповым поручениям: «каждый
    сам» и «части работы» требуют отметки каждого, а не одной галочки на всех.
    Для режима `one_of` строки тоже есть (кто взял и кто закрыл), но решает
    любой первый — агрегат в `Task.status` закрывается сразу.
    """

    __tablename__ = "task_assignments"
    __table_args__ = (
        UniqueConstraint("task_id", "employee_id", name="uq_task_assignment"),
        CheckConstraint(_in_list("status", TASK_STATUSES), name="ck_task_assignment_status"),
        Index("ix_task_assignments_employee", "employee_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TASK_NEW, server_default=TASK_NEW
    )
    # Текст части для режима `parts`: «мойка холодильника», «витрина».
    part: Mapped[str | None] = mapped_column(Text)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TaskEvent(OrgScoped, Base):
    """История изменений поручения (аудит: кто, когда, из какого статуса в какой)."""

    __tablename__ = "task_events"
    __table_args__ = (Index("ix_task_events_task", "task_id", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    by_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    comment: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TaskReminder(OrgScoped, Base):
    """Ручная правка запланированного напоминания (админка).

    Планировщик считает время напоминания сам: `due_at` минус настройка «за
    сколько минут». Иногда это время нужно сдвинуть или выключить, не трогая
    срок поручения — тогда здесь лежит правило, которое сильнее расчёта.

    `skip` — по задаче не напоминать, `remind_at` — своё время отправки.
    Одна строка на задачу; удаление строки возвращает расчёт по умолчанию.
    """

    __tablename__ = "task_reminders"
    __table_args__ = (UniqueConstraint("task_id", name="uq_task_reminders_task"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    remind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skip: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TaskIssue(OrgScoped, Base):
    """«Не успеваю / есть проблема» по поручению (п.4.5).

    Причина из списка (`reason_code`) + свободный комментарий + желаемое время.
    АУП видит проблему в списке и получает уведомление.
    """

    __tablename__ = "task_issues"
    __table_args__ = (Index("ix_task_issues_task", "task_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    reason_code: Mapped[str | None] = mapped_column(String(32))
    comment: Mapped[str | None] = mapped_column(Text)
    eta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TaskPhoto(OrgScoped, Base):
    """Фотоотчёт по поручению (п.4.4).

    Храним TG `file_id` (а не протухающий URL): мини-апп показывает фото через
    прокси, бот может переслать его руководителю.
    """

    __tablename__ = "task_photos"
    __table_args__ = (Index("ix_task_photos_task", "task_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    # `file_id` остаётся для фото из чата; `media_id` — для загрузки из
    # мини-аппа и для кеша, снятого с Telegram (тогда заполнены оба поля).
    file_id: Mapped[str | None] = mapped_column(Text)
    media_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("media_blobs.id", ondelete="SET NULL")
    )
    # Одобрение руководителем — заглушка под Этап 3 («подтверждение фотоотчётов»).
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MediaBlob(OrgScoped, Base):
    """Байты фотоотчёта, загруженного в мини-аппе.

    Раньше хранился только Telegram `file_id`: картинку нельзя было показать в
    приложении (у `<img>` нет доступа к Bot API), а при недоступном Telegram
    фото пропадало совсем. Теперь байты лежат в БД: `GET /api/media/{id}`
    отдаёт их с подписью, поэтому фото видно и в приложении, и после рестарта,
    без токена бота наружу.

    `sha256` даёт дедупликацию: повторная отправка того же снимка не раздувает
    базу. `telegram_file_id` заполнен, если блоб — кеш фото из чата.
    """

    __tablename__ = "media_blobs"
    __table_args__ = (
        # Одинаковый снимок в двух организациях — разные блобы: иначе вторая
        # не смогла бы его загрузить, а первая получила бы чужой по id.
        UniqueConstraint("org_id", "sha256", name="uq_media_blobs_org_sha"),
        Index("ix_media_blobs_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime: Mapped[str] = mapped_column(String(64), nullable=False, default="image/jpeg")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    telegram_file_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------
# Журнал операционных проблем
# --------------------------------------------------------------------------


class Issue(OrgScoped, Base):
    """Операционная проблема смены как отдельная карточка.

    Отличие от `TaskIssue` (объяснение «не успеваю» по поручению): здесь нет
    поручения, из которого всё началось. Проблема может висеть неделю — «течёт
    кран», «не работает терминал», «гость жалуется на шум» — переходить между
    сменами и людьми, обрастать комментариями и закрываться тогда, когда её
    реально решили. `task_id` — необязательная ссылка на поручение, чтобы
    журнал и задачи не разъезжались, если проблема пришла из задачи.

    `shift_date` — смена, на которой проблему зафиксировали. Это не срок
    решения: по нему журнал группируется в отчёте «что было в смене».
    """

    __tablename__ = "hr_issues"
    __table_args__ = (
        CheckConstraint(_in_list("category", ISSUE_CATEGORIES), name="ck_hr_issue_category"),
        CheckConstraint(_in_list("severity", ISSUE_SEVERITIES), name="ck_hr_issue_severity"),
        CheckConstraint(_in_list("status", ISSUE_STATUSES), name="ck_hr_issue_status"),
        Index("ix_hr_issues_status", "status", "severity"),
        Index("ix_hr_issues_department", "department_id", "status"),
        Index("ix_hr_issues_assignee", "assignee_employee_id", "status"),
        Index("ix_hr_issues_shift", "shift_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ISSUE_CATEGORY_OTHER,
        server_default=ISSUE_CATEGORY_OTHER,
    )
    # Свободный текст: «зал», «кухня», «бар», «склад», «касса №2».
    zone: Mapped[str | None] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ISSUE_SEVERITY_NORMAL,
        server_default=ISSUE_SEVERITY_NORMAL,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ISSUE_OPEN, server_default=ISSUE_OPEN
    )
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL")
    )
    # Кто отвечает сейчас. Меняется по ходу жизни карточки.
    assignee_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    created_by_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    task_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("tasks.id", ondelete="SET NULL")
    )
    shift_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IssueEvent(OrgScoped, Base):
    """История карточки: создание, смена статуса/ответственного, комментарии.

    Отдельная таблица, а не поле «последний комментарий»: журнал нужен именно
    затем, чтобы через смену было видно, кто и что с проблемой делал.
    """

    __tablename__ = "hr_issue_events"
    __table_args__ = (Index("ix_hr_issue_events_issue", "issue_id", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("hr_issues.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str | None] = mapped_column(String(16))
    by_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    comment: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------
# Передача смены
# --------------------------------------------------------------------------


class Handover(OrgScoped, Base):
    """Сдача смены: кто, кому и что оставил открытым.

    `hr_handover_items` хранит СНИМОК на момент передачи: через сутки задача уже
    может быть закрыта, но в истории сдачи должно остаться, что именно висело
    на смене и кто это принял. Поэтому название и статус копируются, а `ref_id`
    остаётся ссылкой на живую задачу/проблему.
    """

    __tablename__ = "hr_handovers"
    __table_args__ = (
        CheckConstraint(_in_list("status", HANDOVER_STATUSES), name="ck_hr_handover_status"),
        Index("ix_hr_handovers_to", "to_employee_id", "status"),
        Index("ix_hr_handovers_from", "from_employee_id", "created_at"),
        Index("ix_hr_handovers_shift", "shift_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL")
    )
    from_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    to_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    # Кто подтвердил приём — фиксируется отдельно от `to_employee_id`, потому
    # что карточку могла принять и замена.
    accepted_by_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=HANDOVER_SENT, server_default=HANDOVER_SENT
    )
    note: Mapped[str | None] = mapped_column(Text)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    shift_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HandoverItem(OrgScoped, Base):
    """Снимок одного открытого пункта, который передали следующей смене."""

    __tablename__ = "hr_handover_items"
    __table_args__ = (
        CheckConstraint(_in_list("kind", HANDOVER_ITEM_KINDS), name="ck_hr_handover_item_kind"),
        Index("ix_hr_handover_items_handover", "handover_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    handover_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("hr_handovers.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ref_id: Mapped[int | None] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Срок/зона/срочность одной строкой — чтобы снимок читался без живых таблиц.
    meta: Mapped[str | None] = mapped_column(String(128))


# --------------------------------------------------------------------------
# База стандартов
# --------------------------------------------------------------------------


class Standard(OrgScoped, Base):
    """Инструкция по работе: что делать и как правильно.

    Свободный текст (`body`) вместо файлов-вложений: стандарт пишет
    руководитель прямо в приложении, и он должен читаться с телефона. Тест —
    отдельные строки (`StandardQuestion`), чтобы правка одного вопроса не
    задевала остальные.
    """

    __tablename__ = "standards"
    __table_args__ = (
        CheckConstraint(_in_list("category", STANDARD_CATEGORIES), name="ck_standard_category"),
        Index("ix_standards_active_sort", "is_active", "sort_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default=STANDARD_CATEGORY_OTHER,
        server_default=STANDARD_CATEGORY_OTHER,
    )
    summary: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # `NULL` — стандарт общий для всех подразделений.
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL")
    )
    pass_percent: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=DEFAULT_PASS_PERCENT,
        server_default=str(DEFAULT_PASS_PERCENT),
    )
    # Обязательный стандарт попадает в пробелы отчёта: «кто ещё не сдал».
    # Необязательный остаётся справочником и в отчёт не тянется.
    is_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class StandardQuestion(OrgScoped, Base):
    """Вопрос теста к стандарту. `options` — варианты, `correct_index` — верный."""

    __tablename__ = "standard_questions"
    __table_args__ = (Index("ix_standard_questions_standard", "standard_id", "sort_order"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    standard_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("standards.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    correct_index: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class StandardCheck(OrgScoped, Base):
    """Результат прохождения теста: фиксируем историей, а не последним баллом.

    Пересдавать можно — в обучении это нормально; в профиле показываем
    последнюю попытку, а предыдущие остаются для разбора.
    """

    __tablename__ = "standard_checks"
    __table_args__ = (
        Index("ix_standard_checks_employee", "employee_id", "at"),
        Index("ix_standard_checks_standard", "standard_id", "passed"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    standard_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("standards.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    total: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    correct: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    percent: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    answers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------
# Полезные ссылки (п.8)
# --------------------------------------------------------------------------


class UsefulLink(OrgScoped, Base):
    """Ссылка в разделе «Полезные ссылки» (График, Фудбук, …).

    `department_id IS NULL` — видна всем; иначе только своему подразделению.
    """

    __tablename__ = "useful_links"
    __table_args__ = (Index("ix_useful_links_active_sort", "is_active", "sort_order"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(16))
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="CASCADE")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# --------------------------------------------------------------------------
# Обратная связь по окончании смены (п.7)
# --------------------------------------------------------------------------


class FeedbackQuestion(OrgScoped, Base):
    """Вопрос формы обратной связи — настраивается администратором.

    `kind`: `scale` (оценка 1..5), `choice` (вариант из `options`), `text`
    (свободный ответ). `options` — JSONB-список строк для `choice`.
    """

    __tablename__ = "feedback_questions"
    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_feedback_question_org_code"),
        CheckConstraint(_in_list("kind", QUESTION_KINDS), name="ck_feedback_question_kind"),
        Index("ix_feedback_questions_active_sort", "is_active", "sort_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default=QUESTION_SCALE, server_default=QUESTION_SCALE
    )
    options: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class FeedbackAnswer(OrgScoped, Base):
    """Ответ сотрудника на вопрос формы за смену (дату)."""

    __tablename__ = "feedback_answers"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "shift_date", "question_id", name="uq_feedback_answer"
        ),
        Index("ix_feedback_answers_date", "shift_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    shift_date: Mapped[date] = mapped_column(Date, nullable=False)
    question_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("feedback_questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    value_scale: Mapped[int | None] = mapped_column(SmallInteger)
    value_choice: Mapped[str | None] = mapped_column(Text)
    value_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------
# Скрытые ачивки сотрудника (личный прогресс)
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Режим проверки (имитация сотрудника)
# --------------------------------------------------------------------------

SIM_ACTIVE = "active"
SIM_ENDED = "ended"
SIM_FAILED = "failed"
SIM_STATUSES: tuple[str, ...] = (SIM_ACTIVE, SIM_ENDED, SIM_FAILED)
SIM_MODE_NEW = "new"
SIM_MODE_AS_IS = "as_is"
SIM_MODES: tuple[str, ...] = (SIM_MODE_NEW, SIM_MODE_AS_IS)


class SimulationSession(OrgScoped, Base):
    """Сеанс проверки приложения глазами сотрудника.

    Зачем отдельная таблица, а не просто «переключить employee_id в клиенте»:
    приложению нужен теневой профиль (`employees.is_simulation`), к которому
    привязаны все тестовые задачи, смены, проблемы и уведомления. Сеанс — это
    аудит-запись: кто проверял, кого, в каком режиме и когда закончил. Она
    остаётся после очистки, а тестовые данные — нет.

    `shadow_employee_id` — тот самый теневой профиль. У него отдельный
    `users`-row с отрицательным Telegram ID, поэтому личные сообщения никогда
    не уйдут реальному человеку.
    """

    __tablename__ = "hr_simulation_sessions"
    __table_args__ = (
        CheckConstraint(_in_list("status", SIM_STATUSES), name="ck_sim_status"),
        CheckConstraint(_in_list("mode", SIM_MODES), name="ck_sim_mode"),
        Index("ix_sim_sessions_actor", "actor_employee_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    subject_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    shadow_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    # Снимок на момент старта: после очистки теневого профиля аудит всё равно
    # должен отвечать «кого и в каком виде проверяли».
    subject_name: Mapped[str | None] = mapped_column(Text)
    subject_department_name: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SIM_MODE_NEW, server_default=SIM_MODE_NEW
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SIM_ACTIVE, server_default=SIM_ACTIVE
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleanup_error: Mapped[str | None] = mapped_column(Text)
    tasks_cleaned: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    runs_cleaned: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    issues_cleaned: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )


class EmployeeAchievement(OrgScoped, Base):
    """Выданная ачивка: `code` из каталога + когда получена.

    Строка, а не колонка-счётчик: ачивки копятся историей, поэтому выдать их
    можно ровно один раз (`unique(employee_id, code)`) и показать по порядку.
    Пересчёт идёт на чтение профиля (`services/hr_achievements.py`), так что
    рассинхрон «порог взят, а строки нет» невозможен — состояние выводится из
    исходных данных.

    Видимость ачивок в продукте — отдельное правило и живёт в сервисе: сейчас
    блок в профиле видят только руководитель (`aup`) и администратор бота.
    """

    __tablename__ = "employee_achievements"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "code", name="uq_employee_achievement_code"
        ),
        Index(
            "ix_employee_achievements_employee", "employee_id", "awarded_at"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    awarded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------
class Kudos(OrgScoped, Base):
    """«Спасибо коллеге» — благодарность, которую видно в ленте.

    Отдельная таблица, а не поле у поручения: поблагодарить можно и за то, чего
    в системе нет — за подмену, за спокойную смену, за помощь с гостем. Из этой
    же таблицы считается недельный топ, поэтому агрегат не расходится с лентой:
    источник один.

    Анти-накрутка выражена схемой, а не только проверкой в коде:
    `unique(from_employee_id, to_employee_id, day)` не даёт набить топ повторными
    нажатиями (в том числе двумя одновременными запросами), а дневной лимит
    отправителя не даёт раздать «спасибо» всем подряд: награда, которую выдают
    каждому, перестаёт что-либо значить.
    """

    __tablename__ = "hr_kudos"
    __table_args__ = (
        UniqueConstraint(
            "from_employee_id",
            "to_employee_id",
            "day",
            name="uq_kudos_pair_day",
        ),
        CheckConstraint(
            "from_employee_id <> to_employee_id", name="ck_kudos_not_self"
        ),
        Index("ix_hr_kudos_to_day", "to_employee_id", "day"),
        Index("ix_hr_kudos_from_day", "from_employee_id", "day"),
    )

    # `with_variant(Integer, "sqlite")` — как у остальных таблиц, которые
    # пишутся без заранее известного id: в SQLite только `INTEGER PRIMARY KEY`
    # получает автоинкремент, `BIGINT PRIMARY KEY` — нет, и вторая строка
    # падала бы на «дубле» NULL-ключа.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    from_employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Дата по часам заведения, а не UTC-дата: смена кончается после полуночи, и
    # «спасибо за смену» не должно уезжать во вчера.
    day: Mapped[date] = mapped_column(Date, nullable=False)
    message: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------
# Обучение пользованию приложением (шаг онбординга)
# --------------------------------------------------------------------------


class EmployeeTrainingStep(OrgScoped, Base):
    """Пройденный урок знакомства с приложением.

    Каталог уроков живёт в коде (`services/hr_training.py`): это текст, который
    меняется вместе с интерфейсом. В БД храним только факт прохождения, чтобы
    прогресс не сбрасывался и не дублировался (`unique(employee_id, code)`).
    """

    __tablename__ = "employee_training_steps"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "code", name="uq_employee_training_step_code"
        ),
        Index("ix_employee_training_steps_employee", "employee_id", "completed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------
# Материалы смены из Google Sheets
# --------------------------------------------------------------------------


class SheetSource(OrgScoped, Base):
    """Внешняя таблица, содержимое которой показываем в приложении.

    Зачем копия в БД, а не ссылка «открыть Google»: в России Google Sheets
    открывается нестабильно, а иногда недоступен вовсе. Сервер (HF Space)
    забирает CSV и хранит последний удачный снимок, поэтому сотрудник видит
    актуальный график/меню даже тогда, когда сама таблица у него не грузится.

    `rows_json` — снимок `list[list[str]]` (строки как есть, без заголовков-
    догадок). `synced_at` и `sync_error` показывают, насколько данным можно
    верить: при ошибке старые строки НЕ затираются.
    """

    __tablename__ = "sheet_sources"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "spreadsheet_id", "gid", name="uq_sheet_sources_org_sheet"
        ),
        Index("ix_sheet_sources_sort", "sort_order", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(16))
    # Оригинальная ссылка для «открыть в Google» (может не работать без VPN).
    url: Mapped[str] = mapped_column(Text, nullable=False)
    spreadsheet_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # `gid` — номер листа. Пустой означает первый лист.
    gid: Mapped[str | None] = mapped_column(String(32))
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL")
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    rows_json: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RosterSnapshot(OrgScoped, Base):
    """Снимок состава: кто заведён в боте на этот момент.

    Зачем отдельная таблица, а не лог изменений. Пул Telegram-ID — самое
    дорогое, что есть в базе: его нельзя восстановить из Telegram, только
    заново собирать у людей. Поэтому любое действие, которое может удалить
    людей (`fire(mode=purge)`, `demo/purge` с `delete_employees`), сначала
    складывает сюда состав целиком.

    `payload` — JSONB-список людей (`telegram_id`, имя, отдел, должность,
    роль...) без внутренних `id`: восстанавливать надо по Telegram-ID, а не по
    номерам строк, которые после удаления переиспользуются.
    """

    __tablename__ = "hr_roster_snapshots"
    __table_args__ = (
        CheckConstraint(
            _in_list("kind", ("manual", "auto")), name="ck_roster_snapshot_kind"
        ),
        Index("ix_roster_snapshots_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual"
    )
    # Почему сняли: `employees` (кнопка), `fire:purge`, `demo:purge`.
    source: Mapped[str] = mapped_column(
        String(48), nullable=False, default="", server_default=""
    )
    people_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    payload: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    created_by_employee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("employees.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AppAccessLink(OrgScoped, Base):
    """Ссылка входа в приложение из браузера (вне Telegram).

    Зачем. Внутри мини-аппа личность подтверждает `initData` — подпись бота,
    которую Telegram кладёт в WebApp. В обычном браузере (Pages по прямой
    ссылке) этого нет, поэтому нужен свой вход. Пароль не заводим: сотруднику
    и так выдали Telegram, и второй пароль он забудет.

    Как устроено. Сервер генерирует длинный случайный токен, отдаёт его один
    раз в ссылке `…/?access=…`, а в базе хранит только SHA-256. Утечка дампа
    БД тогда не даёт входа. Срок жизни ограничен, ссылку можно отозвать.

    `last_used_at` нужен человеку, а не серверу: в профиле видно, когда ссылку
    последний раз использовали, — если это было не он, ссылку отзывают.
    """

    __tablename__ = "app_access_links"
    __table_args__ = (
        Index("ix_app_access_links_user", "user_id"),
        Index("ix_app_access_links_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SHA-256 от токена: сам токен в базе не хранится никогда.
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TranslationCache(Base):
    """Перевод строки данных на язык интерфейса (план, 11).

    Зачем таблица, а не «перевести на месте». Модель живёт только там, где есть
    память (HF Space, 16 ГБ). У Amvera 0,5 ГБ, и там её нет физически — зато
    ровно та же база. Поэтому посчитанный один раз перевод становится общим:
    первый хост считает, второй отдаёт.

    Почему в ключе хэш, а не текст. `source_hash` = sha256(текст + язык). В
    таблице нет ни исходной строки, ни её фрагментов: кэш не должен становиться
    второй копией заданий и переписки. Хэша достаточно, чтобы найти готовое, и
    недостаточно, чтобы прочитать чужое.

    Таблица НЕ тенантная сознательно: одинаковый текст («Помыть пол в зале»)
    переводится одинаково в любой организации, и хранить его дважды нет смысла.
    Утечки это не даёт — в строке лежит только перевод того текста, который
    запросивший и так видит.
    """

    __tablename__ = "translation_cache"
    __table_args__ = (
        UniqueConstraint("source_hash", "target", name="uq_translation_hash_target"),
    )

    # `with_variant(Integer, "sqlite")` — как у остальных таблиц проекта:
    # SQLite не делает BIGINT первичным ключом с автоинкрементом, и без этого
    # вставка падала бы на `NOT NULL constraint failed: translation_cache.id`.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(8), nullable=False)
    translated: Mapped[str] = mapped_column(Text, nullable=False)
    # Чем переведено: имя провайдера («small100»). Нужно, чтобы при смене
    # модели было видно происхождение строки, не пересчитывая всё заново.
    provider: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
