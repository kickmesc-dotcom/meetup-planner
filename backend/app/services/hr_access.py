"""Сотрудники и права доступа HR-ядра (SemiTaskBot, Этап 1).

Здесь только то, что нужно КАЖДОМУ другому hr-сервису: получить/создать
`Employee` и понять, что человеку можно делать. Права проверяются на сервере
(п.11 mainPROMT: «все права должны проверяться на стороне системы, а не только
скрытием кнопок»), поэтому `is_aup`/`is_admin` — единственный источник правды
и для API, и для бота.

Роли:
- `employee` — сотрудник: свои чек-листы, поручения, ссылки, обратная связь;
- `aup`      — руководитель: + создание поручений/встреч, просмотр отчётов;
- `admin`    — администратор бота: + управление подразделениями/чек-листами/
               ссылками/ролями.

Админский Telegram-ID из env (`ADMIN_TG_IDS`) действует как «супер-админ» и
переводит роль в `admin` автоматически — так первый администратор появляется
без правки БД (та же идея, что в `config.admin_tg_id_set`).
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.hr_models import (
    ONBOARDING_DONE,
    ONBOARDING_NEW,
    ROLE_ADMIN,
    ROLE_AUP,
    ROLE_EMPLOYEE,
    Employee,
)
from app.db.models import User

log = structlog.get_logger()

# Уровни прав: больше — шире.
_ROLE_RANK: dict[str, int] = {ROLE_EMPLOYEE: 0, ROLE_AUP: 1, ROLE_ADMIN: 2}


class HrAccessError(Exception):
    """Базовая ошибка доступа/состояния сотрудника."""


def role_rank(role: str) -> int:
    return _ROLE_RANK.get(role, 0)


def default_role_for(telegram_id: int) -> str:
    """Роль по умолчанию при создании профиля.

    `admin` — владельцы (`ADMIN_TG_IDS`) и «шестёрка» (`WHITELIST_TG_IDS`):
    их же пропуск в админку. Остальные приходят сотрудниками — Mini App
    открыт всем, но управление остаётся за прописанными людьми.
    """
    if telegram_id in get_settings().staff_tg_id_set:
        return ROLE_ADMIN
    return ROLE_EMPLOYEE


async def get_employee(session: AsyncSession, user_id: int) -> Employee | None:
    """HR-профиль по внутреннему `users.id` (None, если ещё не заводили)."""
    return await session.scalar(select(Employee).where(Employee.user_id == user_id))


async def ensure_employee(session: AsyncSession, user: User) -> Employee:
    """Вернуть профиль сотрудника, создав его при первом обращении.

    Ленивое создание выбрано сознательно: `users` уже сидируется на старте, а
    HR-профиль наполняется данными только когда человек реально пришёл в бота
    или мини-апп — не хотим плодить пустые строки наперёд.
    """
    employee = await get_employee(session, user.id)
    if employee is not None:
        # Уволенный не работает в приложении и не пишет боту: доступ закрыт,
        # пока его не вернут из корзины (`services/hr_admin_ops.restore`).
        if employee.fired_at is not None:
            raise HrAccessError("employee_fired")
        # Админ из env должен получить права, даже если строка создана раньше
        # (человека добавили в ADMIN_TG_IDS уже после первого захода). Но
        # `role_locked` сильнее env: если роль меняли руками (в том числе
        # управляющий снял себе роль, чтобы посмотреть приложение глазами
        # сотрудника), автоматическое повышение её не откатит.
        if (
            user.telegram_id in get_settings().staff_tg_id_set
            and employee.role != ROLE_ADMIN
            and not employee.role_locked
        ):
            employee.role = ROLE_ADMIN
            await session.flush()
        return employee

    employee = Employee(
        user_id=user.id,
        role=default_role_for(user.telegram_id),
        onboarding_state=ONBOARDING_NEW,
    )
    session.add(employee)
    await session.flush()
    log.info("hr.employee_created", user_id=user.id, role=employee.role)
    return employee


def is_employee(employee: Employee | None) -> bool:
    return employee is not None


def is_fired(employee: Employee | None) -> bool:
    """Уволен ли сотрудник (данные при этом могут ещё лежать в корзине)."""
    return employee is not None and employee.fired_at is not None


def is_aup(employee: Employee | None) -> bool:
    """Руководитель или админ."""
    return employee is not None and role_rank(employee.role) >= role_rank(ROLE_AUP)


def is_admin(employee: Employee | None) -> bool:
    return employee is not None and role_rank(employee.role) >= role_rank(ROLE_ADMIN)


def is_staff(employee: Employee | None, user: User | None) -> bool:
    """Прописанный доступ в админку (шестёрка / владельцы), независимо от роли.

    Нужен ровно для одного сценария: администратор временно снимает себе роль,
    чтобы увидеть приложение глазами сотрудника, но кабинет управления у него
    остаётся — иначе вернуть роль было бы нечем.
    """
    if user is None:
        return False
    return user.telegram_id in get_settings().staff_tg_id_set


def onboarding_finished(employee: Employee) -> bool:
    return employee.onboarding_state == ONBOARDING_DONE


def set_role(employee: Employee, role: str) -> None:
    """Сменить роль с валидацией (используется админским API).

    Ставит `role_locked`, чтобы `ensure_employee` не вернул env-админу роль
    назад на следующем запросе: ручной выбор должен жить.
    """
    if role not in _ROLE_RANK:
        raise HrAccessError(f"unknown_role:{role}")
    employee.role = role
    employee.role_locked = True
