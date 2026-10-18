from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.initdata import InitDataError, InitDataPayload, parse_and_verify
from app.config import Settings, get_settings
from app.db.base import get_sessionmaker
from app.db.hr_models import Employee
from app.db.models import User
from app.services import display_names


async def db_session() -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker()
    async with sm() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(db_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def resync_if_expired(session: AsyncSession, *objects: object) -> None:
    """Перечитать объекты, которые экспайрили игровые награды.

    Зачем это нужно отдельным хелпером. Игровая система обязана «не ломать
    бота»: любое её исключение ловит `awards._guarded` и делает
    `session.rollback()`. Rollback — единственное место, которое экспайрит ВСЕ
    объекты сессии даже при `expire_on_commit=False`, а FastAPI сериализует
    `response_model` уже вне greenlet'а. Итог: экспайренный объект даёт
    `MissingGreenlet` и HTTP 500 на УЖЕ сохранённых данных — именно так тап по
    свободному дню создавал диапазон, но показывал ошибку, а клетка зеленела
    только после следующего рефетча.

    Дёшево: лишний SELECT только если объект действительно экспайрен.
    """
    for obj in objects:
        if obj is not None and sa_inspect(obj).expired:
            await session.refresh(obj)


async def _create_user(session: AsyncSession, payload: InitDataPayload) -> User:
    """Завести `users`-строку для нового человека из Telegram.

    Имя берём из подписанных данных (имя + фамилия), иначе username, иначе
    нейтральное «Сотрудник». Цвет — детерминированно из общей палитры, чтобы
    аватарка-инициалы не мигала разными цветами между заходами.
    """
    from app.db.seed import color_for_user
    from app.services.display_names import compose_display_name

    user = User(
        telegram_id=payload.user_id,
        display_name=compose_display_name(
            payload.first_name,
            payload.last_name,
            payload.username,
            fallback_id=payload.user_id,
        ),
        username=payload.username,
        color_hex=color_for_user(payload.user_id),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


def _strip_tma_prefix(authorization: str) -> str:
    if authorization.lower().startswith("tma "):
        return authorization[4:].strip()
    return authorization.strip()


async def current_user(
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing_authorization")

    init_data = _strip_tma_prefix(authorization)
    try:
        payload = parse_and_verify(
            init_data,
            settings.bot_token,
            max_age_seconds=settings.initdata_max_age_seconds,
        )
    except InitDataError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=f"initdata_invalid:{exc}") from exc

    user = await session.scalar(select(User).where(User.telegram_id == payload.user_id))
    if user is None:
        # Mini App открыт всем: `initData` уже проверен подписью бота, значит
        # человек реально пришёл из Telegram. Раньше здесь стоял 403
        # `not_in_whitelist`, и приложением могли пользоваться только шесть
        # участников — теперь знакомиться может любой, а админские права
        # выдаются отдельно (`services.hr_access.default_role_for`).
        user = await _create_user(session, payload)

    # Битое имя лечим по подписанным данным Telegram: U+FFFD восстановить
    # нельзя, а свежие `first_name`/`last_name` приходят в каждом initData.
    # Чистое имя не трогаем — его человек мог поправить сам.
    if display_names.is_corrupted(user.display_name):
        healed = display_names.compose_display_name(
            payload.first_name,
            payload.last_name,
            payload.username,
            fallback_id=payload.user_id,
        )
        if not display_names.is_corrupted(healed):
            user.display_name = healed
            await session.commit()
            await session.refresh(user)

    # Lazy-update username if Telegram changed it.
    if payload.username and payload.username != user.username:
        user.username = payload.username
        await session.commit()
        await session.refresh(user)

    return user


CurrentUser = Annotated[User, Depends(current_user)]


# ---------------------------------------------------------------------------
# HR-ядро SemiTaskBot: профиль сотрудника и серверные проверки прав.
#
# Права НИКОГДА не выводятся из того, что прислал клиент: роль берётся из БД
# (`employees.role`, с учётом супер-админа из env). Отсюда `require_aup` /
# `require_admin` — единая точка входа для всех управляющих ручек (п.11
# mainPROMT: «все права должны проверяться на стороне системы»).
# ---------------------------------------------------------------------------


async def current_employee(
    session: SessionDep,
    user: CurrentUser,
    x_simulation_session: Annotated[str | None, Header()] = None,
) -> AsyncIterator[Employee]:
    """HR-профиль текущего пользователя.

    Без заголовка — настоящий профиль (создаётся лениво). С заголовком
    `X-Simulation-Session` — теневой профиль сеанса проверки: все чтения и
    записи идут от его имени, а настоящий сотрудник остаётся нетронутым.
    """
    from app.services import hr_access, hr_simulation

    if x_simulation_session:
        try:
            session_id = int(x_simulation_session)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="simulation_bad_header"
            ) from exc
        try:
            context = await hr_simulation.resolve(
                session, user=user, session_id=session_id
            )
        except hr_access.HrAccessError as exc:
            code = str(exc)
            status_code = (
                status.HTTP_409_CONFLICT
                if code == "simulation_inactive"
                else status.HTTP_403_FORBIDDEN
            )
            raise HTTPException(status_code, detail=code) from exc
        token = hr_simulation.activate(context)
        try:
            yield context.shadow
        finally:
            hr_simulation.deactivate(token)
        return

    yield await hr_access.ensure_employee(session, user)


EmployeeDep = Annotated[Employee, Depends(current_employee)]


async def require_aup(employee: EmployeeDep) -> Employee:
    """Руководитель или администратор (создание поручений, отчёты)."""
    from app.services import hr_access

    if not hr_access.is_aup(employee):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="aup_required")
    return employee


async def require_admin(employee: EmployeeDep, user: CurrentUser) -> Employee:
    """Админка: роль `admin` или прописанный доступ (шестёрка/владельцы).

    Второе условие нужно для честного «примерить роль сотрудника»: управляющий
    снимает себе `admin`, видит задачи как все, но кабинет и переключатель ролей
    остаются под рукой — иначе вернуть себе права было бы нечем.
    """
    from app.services import hr_access

    if not hr_access.is_admin(employee) and not hr_access.is_staff(employee, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin_required")
    return employee


AupDep = Annotated[Employee, Depends(require_aup)]
AdminDep = Annotated[Employee, Depends(require_admin)]
