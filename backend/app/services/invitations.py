"""Приглашения в организацию (B2B_PLATFORM_PLAN, шаг 2.2).

Задача одна: человек получает ссылку, открывает её и оказывается **в той
организации, которая его позвала**, а не в первой по `id`. Именно поэтому
логика живёт здесь, а не в роутере: `org_id` приглашения — единственный
источник правды о том, куда присоединяться, и его нельзя брать из заголовка
или из членства, которого у приглашённого ещё нет.

Три правила, без которых ссылка превращается в дыру:

* в базе только SHA-256 от токена (ссылка неделю живёт в мессенджере);
* ссылка одноразовая: `accepted_at` закрывает повторный переход;
* если в приглашении указана почта, принять его может только её владелец —
  иначе пересланная ссылка даёт доступ постороннему.

Поиск по токену идёт ДО того, как известна организация, поэтому он
оборачивается в `all_orgs()`: обычный тенантский фильтр искал бы приглашение
только в первой организации и «не находил» бы ссылки остальных клиентов.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.auth_models import AuthSession
from app.db.models import User
from app.db.org_models import ORG_ROLES, Organization, OrgInvitation, set_org
from app.db.tenancy import all_orgs
from app.services import accounts, orgs

# Ссылка живёт неделю: её успевают переслать в чат смены и открыть с телефона.
INVITE_TTL_DAYS = 7
MAX_TTL_DAYS = 30
# Больше полусотни живых ссылок на организацию — это уже не приглашения, а
# забытые черновики; список в админке должен оставаться читаемым.
MAX_ACTIVE = 50


class InvitationsError(Exception):
    """Код уходит клиенту в `detail`, текст — на фронте."""


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    """sqlite отдаёт naive datetime: сравнивать с aware нельзя."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def invite_link(token: str) -> str:
    """Ссылка из письма/чата: та же база, что у сброса пароля."""
    return f"{get_settings().link_base}/invite?token={token}"


async def _by_token(session: AsyncSession, token: str) -> OrgInvitation | None:
    if not token or len(token) > 128:
        return None
    with all_orgs():
        return await session.scalar(
            select(OrgInvitation).where(
                OrgInvitation.token_hash == accounts.token_hash(token)
            )
        )


async def create(
    session: AsyncSession,
    *,
    org_id: int,
    created_by_id: int | None,
    role: str = "staff",
    email: str | None = None,
    days: int = INVITE_TTL_DAYS,
) -> tuple[OrgInvitation, str]:
    """Выписать приглашение. Возвращает (строка, токен для ссылки)."""
    if role not in ORG_ROLES:
        raise InvitationsError("bad_role")
    if days < 1 or days > MAX_TTL_DAYS:
        raise InvitationsError("bad_invite_ttl")

    clean_email: str | None = None
    if email and email.strip():
        try:
            clean_email = accounts.normalize_email(email)
        except accounts.AccountsError as exc:
            raise InvitationsError(str(exc)) from exc

    if len(await active(session, org_id)) >= MAX_ACTIVE:
        raise InvitationsError("invite_limit")

    token = secrets.token_urlsafe(32)
    row = OrgInvitation(
        org_id=org_id,
        email=clean_email,
        role=role,
        token_hash=accounts.token_hash(token),
        created_by_user_id=created_by_id,
        expires_at=_now() + timedelta(days=days),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row, token


async def active(session: AsyncSession, org_id: int) -> list[OrgInvitation]:
    """Живые приглашения организации (фильтр по сроку — в Python).

    Почему не `WHERE expires_at > now()`: в sqlite время хранится строкой и
    сравнение aware/naive даёт разный результат в тестах и на Postgres. Строк
    у организации десятки, поэтому честнее отфильтровать после чтения.
    """
    now = _now()
    # Организация передана явно, поэтому фильтр тенанта здесь только мешал бы:
    # при вызове из платформенного кода контекст может быть другим.
    with all_orgs():
        rows = await session.scalars(
            select(OrgInvitation)
            .where(
                OrgInvitation.org_id == org_id,
                OrgInvitation.accepted_at.is_(None),
                OrgInvitation.revoked_at.is_(None),
            )
            .order_by(OrgInvitation.created_at.desc())
        )
        return [row for row in rows if _aware(row.expires_at) > now]


async def preview(
    session: AsyncSession, token: str
) -> tuple[OrgInvitation, Organization]:
    """Что увидит человек до входа: организация, роль, срок."""
    row = await _by_token(session, token)
    if row is None:
        raise InvitationsError("invite_invalid")
    if row.revoked_at is not None:
        raise InvitationsError("invite_revoked")
    if row.accepted_at is not None:
        raise InvitationsError("invite_used")
    if _aware(row.expires_at) <= _now():
        raise InvitationsError("invite_expired")
    org = await session.get(Organization, row.org_id)
    if org is None:
        raise InvitationsError("invite_invalid")
    if not org.is_active:
        raise InvitationsError("org_inactive")
    return row, org


async def accept(
    session: AsyncSession, *, token: str, user: User
) -> tuple[Organization, str]:
    """Присоединить человека к пригласившей организации.

    Возвращает (организация, роль в ней). Если человек уже состоит в этой
    организации, роль не меняется: ссылка могла быть переслана, и повышать по
    ней права — не то, чего ждёт управляющий.
    """
    row, org = await preview(session, token)
    if row.email and (user.email or "").strip().lower() != row.email:
        # Ссылка «на почту» — это именное приглашение. Пустая почта у
        # Telegram-аккаунта сюда же: его звали не по этому адресу.
        raise InvitationsError("invite_email_mismatch")

    existing = await orgs.member(session, org_id=org.id, user_id=user.id)
    if existing is None:
        member = await orgs.add_member(
            session, org_id=org.id, user_id=user.id, role=row.role
        )
        role = member.role
    else:
        role = existing.role

    # Дальше в этом запросе (и в следующем, если сессия обновится) человек
    # живёт в пригласившей организации. Без этого `ensure_employee` создал бы
    # профиль в первой по id — ровно та ошибка, от которой защищает шаг 2.2.
    set_org(org.id)

    row.accepted_at = _now()
    row.accepted_by_user_id = user.id
    await session.commit()

    # Живые входы переводим в новую организацию: человек мог быть уже вошёл
    # на другом устройстве, и сессия помнит организацию на момент входа.
    # Обновляем объекты, а не bulk-update: иначе в этой же сессии остались бы
    # строки со старым `org_id` (identity map), и следующий тест/запрос увидел
    # бы «ничей» вход.
    live = await session.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)
        )
    )
    for auth_row in live:
        auth_row.org_id = org.id
    await session.commit()
    return org, role


async def revoke(
    session: AsyncSession, *, org_id: int, invitation_id: int
) -> OrgInvitation:
    """Отозвать ссылку. Тенантский фильтр не даст чужую организацию."""
    row = await session.get(OrgInvitation, invitation_id)
    if row is None or row.org_id != org_id:
        raise InvitationsError("invite_not_found")
    if row.accepted_at is not None:
        raise InvitationsError("invite_already_accepted")
    if row.revoked_at is None:
        row.revoked_at = _now()
        await session.commit()
        await session.refresh(row)
    return row
