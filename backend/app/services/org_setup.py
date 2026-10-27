"""Настройка организации: онбординг руководителя и правила видимости.

Зачем отдельный сервис, а не россыпь ключей. Онбординг руководителя отвечает
на несколько вопросов сразу — отрасль и штат, разделы, политика приватности,
наблюдение между подразделениями, — и все они должны меняться вместе. Пяток
независимых ключей легко разъехался бы: сохранили половину, приложение
работает «наполовину настроенным», и никто не понимает почему.

Хранение — `admin_config`, тот же runtime-стор, что у остальных админских
переключателей. Ключ содержит организацию: один и тот же бот может
обслуживать нескольких клиентов, и настройка одного не должна переезжать в
другой.

Что здесь НЕ живёт: сами разделы, сотрудники и подразделения. Сервис только
помнит, что руководитель выбрал, а применяют это экраны (`/api/hr/...`) и
каркас приложения (нижняя полоса и сайдбар).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminConfig
from app.db.org_models import current_org_id

# Разделы, которые руководитель может оставить или убрать. Ядро
# (`feed`/`tasks`/`checklist`/`profile`) в списке отсутствует осознанно: без
# него приложение превращается в пустой экран, и «настроить» его обратно из
# интерфейса было бы нечем.
OPTIONAL_SECTIONS: tuple[str, ...] = (
    "shifts",
    "team",
    "review",
    "reports",
    "issues",
    "handovers",
    "standards",
    "materials",
    "links",
    "calendar",
    "meetings",
)

DEFAULT_SECTIONS: tuple[str, ...] = OPTIONAL_SECTIONS

# Кто видит активность и цифры в карточке коллеги:
# * `colleagues` — как сейчас: коллеги видят, если человек не закрыл профиль;
# * `managers`   — только руководители и администраторы (личный тумблер не
#                  показывается: он ничего не решает);
# * `all_open`   — открыто всем, выключить нельзя (руководство так решило).
PROFILE_VISIBILITY = ("colleagues", "managers", "all_open")

INDUSTRIES = ("restaurant", "cafe", "salon", "autoservice", "retail", "other")

HEADCOUNTS = ("up_to_10", "10_30", "30_100", "100_plus")

_DEFAULT_KEY_PREFIX = "hr.org_setup:"


def _key(org_id: int | None = None) -> str:
    return f"{_DEFAULT_KEY_PREFIX}{org_id if org_id is not None else current_org_id.get()}"


@dataclass(frozen=True)
class OrgSetup:
    """Ответы онбординга и вытекающие из них правила."""

    done: bool = False
    industry: str = "restaurant"
    headcount: str = "10_30"
    # Названия подразделений, которые руководитель выбрал/создал в мастере.
    departments: tuple[str, ...] = ()
    sections: tuple[str, ...] = DEFAULT_SECTIONS
    profile_visibility: str = "colleagues"
    # Руководитель подразделения видит дашборды других подразделений.
    cross_department_watch: bool = False
    # Сотрудник может сам выключить «последний заход» / «последнее медиа».
    allow_hide_last_seen: bool = True
    allow_hide_media: bool = True
    # Языковой пакет (узбекский). Включён по умолчанию: часть команды — узбеки,
    # и выключенный по умолчанию перевод означал бы, что его не найдут.
    # Выключает владелец организации — в будущем это платная опция тарифа,
    # поэтому решение про деньги здесь, а не у руководителя смены.
    uz_pack: bool = True

    @property
    def can_toggle_last_seen(self) -> bool:
        return self.allow_hide_last_seen

    @property
    def can_toggle_last_media(self) -> bool:
        return self.allow_hide_media


def _clean_sections(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple):
        return DEFAULT_SECTIONS
    chosen = [item for item in raw if item in OPTIONAL_SECTIONS]
    # Порядок — как в справочнике, а не как прислал клиент: иначе нижняя
    # полоса переставлялась бы от запроса к запросу.
    return tuple(item for item in OPTIONAL_SECTIONS if item in set(chosen))


def _clean_departments(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple):
        return ()
    out: list[str] = []
    for item in raw:
        name = str(item).strip()
        if name and name not in out:
            out.append(name[:80])
    return tuple(out[:40])


def _parse(raw: str | None) -> OrgSetup:
    if not raw:
        return OrgSetup()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return OrgSetup()
    if not isinstance(data, dict):
        return OrgSetup()
    visibility = str(data.get("profile_visibility") or "colleagues")
    # Строго `isinstance(bool)`, а не `bool(...)`: строка "false" в старом
    # JSON-значении дала бы True, и выключенный пакет молча ожил бы.
    pack = data.get("uz_pack")
    return OrgSetup(
        done=bool(data.get("done")),
        industry=str(data.get("industry") or "restaurant"),
        headcount=str(data.get("headcount") or "10_30"),
        departments=_clean_departments(data.get("departments")),
        sections=_clean_sections(data.get("sections")),
        profile_visibility=(
            visibility if visibility in PROFILE_VISIBILITY else "colleagues"
        ),
        cross_department_watch=bool(data.get("cross_department_watch")),
        allow_hide_last_seen=bool(data.get("allow_hide_last_seen", True)),
        allow_hide_media=bool(data.get("allow_hide_media", True)),
        # Строго `isinstance(bool)`, а не `bool(...)`: строка "false" в старом
        # JSON-значении дала бы True, и выключённый пакет молча ожил бы.
        uz_pack=pack if isinstance(pack, bool) else True,
    )


async def load(session: AsyncSession) -> OrgSetup:
    """Текущая настройка организации. Нет строки — значения по умолчанию."""
    row = await session.get(AdminConfig, _key())
    return _parse(row.value if row is not None else None)


async def save(session: AsyncSession, setup: OrgSetup, *, commit: bool = True) -> OrgSetup:
    payload = {
        "done": setup.done,
        "industry": setup.industry,
        "headcount": setup.headcount,
        "departments": list(setup.departments),
        "sections": list(_clean_sections(setup.sections)),
        "profile_visibility": setup.profile_visibility,
        "cross_department_watch": setup.cross_department_watch,
        "allow_hide_last_seen": setup.allow_hide_last_seen,
        "allow_hide_media": setup.allow_hide_media,
        "uz_pack": setup.uz_pack,
    }
    key = _key()
    row = await session.get(AdminConfig, key)
    value = json.dumps(payload, ensure_ascii=False)
    if row is None:
        session.add(AdminConfig(key=key, value=value))
    else:
        row.value = value
    if commit:
        await session.commit()
    else:
        await session.flush()
    return replace(setup, sections=tuple(payload["sections"]))


def apply_answers(
    current: OrgSetup,
    *,
    industry: str | None = None,
    headcount: str | None = None,
    departments: list[str] | None = None,
    sections: list[str] | None = None,
    profile_visibility: str | None = None,
    cross_department_watch: bool | None = None,
    allow_hide_last_seen: bool | None = None,
    allow_hide_media: bool | None = None,
    uz_pack: bool | None = None,
    done: bool | None = None,
) -> OrgSetup:
    """Собрать новое состояние из частичного ответа мастера.

    Частичный, а не «весь объект целиком»: мастер можно пройти заново и
    поменять только один пункт, не пересылая остальные (и не затирая их
    пустыми значениями по забывчивости клиента).
    """
    next_setup = current
    if industry is not None and industry in INDUSTRIES:
        next_setup = replace(next_setup, industry=industry)
    if headcount is not None and headcount in HEADCOUNTS:
        next_setup = replace(next_setup, headcount=headcount)
    if departments is not None:
        next_setup = replace(next_setup, departments=_clean_departments(departments))
    if sections is not None:
        next_setup = replace(next_setup, sections=_clean_sections(sections))
    if profile_visibility is not None and profile_visibility in PROFILE_VISIBILITY:
        next_setup = replace(next_setup, profile_visibility=profile_visibility)
    if cross_department_watch is not None:
        next_setup = replace(
            next_setup, cross_department_watch=bool(cross_department_watch)
        )
    if allow_hide_last_seen is not None:
        next_setup = replace(
            next_setup, allow_hide_last_seen=bool(allow_hide_last_seen)
        )
    if allow_hide_media is not None:
        next_setup = replace(next_setup, allow_hide_media=bool(allow_hide_media))
    if uz_pack is not None:
        next_setup = replace(next_setup, uz_pack=bool(uz_pack))
    if done is not None:
        next_setup = replace(next_setup, done=bool(done))
    return next_setup


# --------------------------------------------------------------------------
# Готовые наборы подразделений по отрасли
# --------------------------------------------------------------------------

DEPARTMENT_PRESETS: dict[str, tuple[tuple[str, str], ...]] = {
    "restaurant": (
        ("Кухня", "👨‍🍳"),
        ("Официанты", "🍽"),
        ("Бар", "🍸"),
        ("Хостес", "🙋"),
        ("Менеджеры", "🧾"),
    ),
    "cafe": (
        ("Кухня", "👨‍🍳"),
        ("Бариста", "☕"),
        ("Зал", "🍽"),
        ("Менеджеры", "🧾"),
    ),
    "salon": (
        ("Парикмахеры", "✂️"),
        ("Мастера ногтей", "💅"),
        ("Косметологи", "🧖"),
        ("Администраторы", "🧾"),
    ),
    "autoservice": (
        ("Механики", "🔧"),
        ("Кузовной цех", "🚗"),
        ("Приёмка", "🧾"),
        ("Склад", "📦"),
    ),
    "retail": (
        ("Торговый зал", "🛍"),
        ("Касса", "💳"),
        ("Склад", "📦"),
        ("Управляющие", "🧾"),
    ),
    "other": (
        ("Основное подразделение", "🏢"),
        ("Администрация", "🧾"),
    ),
}


def presets_for(industry: str) -> list[dict[str, str]]:
    """Подсказки для шага «подразделения»: имя и эмодзи, без id."""
    items = DEPARTMENT_PRESETS.get(industry) or DEPARTMENT_PRESETS["other"]
    return [{"name": name, "emoji": emoji} for name, emoji in items]
