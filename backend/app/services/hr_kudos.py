"""«Спасибо коллеге»: кому можно сказать, сколько и что видно за неделю.

Механика намеренно маленькая и без новых сущностей: одна благодарность — одна
строка `hr_kudos`, из той же строки собирается лента и считается недельный топ.
Поэтому «топ за неделю» не может разойтись с тем, что человек видит в ленте.

Правила и почему именно такие:

* **Коллеге по подразделению.** Спасибо — про совместную работу, а не про
  пальцы вверх случайному человеку. Управляющий и администратор могут сказать
  спасибо любому действующему сотруднику: они и так видят всех.
* **Не себе.** Проверяет и сервис, и `check` в схеме: правило не должно зависеть
  от того, поправили ли код.
* **Одно спасибо одному человеку в день и не больше `MAX_PER_DAY` всего.**
  Иначе топ набивается нажатиями за минуту и перестаёт что-либо значить. День
  считается по часам заведения: смена кончается после полуночи, и благодарность
  за смену не должна уезжать во вчера.
* **Не действующему — нельзя.** Поблагодарить уволенного нельзя: строка осталась
  бы в топе под именем, которого больше нет в составе.

Тексты уведомлений живут в `services/hr_notify`, доставку делает бот. Здесь —
только данные и правила.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import Employee, Kudos
from app.db.models import User
from app.services import hr_checklists, hr_demo, hr_feed

# Сколько благодарностей один человек может отдать за день. Число из практики:
# в смене 5–8 человек, а «спасибо» должно остаться выбором, а не ритуалом.
MAX_PER_DAY = 5
# Длина записи: одна фраза, а не письмо. Лента читается на бегу.
MAX_MESSAGE = 160
# Сколько мест показываем в карточке недельного топа.
TOP_LIMIT = 3

# Коды ошибок. Их возвращает API, а интерфейс переводит: сервер не знает языка
# клиента, но обязан сказать, ЧТО именно не так.
ERR_SELF = "self"
ERR_OUT_OF_SCOPE = "out_of_scope"
ERR_ALREADY_TODAY = "already_today"
ERR_DAILY_LIMIT = "daily_limit"
ERR_MESSAGE_TOO_LONG = "message_too_long"


class KudosError(Exception):
    """Отказ по правилам благодарности. `code` уходит в API как есть."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TopRow:
    employee_id: int
    display_name: str
    department_id: int | None
    count: int


@dataclass(frozen=True)
class Weekly:
    """Неделя благодарностей глазами одного человека."""

    since: date
    until: date
    top: list[TopRow] = field(default_factory=list)
    received: int = 0
    given: int = 0
    my_place: int | None = None
    # Сколько ещё можно сказать сегодня: в интерфейсе это честнее, чем «лимит
    # исчерпан» без числа.
    today_left: int = MAX_PER_DAY


async def thankable_ids(session: AsyncSession, sender: Employee) -> set[int]:
    """Кому `sender` вправе сказать спасибо.

    Возвращает готовое множество: и правило области, и «человек ещё работает»
    считаются здесь, а не в вызывающем коде — иначе проверка расползётся по
    ручкам и однажды разойдётся.
    """
    scope = hr_feed.viewer_scope(sender)
    stmt = select(Employee.id).where(
        Employee.is_active.is_(True),
        Employee.is_simulation.is_(False),
    )
    if scope != hr_feed.SCOPE_ALL:
        # Коллега по подразделению. Сотрудник без подразделения никого не видит
        # (кроме админов выше) — и это честно: список людей он не получает.
        if sender.department_id is None:
            return set()
        stmt = stmt.where(Employee.department_id == sender.department_id)

    ids = {int(i) for i in (await session.scalars(stmt)).all()}
    ids.discard(sender.id)
    hidden = await hr_demo.hidden_employee_ids(session)
    if not sender.is_simulation:
        from app.services import hr_simulation

        hidden = hidden | await hr_simulation.hidden_employee_ids(session)
    return ids - hidden


async def _count(session: AsyncSession, *where) -> int:  # noqa: ANN002 - условия
    value = await session.scalar(select(func.count()).select_from(Kudos).where(*where))
    return int(value or 0)


