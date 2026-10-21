"""Снапшоты состава: страховка для пула Telegram-ID.

Зачем. Список заведённых людей — самое дорогое, что есть в базе: Telegram-ID
нельзя «перевыпустить», их приходится заново собирать у сотрудников. При этом
часть админских действий удаляет людей безвозвратно (`fire` с режимом
`purge`, `demo/purge` с `delete_employees`). Поэтому перед таким действием
сервис снимает снимок состава, а из админки его можно вернуть одной кнопкой.

Что именно храним. Только то, что нужно, чтобы человек снова смог войти и
работать: `telegram_id`, имя, отдел, должность, плашку, роль. Внутренние `id`
не сохраняем — после удаления они переиспользуются, и восстановление по ним
приклеило бы профиль к чужой строке. Восстановление идёт по `telegram_id`.

Что НЕ делаем. Снимок не перезаписывает живые профили: активный сотрудник
пропускается, а не «перезаливается» из снимка. Иначе кнопка «восстановить»
молча откатила бы человеку отдел и имя, которые правили уже после снимка.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    ONBOARDING_NEW,
    ONBOARDING_STATES,
    ROLE_EMPLOYEE,
    ROLES,
    Department,
    Employee,
    RosterSnapshot,
)
from app.db.models import User
from app.db.seed import color_for_user
from app.services.hr_demo import DEMO_TG_BASE

log = structlog.get_logger()

# Сколько снимков держим. Пул небольшой (десятки людей), поэтому 20 снимков —
# это сотни килобайт JSONB и при этом реальная история: «до увольнения», «до
# демо-пула», «перед большой чисткой».
MAX_SNAPSHOTS = 20

KIND_MANUAL = "manual"
KIND_AUTO = "auto"

SOURCE_MANUAL = "employees"
MAX_LABEL = 120
MAX_NAME = 96


class RosterError(Exception):
    """Ошибка работы со снимками (текст — код для клиента)."""


@dataclass(frozen=True)
class SnapshotSummary:
    id: int
    label: str
    kind: str
    source: str
    people_count: int
    created_at: datetime


@dataclass(frozen=True)
class SnapshotDetail:
    summary: SnapshotSummary
    people: list[dict[str, object]]


@dataclass(frozen=True)
class RestoreResult:
    """Итог восстановления: что появилось, что вернули и что не тронули."""

    created: int
    restored: int
    skipped: int
    departments_missing: list[str]


# --------------------------------------------------------------------------
# Чистые правила (проверяются тестами без базы)
# --------------------------------------------------------------------------


def normalize_telegram_id(value: str | int) -> int:
    """Telegram-ID из поля ввода: цифры, возможно с пробелами или `@`.

    Отрицательные и нулевые не годятся (это не аккаунт), а синтетический
    диапазон тестового пула занят `hr_demo` — вручную туда писать нельзя,
    иначе настоящий человек получит ID бота.
    """
    if isinstance(value, bool):  # bool — подкласс int, но это не ID
        raise RosterError("bad_telegram_id")
    if isinstance(value, str):
        clean = value.strip().lstrip("@").replace(" ", "").replace("\u00a0", "")
        if not clean:
            raise RosterError("bad_telegram_id")
        if not clean.isdigit():
            raise RosterError("bad_telegram_id")
        number = int(clean)
    else:
        number = int(value)
    if number <= 0:
        raise RosterError("bad_telegram_id")
    if number >= DEMO_TG_BASE:
        raise RosterError("demo_id_reserved")
    return number


def default_display_name(telegram_id: int) -> str:
    """Имя, пока человек не назвался: по нему видно, кого именно завели."""
    return f"ID {telegram_id}"


def clean_label(label: str | None) -> str:
    return (label or "").strip()[:MAX_LABEL]


def clean_name(name: str | None, telegram_id: int) -> str:
    clean = (name or "").strip()
    if not clean:
        return default_display_name(telegram_id)
    return clean[:MAX_NAME]


def safe_role(role: object) -> str:
    """Роль из снимка: неизвестное значение не должно ломать восстановление."""
    if isinstance(role, str) and role in ROLES:
        return role
    return ROLE_EMPLOYEE


def safe_onboarding(value: object) -> str:
    if isinstance(value, str) and value in ONBOARDING_STATES:
        return value
    return ONBOARDING_NEW


def parse_hire_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def person_entry(
    *,
    telegram_id: int,
    display_name: str,
    username: str | None,
    position: str | None,
    badge: str | None,
    badge_emoji: str | None,
    department_slug: str | None,
    department_name: str | None,
    role: str,
    onboarding_state: str,
    is_demo: bool,
    is_active: bool,
    hire_date: date | None = None,
    learning_mode: bool = False,
) -> dict[str, object]:
    """Одна запись снимка — явный список полей, без `dict(model.__dict__)`.

    Явный список важен: снимок переживает миграции, и случайно попавшее в него
    поле-объект сломало бы JSONB молча и необратимо.
    """
    return {
        "telegram_id": int(telegram_id),
        "display_name": display_name,
        "username": username,
        "position": position,
        "badge": badge,
        "badge_emoji": badge_emoji,
        "department_slug": department_slug,
        "department_name": department_name,
        "role": safe_role(role),
        "onboarding_state": safe_onboarding(onboarding_state),
        "is_demo": bool(is_demo),
        "is_active": bool(is_active),
        "hire_date": hire_date.isoformat() if hire_date else None,
        "learning_mode": bool(learning_mode),
    }


def summary_of(row: RosterSnapshot) -> SnapshotSummary:
    """Сводка по строке — общая для списка и ручки создания снимка."""
    return _summary(row)


def _summary(row: RosterSnapshot) -> SnapshotSummary:
    return SnapshotSummary(
        id=int(row.id),
        label=str(row.label),
        kind=str(row.kind),
        source=str(row.source),
        people_count=int(row.people_count),
        created_at=row.created_at,
    )


# --------------------------------------------------------------------------
# Чтение и создание
# --------------------------------------------------------------------------


async def list_snapshots(
    session: AsyncSession, *, limit: int = MAX_SNAPSHOTS
) -> list[SnapshotSummary]:
    rows = await session.scalars(
        select(RosterSnapshot)
        .order_by(RosterSnapshot.created_at.desc(), RosterSnapshot.id.desc())
        .limit(max(1, min(limit, MAX_SNAPSHOTS)))
    )
    return [_summary(row) for row in rows.all()]


async def detail(session: AsyncSession, snapshot_id: int) -> SnapshotDetail:
    row = await session.get(RosterSnapshot, snapshot_id)
    if row is None:
        raise RosterError("snapshot_not_found")
    people = [person for person in (row.payload or []) if isinstance(person, dict)]
    return SnapshotDetail(summary=_summary(row), people=people)


async def capture(
    session: AsyncSession,
    *,
    created_by_employee_id: int | None = None,
    label: str | None = None,
    kind: str = KIND_MANUAL,
    source: str = SOURCE_MANUAL,
) -> RosterSnapshot:
    """Снять состав целиком: все люди, кроме теневых профилей проверки."""
    rows = (
        await session.execute(
            select(Employee, User, Department)
            .join(User, User.id == Employee.user_id)
            .outerjoin(Department, Department.id == Employee.department_id)
            .where(Employee.is_simulation.is_(False))
            .order_by(Employee.id)
        )
    ).all()

    people = [
        person_entry(
            telegram_id=int(user.telegram_id),
            display_name=str(user.display_name),
            username=user.username,
            position=employee.position,
            badge=employee.badge,
            badge_emoji=employee.badge_emoji,
            department_slug=department.slug if department else None,
            department_name=department.name if department else None,
            role=str(employee.role),
            onboarding_state=str(employee.onboarding_state),
            is_demo=bool(employee.is_demo),
            is_active=bool(employee.is_active),
            hire_date=employee.hire_date,
            learning_mode=bool(employee.learning_mode),
        )
        for employee, user, department in rows
    ]

    row = RosterSnapshot(
        label=clean_label(label),
        kind=kind if kind in (KIND_MANUAL, KIND_AUTO) else KIND_MANUAL,
        source=(source or "")[:48],
        people_count=len(people),
        payload=people,
        created_by_employee_id=created_by_employee_id,
    )
    session.add(row)
    await session.flush()
    await _prune(session)
    await session.commit()
    await session.refresh(row)
    log.info("hr.roster.snapshot", snapshot_id=int(row.id), people=len(people), source=source)
    return row


async def remove(session: AsyncSession, snapshot_id: int) -> bool:
    row = await session.get(RosterSnapshot, snapshot_id)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def _prune(session: AsyncSession) -> None:
    """Оставить только свежие `MAX_SNAPSHOTS` снимков."""
    keep = list(
        (
            await session.scalars(
                select(RosterSnapshot.id)
                .order_by(
                    RosterSnapshot.created_at.desc(), RosterSnapshot.id.desc()
                )
                .limit(MAX_SNAPSHOTS)
            )
        ).all()
    )
    if not keep:
        return
    await session.execute(
        delete(RosterSnapshot).where(RosterSnapshot.id.not_in(keep))
    )


# --------------------------------------------------------------------------
# Восстановление
# --------------------------------------------------------------------------


async def _department_index(
    session: AsyncSession,
) -> tuple[dict[str, int], dict[str, int]]:
    """Два словаря: по slug и по имени (имя — запасной путь для старых снимков)."""
    rows = (await session.scalars(select(Department))).all()
    by_slug: dict[str, int] = {}
    by_name: dict[str, int] = {}
    for row in rows:
        by_slug[str(row.slug)] = int(row.id)
        by_name[str(row.name).strip().lower()] = int(row.id)
    return by_slug, by_name


async def restore(session: AsyncSession, snapshot_id: int) -> RestoreResult:
    """Вернуть людей из снимка по `telegram_id`.

    Три исхода на человека, и они принципиально разные:

    * `created` — строки не было вовсе (или был `User` без HR-профиля): заводим;
    * `restored` — профиль был уволен: открываем доступ обратно;
    * `skipped` — человек активен: не трогаем (снимок не откатывает правки).

    Отдел ищем сначала по `slug`, потом по имени: slug меняли руками, а старые
    снимки должны остаться рабочими.
    """
    row = await session.get(RosterSnapshot, snapshot_id)
    if row is None:
        raise RosterError("snapshot_not_found")

    by_slug, by_name = await _department_index(session)
    missing: set[str] = set()
    created = 0
    restored = 0
    skipped = 0

    for person in row.payload or []:
        if not isinstance(person, dict):
            skipped += 1
            continue
        try:
            telegram_id = normalize_telegram_id(person.get("telegram_id", 0))
        except RosterError:
            # Синтетические ID демо-пула тоже сюда попадают: их заводит
            # `hr_demo.seed_pool`, вручную восстанавливать нечего.
            skipped += 1
            continue

        slug = person.get("department_slug")
        name = person.get("department_name")
        department_id = by_slug.get(str(slug)) if slug else None
        if department_id is None and isinstance(name, str) and name:
            department_id = by_name.get(name.strip().lower())
            if department_id is None:
                missing.add(name)

        role = safe_role(person.get("role"))
        onboarding = safe_onboarding(person.get("onboarding_state"))
        position = person.get("position") if isinstance(person.get("position"), str) else None
        badge = person.get("badge") if isinstance(person.get("badge"), str) else None
        badge_emoji = (
            person.get("badge_emoji")
            if isinstance(person.get("badge_emoji"), str)
            else None
        )
        is_demo = bool(person.get("is_demo"))
        hire_date = parse_hire_date(person.get("hire_date"))
        learning_mode = bool(person.get("learning_mode"))

        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            display_name = person.get("display_name")
            user = User(
                telegram_id=telegram_id,
                display_name=(
                    display_name
                    if isinstance(display_name, str) and display_name.strip()
                    else default_display_name(telegram_id)
                ),
                username=(
                    person.get("username")
                    if isinstance(person.get("username"), str)
                    else None
                ),
                color_hex=color_for_user(telegram_id),
            )
            session.add(user)
            await session.flush()

        employee = await session.scalar(
            select(Employee).where(
                Employee.user_id == user.id, Employee.is_simulation.is_(False)
            )
        )
        if employee is None:
            session.add(
                Employee(
                    user_id=int(user.id),
                    department_id=department_id,
                    position=position,
                    badge=badge,
                    badge_emoji=badge_emoji,
                    role=role,
                    # Снимок хранит настоящую роль: восстановление не должно
                    # зависеть от текущего env-списка админов.
                    role_locked=True,
                    onboarding_state=onboarding,
                    is_demo=is_demo,
                    is_active=True,
                    hire_date=hire_date,
                    learning_mode=learning_mode,
                )
            )
            created += 1
            continue

        if employee.fired_at is not None:
            employee.fired_at = None
            employee.purge_after = None
            employee.fired_mode = None
            employee.is_active = True
            restored += 1
        else:
            skipped += 1

    await session.commit()
    result = RestoreResult(
        created=created,
        restored=restored,
        skipped=skipped,
        departments_missing=sorted(missing),
    )
    log.info(
        "hr.roster.restored",
        snapshot_id=snapshot_id,
        created=created,
        restored=restored,
        skipped=skipped,
    )
    return result


def now_utc() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "KIND_AUTO",
    "KIND_MANUAL",
    "MAX_SNAPSHOTS",
    "RosterError",
    "SnapshotDetail",
    "SnapshotSummary",
    "RestoreResult",
    "capture",
    "clean_label",
    "clean_name",
    "default_display_name",
    "detail",
    "list_snapshots",
    "normalize_telegram_id",
    "person_entry",
    "summary_of",
    "remove",
    "restore",
]
