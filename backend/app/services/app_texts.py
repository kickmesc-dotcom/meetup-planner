"""Тексты приложения, которые можно править из админки.

Раньше здесь жил «снапшот фраз» — бэкап мемных пулов (лох/чухан/реакции). Этих
модулей больше нет, но потребность осталась: руководитель хочет менять готовые
формулировки в интерфейсе под свой ресторан — приветствие, подсказки, пустые
состояния — без релиза и без разработчика.

Как устроено:

* каталог текстов живёт в КОДЕ (`CATALOG`): код, группа, дефолт и пояснение;
* правки лежат в `admin_config` одним JSON (`app.texts`), поэтому миграция не
  нужна и откат — это удаление ключа;
* API отдаёт уже собранную карту «код → текст»; фронт подставляет её там, где
  это уместно, и всегда имеет дефолт на случай недоступного сервера.

Так текст нельзя «потерять»: дефолт остаётся в коде, а пустое значение
трактуется как «вернуть как было».
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdminConfig

STORAGE_KEY = "app.texts"
MAX_LEN = 600


class TextsError(Exception):
    """Неизвестный код или слишком длинный текст."""


@dataclass(frozen=True)
class TextSpec:
    code: str
    group: str
    title: str
    default: str
    hint: str = ""


# Намеренно небольшой стартовый набор: это тексты, которые правда хочется
# переписать под свой ресторан. Кнопки и юридически значимые подписи не
# редактируются — их нельзя ломать случайной правкой.
CATALOG: tuple[TextSpec, ...] = (
    TextSpec(
        code="tasks.empty.title",
        group="Задачи",
        title="Когда поручений нет",
        default="На сегодня всё",
    ),
    TextSpec(
        code="tasks.empty.hint",
        group="Задачи",
        title="Пояснение к пустому списку",
        default="Загляни в события смены.",
    ),
    TextSpec(
        code="checklist.empty.title",
        group="Чек-лист",
        title="Чек-лист не назначен",
        default="Чек-лист не назначен",
    ),
    TextSpec(
        code="materials.hint",
        group="Материалы",
        title="Подпись к материалам смены",
        default="График, меню и методички. Показываем копию с сервера — Google открывать не нужно.",
    ),
    TextSpec(
        code="profile.photo.hint",
        group="Профиль",
        title="Подсказка про фотоотчёт",
        default=(
            "Фотоотчёт можно снять прямо в пункте с 📷, а «не успеваю» — "
            "в карточке задачи. Чат с ботом тоже работает."
        ),
    ),
)

BY_CODE: dict[str, TextSpec] = {item.code: item for item in CATALOG}


def defaults() -> dict[str, str]:
    return {item.code: item.default for item in CATALOG}


async def _row(session: AsyncSession) -> AdminConfig | None:
    return await session.scalar(select(AdminConfig).where(AdminConfig.key == STORAGE_KEY))


async def overrides(session: AsyncSession) -> dict[str, str]:
    row = await _row(session)
    if row is None or not row.value:
        return {}
    try:
        raw = json.loads(row.value)
    except (TypeError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        code: str(value)
        for code, value in raw.items()
        if code in BY_CODE and isinstance(value, str) and value.strip()
    }


async def effective(session: AsyncSession) -> dict[str, str]:
    """Дефолты + правки. Только известные коды — мусор из конфига не отдаём."""
    texts = defaults()
    texts.update(await overrides(session))
    return texts


async def save(session: AsyncSession, values: dict[str, str]) -> dict[str, str]:
    """Сохранить правки.

    Слияние, а не замена: код, которого нет в `values`, остаётся как был.
    Пустая строка снимает правку и возвращает дефолт — иначе «очистил поле»
    выглядело бы как «ничего не изменил».
    """
    cleaned = await overrides(session)
    for code, value in values.items():
        if code not in BY_CODE:
            raise TextsError(f"unknown_text:{code}")
        text = (value or "").strip()
        if len(text) > MAX_LEN:
            raise TextsError(f"text_too_long:{code}")
        if text:
            cleaned[code] = text
        else:
            cleaned.pop(code, None)

    row = await _row(session)
    if row is None:
        session.add(AdminConfig(key=STORAGE_KEY, value=json.dumps(cleaned, ensure_ascii=False)))
    else:
        row.value = json.dumps(cleaned, ensure_ascii=False)
    await session.commit()
    return await effective(session)
