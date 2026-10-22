"""Тенантский фильтр на уровне сессии (B2B_PLATFORM_PLAN, шаг 1.3).

Проблема, которую решает модуль. Колонка `org_id` сама по себе ничего не
защищает: запрос без `where org_id = …` вернёт строки всех клиентов. В проекте
больше сотни таких запросов — в сервисах, роутерах, боте, планировщике. Ходить
по ним руками и надеяться, что ничего не забыто, — это и есть «полу-мульти-
тенантность», которую план называет хуже её отсутствия.

Поэтому фильтр добавляется один раз, в момент выполнения ORM-запроса:

* каждому SELECT по моделям с `OrgScoped` добавляется `WHERE org_id = :текущая`;
* вложенные загрузки (`selectinload`, `joinedload`) фильтруются так же, иначе
  связь вернула бы чужие строки через id из своей организации.

Что НЕ покрывается автоматически (и это важно знать):

* сырой SQL (`text(...)`) и запросы по `Table` — таких в проекте единицы, их
  нужно смотреть глазами;
* Core-вставки без ORM-объекта: там сработает серверный дефолт (первая
  организация). Пока контур один — это ровно прежнее поведение.

Как включается. `deps.current_employee` после резолва сотрудника вызывает
`set_org(employee.org_id)`; middleware в `app.main` возвращает контекст после
ответа. Бот, планировщик и фоновые задачи живут со значением по умолчанию —
первой организацией, то есть ведут себя точно как до тенантов. Платформенные
задачи, которым нужен обход всех организаций, используют `all_orgs()`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.db.org_models import ALL_ORGS, OrgScoped, current_org_id

_CRITERIA_KEY = "tenant_scope"


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_scope(execute_state) -> None:  # noqa: ANN001 - тип SQLAlchemy
    """Добавить `WHERE org_id = …` ко всем ORM-выборкам.

    Слушатель висит на синхронном `Session`: `AsyncSession` выполняет запросы
    через него, поэтому отдельная регистрация для async не нужна.
    """
    if not execute_state.is_select:
        return
    # Догрузка отдельной колонки (`load_only`/`deferred`) — это тот же объект,
    # критерий на классе там не нужен и SQLAlchemy на нём ругается.
    if execute_state.is_column_load:
        return

    org_id = current_org_id.get()
    if org_id == ALL_ORGS:
        return

    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            OrgScoped,
            lambda cls: cls.org_id == org_id,
            include_aliases=True,
        )
    )


@contextmanager
def all_orgs() -> Iterator[None]:
    """Временно снять фильтр: обход организаций платформенной задачей.

    Нужен, например, планировщику, который должен пройти по всем клиентам.
    Обычный код обязан обходиться без него: каждое использование — это место,
    где данные всех организаций лежат в одной выборке.
    """
    token = current_org_id.set(ALL_ORGS)
    try:
        yield
    finally:
        current_org_id.reset(token)
