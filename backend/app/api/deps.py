from __future__ import annotations

from collections.abc import AsyncIterator
from contextvars import ContextVar
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
from app.db.org_models import Organization, set_org
from app.services import display_names, org_bots, orgs


async def db_session() -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker()
    async with sm() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(db_session)]

# Каким способом человек вошёл в ЭТОМ запросе. Нужно ровно для одного
# различия: почтовый вход без членства не имеет права завести сотрудника в
# первой организации, а телеграм-вход (и ссылка доступа) — имеет, потому что
# человек пришёл из конкретного бота/по приглашению администратора.
session_auth: ContextVar[bool] = ContextVar("session_auth", default=False)
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
    x_access_token: Annotated[str | None, Header()] = None,
) -> User:
    """Кто пришёл: `initData` из Telegram или ссылка доступа из браузера.

    Порядок важен. `Authorization: tma …` — это мини-апп, и он всегда главнее:
    если человек открыл приложение внутри Telegram, локальный токен браузера
    (мог остаться от прошлого входа) не должен подменять личность.

    `X-Access-Token` — только вторая ветка, для прямой ссылки на Pages, где
    `initData` нет вовсе. Токен проверяется по SHA-256 в базе, со сроком и
    отзывом (`services.app_access`).
    """
    if not authorization:
        if x_access_token:
            from app.services import app_access

            user = await app_access.resolve(session, x_access_token)
            if user is None:
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED, detail="access_token_invalid"
                )
            # Ссылка не говорит, чья это организация, — берём её из членства
            # человека. Без этого онбординг создал бы сотрудника в первой
            # (B2B_PLATFORM_PLAN, шаги 1.2 и 2.1).
            org = await orgs.default_org_for(session, user)
            if org is not None:
                set_org(org.id)
            return user
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing_authorization")

    # Вход по почте: `Authorization: Bearer <токен сессии>` (шаг 2.1).
    scheme, _, bearer = authorization.partition(" ")
    if scheme.lower() == "bearer":
        from app.services import accounts

        resolved = await accounts.resolve_session(session, bearer.strip())
        if resolved is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="session_invalid")
        user, org_id = resolved
        session_auth.set(True)
        if org_id is not None:
            set_org(org_id)
        return user

    init_data = _strip_tma_prefix(authorization)
    # Мини-апп мог быть открыт через бота ЛЮБОЙ организации: подпись `initData`
    # считается от токена конкретного бота (B2B_PLATFORM_PLAN, шаг 1.6).
    # Пробуем все известные токены и запоминаем, чей подошёл — это и есть
    # организация запроса; иначе новый сотрудник второго клиента завёлся бы
    # в первой.
    await org_bots.ensure_loaded(session)
    payload: InitDataPayload | None = None
    matched_org: int | None = None
    last_error: InitDataError | None = None
    for token in org_bots.token_candidates():
        try:
            payload = parse_and_verify(
                init_data,
                token,
                max_age_seconds=settings.initdata_max_age_seconds,
            )
        except InitDataError as exc:
            last_error = exc
            continue
        matched_org = org_bots.org_for_token(token)
        break
    if payload is None:
        detail = f"initdata_invalid:{last_error or 'no_token'}"
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail)
    if matched_org is not None:
        set_org(matched_org)

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

    if matched_org is not None:
        # Человек пришёл через бота этой организации — значит он её сотрудник.
        # Роль существующего членства не трогаем: иначе вход понижал бы
        # управляющего до staff (см. `orgs.ensure_member`).
        await orgs.ensure_member(session, org_id=matched_org, user_id=user.id)

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
        set_org(context.shadow.org_id)
        try:
            yield context.shadow
        finally:
            hr_simulation.deactivate(token)
        return

    # Почтовый вход без членства: приглашение ещё не принято (шаг 2.2).
    # Без этой проверки онбординг молча завёл бы человеку сотрудника в
    # ПЕРВОЙ организации — то есть в чужом клиенте. Телеграм-вход сюда не
    # попадает: он уже проставил членство по боту, через который пришли.
    if session_auth.get() and not await orgs.orgs_of(session, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="org_required")

    try:
        employee = await hr_access.ensure_employee(session, user)
        # Тенантский фильтр: все дальнейшие ORM-запросы в этом запросе видят
        # только его организацию (см. `app/db/tenancy.py`).
        set_org(employee.org_id)
        yield employee
    except hr_access.HrAccessError as exc:
        # Уволенный сотрудник: доступ закрыт, пока его не вернут из корзины.
        # Отдаём 403 с кодом, чтобы приложение показало человеческий текст.
        if str(exc) == "employee_fired":
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        raise


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


async def current_org(session: SessionDep, employee: EmployeeDep) -> Organization:
    """Организация текущего сотрудника (B2B_PLATFORM_PLAN, шаг 1.2).

    Источник — `employees.org_id`, а не заголовок запроса: клиент не должен
    выбирать тенант сам, иначе достаточно прислать чужой номер. Неактивная
    организация закрывает доступ сразу, а не после истечения сессии: клиента
    могли заблокировать за неоплату.
    """
    org = await session.get(Organization, employee.org_id)
    if org is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="org_missing")
    if not org.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="org_inactive")
    return org


OrgDep = Annotated[Organization, Depends(current_org)]
