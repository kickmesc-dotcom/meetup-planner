"""Ключи подписи ссылок на организацию (S-10/S-11).

Зачем это отдельно от `hr_media` и `ical`. Раньше обе подписи считались от
общего секрета контура: iCal — от секрета вебхука, фото — от токена бота.
Отозвать ссылку одного клиента было нельзя, а смена секрета отзывала всё и у
всех сразу. Здесь ключ принадлежит организации, поэтому ротация — её личное
дело, а не отключение сервиса для остальных.

Почему контекст, а не параметр в каждой функции. Подпись формируется в шести
местах (задачи, чек-листы, профиль, админка, кабинет, бот), и тащить ключ
через каждую сигнатуру значило бы рано или поздно забыть одно место — ссылка
молча стала бы глобальной. Контекст задаётся там, где организация уже
известна (вход сотрудника, публичная выдача фото, iCal-фид).

Обратная совместимость обязательна: уже выданные ссылки подписаны глобальным
ключом, и они должны продолжать работать. Поэтому `candidates` всегда
добавляет глобальный ключ последним.
"""

from __future__ import annotations

import secrets
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.org_models import Organization

# Сколько дней принимаем подпись предыдущего ключа после ротации. Не «пока не
# сломается»: окно должно закрываться само, иначе ротация ничего не отзывает.
PREV_VALID_DAYS = 30


@dataclass(frozen=True)
class Keys:
    """Текущий и предыдущий ключ организации (байты)."""

    current: bytes
    previous: bytes | None = None
    previous_until: datetime | None = None

    def candidates(self, fallback: bytes) -> list[bytes]:
        """Ключи для проверки: текущий, предыдущий (в окне), глобальный.

        Глобальный — всегда последним: старые ссылки не должны отваливаться
        в день выкладки, а окно совместимости закрывается отдельно.
        """
        out = [self.current]
        if self.previous is not None:
            until = self.previous_until
            if until is None or datetime.now(UTC) < until:
                out.append(self.previous)
        if fallback not in out:
            out.append(fallback)
        return out


def global_key() -> bytes:
    """Глобальный ключ контура — только для совместимости со старыми ссылками."""
    return get_settings().bot_token.encode("utf-8")


_keys: ContextVar[Keys | None] = ContextVar("link_keys", default=None)


def current() -> Keys | None:
    return _keys.get()


def activate(keys: Keys) -> Token[Keys | None]:
    return _keys.set(keys)


def deactivate(token: Token[Keys | None]) -> None:
    _keys.reset(token)


def keys_for(org: Organization) -> Keys:
    """Ключи из строки организации. Пустой ключ сюда не попадает — см. `ensure`."""
    if not org.media_key:
        raise ValueError("organization_has_no_media_key")
    prev = org.media_key_prev.encode("utf-8") if org.media_key_prev else None
    until = (
        org.media_key_rotated_at + timedelta(days=PREV_VALID_DAYS)
        if org.media_key_rotated_at is not None
        else None
    )
    return Keys(
        current=org.media_key.encode("utf-8"),
        previous=prev,
        previous_until=until,
    )


async def ensure(session: AsyncSession, org: Organization) -> Organization:
    """Гарантировать ключ у организации.

    Коммитим сразу: ключ должен пережить запрос. Если оставить его в открытой
    транзакции, GET-запрос её не закроет, ключ не сохранится, и каждая выдача
    подпишет ссылку новым случайным ключом — то есть сломает предыдущую.
    """
    if org.media_key:
        return org
    org.media_key = secrets.token_hex(32)
    await session.commit()
    await session.refresh(org)
    return org


async def activate_org(
    session: AsyncSession, org_id: int
) -> tuple[Token[Keys | None] | None, Organization | None]:
    """Загрузить организацию, выдать ей ключ при необходимости и включить контекст."""
    org = await session.get(Organization, org_id)
    if org is None:
        return None, None
    await ensure(session, org)
    return activate(keys_for(org)), org


async def rotate(session: AsyncSession, org: Organization) -> datetime:
    """Сменить ключ организации, оставив предыдущий на окно совместимости."""
    await ensure(session, org)
    org.media_key_prev = org.media_key
    org.media_key = secrets.token_hex(32)
    org.media_key_rotated_at = datetime.now(UTC)
    await session.flush()
    return org.media_key_rotated_at