async def give(
    session: AsyncSession,
    *,
    sender: Employee,
    to_employee_id: int,
    message: str | None = None,
    today: date | None = None,
) -> Kudos:
    """Сказать спасибо. Коммитит вызывающий (вместе с уведомлением).

    Порядок проверок — от самого дешёвого к самому дорогому, а последняя
    защита лежит в схеме: `unique(from, to, day)` ловит два одновременных
    запроса, которые оба прошли проверку «сегодня ещё не говорил».
    """
    text = (message or "").strip()
    if len(text) > MAX_MESSAGE:
        raise KudosError(ERR_MESSAGE_TOO_LONG)
    if to_employee_id == sender.id:
        raise KudosError(ERR_SELF)

    day = today or hr_checklists.local_today()
    if to_employee_id not in await thankable_ids(session, sender):
        raise KudosError(ERR_OUT_OF_SCOPE)

    already = await session.scalar(
        select(Kudos.id).where(
            Kudos.from_employee_id == sender.id,
            Kudos.to_employee_id == to_employee_id,
            Kudos.day == day,
        )
    )
    if already is not None:
        raise KudosError(ERR_ALREADY_TODAY)

    given_today = await _count(
        session,
        Kudos.from_employee_id == sender.id,
        Kudos.day == day,
    )
    if given_today >= MAX_PER_DAY:
        raise KudosError(ERR_DAILY_LIMIT)

    row = Kudos(
        from_employee_id=sender.id,
        to_employee_id=to_employee_id,
        day=day,
        message=text or None,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:  # гонка двух нажатий — побеждает первое
        raise KudosError(ERR_ALREADY_TODAY) from exc
    return row


async def _top_rows(
    session: AsyncSession,
    *,
    allowed: set[int] | None,
    since: date,
    until: date,
) -> list[TopRow]:
    """Кто сколько благодарностей получил за неделю — по убыванию."""
    if allowed is not None and not allowed:
        return []
    stmt = (
        select(
            Kudos.to_employee_id,
            func.count().label("cnt"),
            User.display_name,
            Employee.department_id,
            Employee.is_simulation,
        )
        .join(Employee, Employee.id == Kudos.to_employee_id)
        .join(User, User.id == Employee.user_id)
        .where(Kudos.day >= since, Kudos.day <= until)
        .group_by(
            Kudos.to_employee_id,
            User.display_name,
            Employee.department_id,
            Employee.is_simulation,
        )
        # Второй ключ — `employee_id`: при равных счётах порядок не «прыгает»
        # между запросами, иначе место в топе менялось бы само по себе.
        .order_by(func.count().desc(), Kudos.to_employee_id)
    )
    if allowed is not None:
        stmt = stmt.where(Kudos.to_employee_id.in_(allowed))
    rows = (await session.execute(stmt)).all()

    # Тестовый пул в топ не попадает: «спасибо» боту-симулятору обесценивает
    # сам топ. Скрытых админом людей прячем тем же правилом, что и в ленте.
    hidden = await hr_demo.hidden_employee_ids(session)
    out: list[TopRow] = []
    for employee_id, cnt, name, department_id, is_simulation in rows:
        if is_simulation or int(employee_id) in hidden:
            continue
        out.append(
            TopRow(
                employee_id=int(employee_id),
                display_name=str(name),
                department_id=department_id,
                count=int(cnt),
            )
        )
    return out


async def weekly(
    session: AsyncSession,
    viewer: Employee,
    *,
    today: date | None = None,
    limit: int = TOP_LIMIT,
) -> Weekly:
    """Недельный топ и личные числа смотрящего.

    Область та же, что у ленты (`hr_feed.allowed_employee_ids`): сотрудник
    видит только себя, руководитель — своё подразделение, управляющий — всех.
    Топ не должен становиться способом узнать чужие имена в обход видимости.
    """
    from app.services import hr_simulation

    day = today or hr_checklists.local_today()
    since, until = hr_kpi_week_bounds(day)

    allowed = await hr_feed.allowed_employee_ids(session, viewer)
    excluded = await hr_demo.hidden_employee_ids(session)
    if not viewer.is_simulation:
        excluded = excluded | await hr_simulation.hidden_employee_ids(session)
    if allowed is not None:
        allowed = allowed - excluded

    rows = await _top_rows(session, allowed=allowed, since=since, until=until)
    my_place = next(
        (i + 1 for i, row in enumerate(rows) if row.employee_id == viewer.id), None
    )

    received = await _count(
        session,
        Kudos.to_employee_id == viewer.id,
        Kudos.day >= since,
        Kudos.day <= until,
    )
    given = await _count(
        session,
        Kudos.from_employee_id == viewer.id,
        Kudos.day >= since,
        Kudos.day <= until,
    )
    given_today = await _count(
        session,
        Kudos.from_employee_id == viewer.id,
        Kudos.day == day,
    )

    return Weekly(
        since=since,
        until=until,
        top=rows[: max(1, limit)],
        received=received,
        given=given,
        my_place=my_place,
        today_left=max(0, MAX_PER_DAY - given_today),
    )


def hr_kpi_week_bounds(day: date) -> tuple[date, date]:
    """Пн–вс той же недели, что и недельный рейтинг опыта.

    Импорт локальный: `hr_kpi` тянет за собой настройки начисления опыта, а
    благодарности от них не зависят — нужна только граница недели, чтобы
    «топ за неделю» и «место в неделе» в профиле говорили об одном периоде.
    """
    from app.services.hr_kpi import week_bounds

    return week_bounds(day)
