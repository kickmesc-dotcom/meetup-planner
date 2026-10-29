"""Старт приложения одним запросом (план: быстрый десктоп).

Зачем это нужно. Открытие мини-аппа в браузере стоило ШЕСТИ запросов на чужой
домен: `/me`, `/users`, `/me/employee`, `/tasks`, `/org-setup`, `/me/ui-prefs`.
Каждый несёт `Authorization`, то есть «непростой» по CORS, — а значит перед
каждым браузер отдельно спрашивает разрешение (OPTIONS) и только потом делает
сам GET. Два круга до сервера на адрес, шесть адресов на один экран загрузки.
На контейнере в 0,5 ГБ и с холодным стартом это и было «медленно, но
непонятно почему» (замеры — `docs/DESKTOP_PERF.md`).

Что здесь есть и чего нет. Каждый кусок ответа — ровно тело своей ручки,
собранное ТЕМИ ЖЕ функциями (они вынесены в `routes_users` и `routes_hr`).
Никакой второй правды: если у `/me` изменится формат, изменится и здесь.
Побочные действия старта сохранены: отметка «последний заход» и `touch_seen`
для карточки коллеги — иначе пропали бы из приложения ровно те данные, ради
которых эти ручки писали в базу.

Чего здесь СОЗНАТЕЛЬНО нет:

* терпимости к отсутствию HR-профиля. Ручка зависит от `EmployeeDep`, как и
  `/me/employee`: та же проверка прав, тот же тенантский контекст, тот же
  режим проверки (`X-Simulation-Session`). Написать «свой» резолв значило бы
  завести вторую копию правил доступа — и однажды разойтись с ними. Если
  человек в состоянии «сессии есть, членства нет», ручка честно ответит 403,
  а фронт молча сделает шесть обычных запросов: bootstrap — оптимизация, а не
  источник истины.
* кеша. Ответ зависит от человека и от смены; `Cache-Control` ставит общий
  слой API, а не эта ручка.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser, EmployeeDep, SessionDep
from app.api.routes_hr import (
    EmployeeOut,
    OrgSetupOut,
    TaskOut,
    _employee_out,
    _may_edit_setup,
    _may_manage_packs,
    _org_setup_out,
    _task_views,
)
from app.api.routes_users import UiPrefsOut, UserOut, me_out, ui_prefs_out, users_out
from app.services import hr_profile, hr_tasks, org_setup

router = APIRouter(tags=["bootstrap"])


class BootstrapOut(BaseModel):
    """Всё, что нужно для первого экрана.

    `employee`/`tasks`/`org_setup`/`ui_prefs` помечены опциональными не ради
    терпимости к ошибкам (её нет — ручка падает целиком), а ради честности
    формы: HR-профиль может быть ещё не заведён, и тогда в ответе `null`, а не
    выдуманный объект.
    """

    me: UserOut
    users: list[UserOut]
    employee: EmployeeOut | None = None
    tasks: list[TaskOut] | None = None
    org_setup: OrgSetupOut | None = None
    ui_prefs: UiPrefsOut | None = None


@router.get("/bootstrap", response_model=BootstrapOut)
async def bootstrap(
    session: SessionDep, user: CurrentUser, employee: EmployeeDep
) -> BootstrapOut:
    """Шесть ответов старта одним запросом (см. модульный комментарий).

    Поручения собираем только когда знакомство пройдено — ровно как на фронте:
    до этого вкладки «Задачи» нет, и запрос был бы пустой тратой.
    """
    # Побочное действие `/me/employee`: карточка коллеги показывает «был N
    # минут назад». Без него открытие приложения перестало бы обновлять
    # отметку — то есть bootstrap тихо убрал бы функцию.
    await hr_profile.touch_seen(session, employee)

    setup = await org_setup.load(session)
    tasks: list[TaskOut] | None = None
    if employee.onboarding_state == "done":
        rows = await hr_tasks.list_for_employee(session, employee, include_closed=False)
        tasks = await _task_views(session, rows, employee)

    return BootstrapOut(
        me=await me_out(session, user),
        users=await users_out(session),
        employee=await _employee_out(session, employee, user),
        tasks=tasks,
        org_setup=_org_setup_out(
            setup,
            can_edit=_may_edit_setup(employee, user),
            can_manage_packs=await _may_manage_packs(session, employee, user),
        ),
        ui_prefs=await ui_prefs_out(session, user),
    )
