"""Приватность организации: выгрузка, удаление, сроки (план 5.5).

Три вещи, которые клиент вправе получить от B2B-сервиса и которых не было:

1. **Свои данные.** Выгрузка структуры и людей в JSON — без токенов
   приглашений и без чужих строк. Это не «дамп базы»: дамп содержит пароли
   (хеши), токены ботов и данные других клиентов. Экспорт собирается явно,
   поле за полем, поэтому новая колонка не утечёт в файл автоматически.

2. **Уход.** Удаление по запросу с отсрочкой `GRACE_DAYS`: запрос фиксируется
   сразу, доступ команде закрывается, данные исчезают по истечении срока.
   Отсрочка нужна не нам, а клиенту: удаление необратимо, и кнопка, которая
   стирает всё мгновенно, — это ловушка. За это время владелец отменяет
   запрос, если передумал.

3. **Сроки.** Не «мы храним разумно», а числа: журнал доступа — 180 дней,
   корзина уволенных — 30, отсрочка удаления — 30, артефакты бэкапов — 14.
   Те же числа отдаёт ручка `/api/org/privacy`, чтобы обещание в документе и
   поведение сервера нельзя было развести.

Почему удаление организации физическое, а не «флаг». Флаг удаления через год
превращается в «мы храним, но называем иначе». Срок вышел — строки удаляются
каскадом (`ON DELETE CASCADE` у тенантных таблиц); глобальные `users` остаются,
потому что человек может работать в другой организации.

Почему экспорт не включает рабочие данные (задачи, чек-листы, медиа). Это
объём в гигабайты и отдельный формат (файлы). Персональные данные — люди,
доступы и структура — выгружаются здесь; полный архив по запросу собирается
отдельно, и это честно написано в `docs/PRIVACY.md`, а не спрятано.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import Department, Employee
from app.db.models import User
from app.db.org_models import Organization, OrganizationMember
from app.services import audit, hr_admin_ops

log = structlog.get_logger()

# Отсрочка удаления: сколько клиент может передумать.
GRACE_DAYS = 30
# Сколько живут артефакты бэкапов в GitHub Actions (`.github/workflows/backup.yml`).
# Число повторено здесь, потому что оно обещано клиенту в кабинете.
BACKUP_ARTIFACT_DAYS = 14

EXPORT_FORMAT = "semitask.organization.export"
EXPORT_VERSION = 1


class PrivacyError(Exception):
    """Код ошибки для ручки. Текст живёт на фронте, а не на сервере."""


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _aware(value: datetime | None) -> datetime | None:
    """Дата из базы может прийти без зоны (sqlite): считаем её UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def retention() -> dict[str, int]:
    """Сроки хранения, которые обещаны клиенту. Один источник чисел."""
    return {
        "audit_days": audit.RETENTION_DAYS,
        "deletion_grace_days": GRACE_DAYS,
        "fired_trash_days": hr_admin_ops.TRASH_DAYS,
        "backup_artifact_days": BACKUP_ARTIFACT_DAYS,
    }


def state(org: Organization, *, now: datetime | None = None) -> dict[str, Any]:
    """Состояние удаления: запрошено ли и сколько осталось дней."""
    moment = now or datetime.now(timezone.utc)
    purge_after = _aware(org.purge_after)
    days_left: int | None = None
    if purge_after is not None:
        seconds = (purge_after - moment).total_seconds()
        # Округление вверх: «осталось 0 дней» читалось бы как «уже удалено»,
        # хотя данные ещё на месте.
        days_left = max(0, math.ceil(seconds / 86400))
    return {
        "deleted": org.deleted_at is not None,
        "deleted_at": _iso(_aware(org.deleted_at)),
        "purge_after": _iso(purge_after),
        "days_left": days_left,
    }


