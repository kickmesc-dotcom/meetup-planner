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
from app.db.org_models import current_org_id

log = structlog.get_logger()

# Уровни прав: больше — шире.
_ROLE_RANK: dict[str, int] = {ROLE_EMPLOYEE: 0, ROLE_AUP: 1, ROLE_ADMIN: 2}

# Роль организации → HR-роль нового профиля. Приглашение выписывается уровнем
# доступа («manager»), а интерфейс спрашивает HR-роль, поэтому связка должна
# быть одна — та же, что в миграции 0056 (admin→owner, aup→manager, staff).
_ORG_ROLE_TO_HR: dict[str, str] = {
    "owner": ROLE_ADMIN,
    "manager": ROLE_AUP,
    "staff": ROLE_EMPLOYEE,
}


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

    # Почему роль берётся из членства. Приглашённого позвали управляющим —
    # значит его HR-роль должна быть `aup`, иначе человек попадёт в приложение
    # сотрудником без админки и менеджер будет искать причину в правах.
    # Env-админ по-прежнему сильнее: `default_role_for` уже вернул `admin`.
    from app.services import orgs

    org_id = current_org_id.get()
    role = default_role_for(user.telegram_id or 0)
    if role != ROLE_ADMIN:
        membership = await orgs.member(session, org_id=org_id, user_id=user.id)
        role = _ORG_ROLE_TO_HR.get(
            membership.role if membership is not None else "staff", ROLE_EMPLOYEE
        )

    employee = Employee(
        user_id=user.id,
        role=role,
        onboarding_state=ONBOARDING_NEW,
    )
    # Приглашение могло нести должность и отдел. Профиля до этого момента не
    # было, поэтому применить их было некуда — делаем это здесь, один раз, при
    # создании строки.
    from app.db.org_models import OrgInvitation

    invitation = await session.scalar(
        select(OrgInvitation)
        .where(
            OrgInvitation.org_id == org_id,
            OrgInvitation.accepted_by_user_id == user.id,
        )
        .order_by(OrgInvitation.accepted_at.desc())
    )
    if invitation is not None:
        employee.position = invitation.position
        employee.department_id = invitation.department_id
    session.add(employee)
    await session.flush()
    # Сотрудник без членства — это сотрудник, которого не видно ни в одной
    # организации: связь создаём сразу, в организации из контекста.
    await orgs.ensure_member(session, org_id=org_id, user_id=user.id)
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


def hr_role_for_org(role: str) -> str:
    """HR-роль для уровня доступа в организации.

    Публичная обёртка над таблицей соответствий: ручка смены роли участника не
    должна тянуть приватный словарь, иначе переименование поля сломает API.
    """
    return _ORG_ROLE_TO_HR.get(role, ROLE_EMPLOYEE)


def set_role(employee: Employee, role: str) -> None:
    """Сменить роль с валидацией (используется админским API).

    Ставит `role_locked`, чтобы `ensure_employee` не вернул env-админу роль
    назад на следующем запросе: ручной выбор должен жить.
    """
    if role not in _ROLE_RANK:
        raise HrAccessError(f"unknown_role:{role}")
    employee.role = role
    employee.role_locked = True
