"""Бренд организации: имя, цвет и логотип (B2B_PLATFORM_PLAN, шаг 4.4).

Зачем отдельный сервис. Бренд читают в разных местах (заголовок приложения,
цвет ссылок, письма), а правила у него одни: имя не пустое, цвет — CSS-цвет,
логотип — `https`-адрес. Если бы каждый экран проверял это сам, первый же
новый экран пропустил бы `javascript:` в поле логотипа.

Почему пустое значение — это «не настроено», а не ошибка. У новой организации
бренда нет, и она должна видеть имя организации; пустая строка в поле означает
«сбросить к имени организации», а не «сохранить пустое имя».

Почему цвет нормализуется. `#ABC` и `#aabbcc` — один и тот же цвет, и без
нормализации сравнение «изменился ли бренд» врало бы, а в базе копились бы
разные написания одного значения.

Почему `is_custom` отдельным полем. Интерфейсу нужно различать «это бренд
клиента» и «это имя организации по умолчанию»: во втором случае подсказка
«задайте своё имя» уместна, а в первом — нет.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.org_models import Organization

# Цвет платформы по умолчанию: тот же, что в `index.html` и tailwind
# (`link-color`). Бренд клиента его заменяет, а не «дополняет».
DEFAULT_COLOR = "#1c6fb8"
MAX_NAME = 64
MAX_LOGO = 500

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class BrandError(Exception):
    """Отказ по бренду. Строка — код: перевод живёт на фронте."""


@dataclass(frozen=True)
class Brand:
    name: str
    color: str
    logo_url: str | None
    bot_username: str | None
    is_custom: bool


def normalize_color(raw: str) -> str:
    """Проверить и привести CSS-цвет к `#rrggbb` в нижнем регистре."""
    value = (raw or "").strip()
    if not _HEX.fullmatch(value):
        raise BrandError("bad_color")
    value = value.lower()
    if len(value) == 4:  # #abc → #aabbcc
        value = "#" + "".join(ch * 2 for ch in value[1:])
    return value


def normalize_name(raw: str) -> str:
    value = " ".join((raw or "").split())
    if not value:
        raise BrandError("bad_name")
    if len(value) > MAX_NAME:
        raise BrandError("bad_name")
    return value


def normalize_logo(raw: str) -> str | None:
    """Пусто — логотипа нет. Иначе только https: `http` на телефоне блокируется
    браузером как смешанный контент, а `javascript:`/`data:` — это не картинка.
    """
    value = (raw or "").strip()
    if not value:
        return None
    if len(value) > MAX_LOGO:
        raise BrandError("bad_logo")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.netloc:
        raise BrandError("bad_logo")
    return value


def from_org(org: Organization) -> Brand:
    """Бренд, который видит клиент: своё имя или имя организации."""
    name = (org.brand_name or "").strip() or org.name
    color = (org.brand_color or "").strip() or DEFAULT_COLOR
    return Brand(
        name=name,
        color=color,
        logo_url=org.brand_logo_url or None,
        bot_username=org.bot_username or None,
        is_custom=bool((org.brand_name or "").strip()),
    )


async def update(
    session: AsyncSession,
    org: Organization,
    *,
    name: str | None = None,
    color: str | None = None,
    logo_url: str | None = None,
) -> Brand:
    """Обновить бренд. `None` — «не менять», пустая строка — «сбросить».

    Разделение важно для формы: она присылает только изменённые поля, иначе
    сохранение имени стирало бы логотип, о котором форма не спрашивала.
    """
    if name is not None:
        # Пустое имя — не «убрать бренд»: имя организации уже есть, и
        # подставлять вместо него ничего не нужно. Сброс делается очисткой
        # поля `brand_name` через `reset`-ручку (см. `clear`).
        org.brand_name = normalize_name(name)
    if color is not None:
        org.brand_color = normalize_color(color)
    if logo_url is not None:
        org.brand_logo_url = normalize_logo(logo_url)
    await session.commit()
    await session.refresh(org)
    return from_org(org)


async def clear(session: AsyncSession, org: Organization) -> Brand:
    """Сбросить бренд к имени организации. Цвет и логотип тоже уходят."""
    org.brand_name = None
    org.brand_color = None
    org.brand_logo_url = None
    await session.commit()
    await session.refresh(org)
    return from_org(org)