async def export_org(session: AsyncSession, org: Organization) -> dict[str, Any]:
    """Собрать выгрузку своей организации.

    Фильтр по `org.id` стоит явно в каждом запросе, а не полагается на
    контекстную переменную: выгрузка — ровно то место, где ошибка фильтра
    означала бы «данные чужого клиента в файле».
    """
    members = list(
        await session.scalars(
            select(OrganizationMember).where(
                OrganizationMember.org_id == org.id
            )
        )
    )
    employees = list(
        await session.scalars(
            select(Employee).where(Employee.org_id == org.id)
        )
    )
    departments = list(
        await session.scalars(
            select(Department).where(Department.org_id == org.id)
        )
    )
    user_ids = {row.user_id for row in members} | {
        row.user_id for row in employees
    }
    users = (
        {
            row.id: row
            for row in await session.scalars(
                select(User).where(User.id.in_(user_ids))
            )
        }
        if user_ids
        else {}
    )
    department_names = {row.id: row.name for row in departments}

    def person_name(user_id: int) -> str | None:
        person = users.get(user_id)
        if person is None:
            return None
        return person.display_name or person.email

    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "retention": retention(),
        "organization": {
            "id": org.id,
            "slug": org.slug,
            "name": org.name,
            "industry": org.industry,
            "plan": org.plan,
            "plan_ends_at": _iso(_aware(org.plan_ends_at)),
            "trial_ends_at": _iso(_aware(org.trial_ends_at)),
            "created_at": _iso(_aware(org.created_at)),
            "brand": {
                "name": org.brand_name,
                "color": org.brand_color,
                "logo_url": org.brand_logo_url,
            },
            "bot_username": org.bot_username,
        },
        "members": [
            {
                "user_id": row.user_id,
                "name": person_name(row.user_id),
                "email": users[row.user_id].email if row.user_id in users else None,
                "role": row.role,
                "created_at": _iso(_aware(row.created_at)),
            }
            for row in members
        ],
        "departments": [
            {
                "id": row.id,
                "name": row.name,
                "slug": row.slug,
                "emoji": row.emoji,
                "is_active": row.is_active,
            }
            for row in departments
        ],
        "employees": [
            {
                "id": row.id,
                "user_id": row.user_id,
                "name": person_name(row.user_id),
                "role": row.role,
                "position": row.position,
                "badge": row.badge,
                "department_id": row.department_id,
                "department": department_names.get(row.department_id),
                "hire_date": row.hire_date.isoformat() if row.hire_date else None,
                "is_active": row.is_active,
                "fired_at": _iso(_aware(row.fired_at)),
                # Личные тумблеры — тоже данные человека, поэтому в выгрузке.
                "profile_public": row.profile_public,
                "show_last_seen": row.show_last_seen,
                "show_last_media": row.show_last_media,
                "created_at": _iso(_aware(row.created_at)),
            }
            for row in employees
        ],
    }


async def request_deletion(
    session: AsyncSession,
    org: Organization,
    *,
    confirm: str,
    user: User | None,
) -> Organization:
    """Запросить удаление организации. Точный код — вместо «да, удалить»."""
    if (confirm or "").strip().lower() != org.slug.strip().lower():
        raise PrivacyError("bad_confirm")
    if org.deleted_at is not None:
        raise PrivacyError("already_deleting")
    moment = datetime.now(timezone.utc)
    org.deleted_at = moment
    org.purge_after = moment + timedelta(days=GRACE_DAYS)
    await audit.record(
        session,
        org_id=org.id,
        user=user,
        action="org.delete_requested",
        target_type="organization",
        target_id=org.id,
        details={"grace_days": GRACE_DAYS, "purge_after": org.purge_after.isoformat()},
    )
    await session.commit()
    await session.refresh(org)
    log.info("org.delete_requested", org_id=org.id, purge_after=org.purge_after)
    return org


async def cancel_deletion(
    session: AsyncSession, org: Organization, *, user: User | None
) -> Organization:
    """Отменить запрос удаления, пока срок не вышел."""
    if org.deleted_at is None:
        raise PrivacyError("not_deleting")
    org.deleted_at = None
    org.purge_after = None
    await audit.record(
        session,
        org_id=org.id,
        user=user,
        action="org.delete_canceled",
        target_type="organization",
        target_id=org.id,
    )
    await session.commit()
    await session.refresh(org)
    log.info("org.delete_canceled", org_id=org.id)
    return org


async def purge_due_orgs(
    session: AsyncSession, *, now: datetime | None = None
) -> list[int]:
    """Удалить организации, у которых вышел срок. Возвращает id удалённых.

    Каскад срабатывает в базе (`ON DELETE CASCADE` у тенантных таблиц): здесь
    один `DELETE`, а не сорок запросов по списку таблиц, где новую таблицу
    легко забыть. Глобальные `users` не трогаем — человек может работать в
    другой организации.
    """
    moment = now or datetime.now(timezone.utc)
    ids = [
        int(value)
        for value in (
            await session.scalars(
                select(Organization.id).where(
                    Organization.purge_after.is_not(None),
                    Organization.purge_after <= moment,
                )
            )
        ).all()
    ]
    if not ids:
        return []
    await session.execute(delete(Organization).where(Organization.id.in_(ids)))
    await session.commit()
    log.info("org.purged", org_ids=ids)
    return ids


__all__ = [
    "BACKUP_ARTIFACT_DAYS",
    "EXPORT_FORMAT",
    "EXPORT_VERSION",
    "GRACE_DAYS",
    "PrivacyError",
    "cancel_deletion",
    "export_org",
    "purge_due_orgs",
    "request_deletion",
    "retention",
    "state",
]
