"""GHG8 J.1: метаданные фраз — источник (`source`) и мягкое скрытие (`hidden`).

Задача (прод-фидбек 28.09): пулы фраз регулярно пополняются контент-дропами
(≈+50 фраз/пул раз в месяц). Нужно (а) отличать «мои/участников» фразы от
«ИИ-слопа» и (б) временно исключать неудачные фразы из ротации, НЕ удаляя их.

Реализация — **без изменения схемы БД и без миграции**: пулы остаются
`list[str]` в `admin_config` (формат пулов и снапшот не ломаются), а метаданные
лежат рядом отдельным ключом `phrases.meta`:

    {
      "<pool>": {
        "<phrase_hash>": {"source": "ai", "hidden": true,
                          "added_at": "...", "added_by": 123}
      }
    }

Ключ — тот же `phrase_hash`, что используется в `phrase_weights.use_counts`,
поэтому связка бесплатная и переживает правку списка (хэш зависит только от
текста фразы).

Поведение по умолчанию (обратная совместимость): записи нет → фраза считается
`manual` и видимой. Это значит, что существующие фразы ничего не теряют, а
скрытие — всегда явное действие.

Чистые функции (normalize_source/is_hidden/visible_phrases/update_entry/
items_for/parse_meta) вынесены без БД-IO — их и тестируем. Async-обёртки ходят
в admin_config.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.admin_config import _get_value, _set_value
from app.services.phrase_weights import phrase_hash

META_KEY = "phrases.meta"

# Допустимые источники фразы.
SOURCE_MANUAL = "manual"      # заведена руками (в т.ч. через редактор)
SOURCE_AI = "ai"              # контент-дроп, сгенерированный ассистентом
SOURCE_IMPORT = "import"      # пришла из снапшота без явного источника
SOURCE_PERSONA = "persona"    # из персоны/типажа
SOURCES: tuple[str, ...] = (SOURCE_MANUAL, SOURCE_AI, SOURCE_IMPORT, SOURCE_PERSONA)


def normalize_source(value: Any) -> str:
    """Привести источник к допустимому значению. Неизвестное → `manual`
    (безопасный дефолт: фраза считается «своей» и видимой)."""
    if isinstance(value, str):
        v = value.strip().lower()
        if v in SOURCES:
            return v
    return SOURCE_MANUAL


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- чистое ядро

def normalize_meta(data: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """Привести произвольный (уже распарсенный) объект к структуре метаданных.
    Мусор → пустой словарь (толерантно: битая мета не должна ронять выбор
    фраз)."""
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for pool, entries in data.items():
        if not isinstance(pool, str) or not isinstance(entries, dict):
            continue
        clean: dict[str, dict[str, Any]] = {}
        for h, entry in entries.items():
            if isinstance(h, str) and isinstance(entry, dict):
                clean[h] = entry
        if clean:
            out[pool] = clean
    return out


def parse_meta(raw: str | None) -> dict[str, dict[str, dict[str, Any]]]:
    """Разобрать сырое значение ключа `phrases.meta` (JSON-строка)."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return normalize_meta(data)


def entry_for(
    meta: dict[str, dict[str, dict[str, Any]]], pool: str, phrase: str
) -> dict[str, Any]:
    """Запись метаданных для фразы (или пустой dict)."""
    return (meta.get(pool) or {}).get(phrase_hash(phrase)) or {}


def is_hidden(
    meta: dict[str, dict[str, dict[str, Any]]], pool: str, phrase: str
) -> bool:
    """Скрыта ли фраза (временно исключена из ротации)."""
    return bool(entry_for(meta, pool, phrase).get("hidden"))


def source_of(
    meta: dict[str, dict[str, dict[str, Any]]], pool: str, phrase: str
) -> str:
    """Источник фразы (по умолчанию `manual`)."""
    return normalize_source(entry_for(meta, pool, phrase).get("source"))


# Э19: какие источники считаем «ручными», а какие «ИИ». Импорт — это тоже
# ручной путь (снапшот), персоны — генерация, как и контент-дроп.
_MANUAL_SOURCES = (SOURCE_MANUAL, SOURCE_IMPORT)
_AI_SOURCES = (SOURCE_AI, SOURCE_PERSONA)


def filter_by_source_mode(
    meta: dict[str, dict[str, dict[str, Any]]],
    pool: str,
    phrases: list[str],
    mode: str,
) -> list[str]:
    """Оставить фразы выбранного источника. Чистая функция.

    `both` — всё; `manual` — ручные/импорт; `ai` — ИИ-дроп и персоны. Неизвестный
    режим трактуем как `both` (безопасный дефолт).
    """
    if mode == "manual":
        allowed = _MANUAL_SOURCES
    elif mode == "ai":
        allowed = _AI_SOURCES
    else:
        return list(phrases)
    return [p for p in phrases if source_of(meta, pool, p) in allowed]


def visible_phrases(
    meta: dict[str, dict[str, dict[str, Any]]], pool: str, phrases: list[str]
) -> list[str]:
    """Отфильтровать скрытые фразы, сохранив порядок."""
    return [p for p in phrases if not is_hidden(meta, pool, p)]


def _is_default_entry(entry: dict[str, Any]) -> bool:
    """Запись не несёт информации (= дефолт: видима и источник `manual`) →
    её не нужно хранить. `added_at`/`added_by` — только провенанс, они не
    делают запись значимой (иначе «скрыл → вернул» оставлял бы мусор)."""
    return not entry.get("hidden") and normalize_source(entry.get("source")) == SOURCE_MANUAL


def update_entry(
    meta: dict[str, dict[str, dict[str, Any]]],
    pool: str,
    phrase: str,
    *,
    source: str | None = None,
    hidden: bool | None = None,
    added_by: int | None = None,
) -> dict[str, Any]:
    """Обновить/создать запись. Если после правки запись стала дефолтной —
    удаляем её (держим `phrases.meta` компактным). Возвращает итоговую запись
    (пустой dict, если удалена). Мутирует `meta`."""
    h = phrase_hash(phrase)
    entries = meta.setdefault(pool, {})
    entry = dict(entries.get(h) or {})
    if source is not None:
        entry["source"] = normalize_source(source)
    if hidden is not None:
        entry["hidden"] = bool(hidden)
    if added_by is not None:
        entry["added_by"] = int(added_by)

    if _is_default_entry(entry):
        entries.pop(h, None)
        if not entries:
            meta.pop(pool, None)
        return {}
    if not entry.get("added_at"):
        entry["added_at"] = _now_iso()
    entries[h] = entry
    return entry


def items_for(
    meta: dict[str, dict[str, dict[str, Any]]], pool: str, phrases: list[str]
) -> list[dict[str, Any]]:
    """Список для UI: `[{phrase, source, hidden}]` в порядке пула."""
    out: list[dict[str, Any]] = []
    for p in phrases:
        e = entry_for(meta, pool, p)
        out.append(
            {
                "phrase": p,
                "source": normalize_source(e.get("source")),
                "hidden": bool(e.get("hidden")),
            }
        )
    return out


# ------------------------------------------------------------------- БД-слой

async def load_meta(session: AsyncSession) -> dict[str, dict[str, dict[str, Any]]]:
    return parse_meta(await _get_value(session, META_KEY))


async def save_meta(
    session: AsyncSession, meta: dict[str, dict[str, dict[str, Any]]]
) -> None:
    await _set_value(session, META_KEY, json.dumps(meta, ensure_ascii=False))


async def effective_pool(
    session: AsyncSession, pool: str, phrases: list[str]
) -> list[str]:
    """Пул для ВЫБОРА ботом: без скрытых фраз.

    Страховка: если скрыто ВСЁ (после фильтра пусто, а исходный пул не пуст) —
    возвращаем исходный список. «Скрыть всё» не должно ломать постинг
    (защита от IndexError в `random.choice` на стороне вызывающего)."""
    if not phrases:
        return phrases
    meta = await load_meta(session)
    visible = visible_phrases(meta, pool, phrases)
    if not visible:
        return phrases
    # Э19: глобальный свитчер источника (ручные / ИИ / оба). Ленивый импорт —
    # admin_config уже импортирован модулем, но геттер тянем точечно, как везде.
    from app.services.admin_config import get_phrases_source_mode

    mode = await get_phrases_source_mode(session)
    chosen = filter_by_source_mode(meta, pool, visible, mode)
    # Безопасный фолбэк: если выбранный источник пуст, отдаём видимые фразы —
    # «только ИИ» на пуле без ИИ не должно ломать постинг.
    return chosen or visible


async def set_flags(
    session: AsyncSession,
    pool: str,
    phrase: str,
    *,
    source: str | None = None,
    hidden: bool | None = None,
    added_by: int | None = None,
) -> dict[str, Any]:
    meta = await load_meta(session)
    entry = update_entry(
        meta, pool, phrase, source=source, hidden=hidden, added_by=added_by
    )
    await save_meta(session, meta)
    return entry


async def bulk_set_flags(
    session: AsyncSession,
    pool: str,
    phrases: list[str],
    *,
    source: str | None = None,
    hidden: bool | None = None,
    added_by: int | None = None,
) -> int:
    """Массово проставить флаги. Возвращает число обработанных фраз."""
    meta = await load_meta(session)
    n = 0
    for p in phrases:
        if not (p or "").strip():
            continue
        update_entry(
            meta, pool, p, source=source, hidden=hidden, added_by=added_by
        )
        n += 1
    await save_meta(session, meta)
    return n


async def tag_source(
    session: AsyncSession, pool: str, phrases: list[str], source: str
) -> int:
    """Пометить источник у набора фраз (используется импортом снапшота)."""
    return await bulk_set_flags(session, pool, phrases, source=source)


async def prune(session: AsyncSession, pool: str, phrases: list[str]) -> int:
    """Удалить записи метаданных для фраз, которых больше нет в пуле.
    Лениво вызывать не обязательно (осиротевшие записи безвредны), но полезно
    для компактности `phrases.meta`."""
    meta = await load_meta(session)
    entries = meta.get(pool)
    if not entries:
        return 0
    alive = {phrase_hash(p) for p in phrases}
    kept = {h: e for h, e in entries.items() if h in alive}
    removed = len(entries) - len(kept)
    if removed:
        if kept:
            meta[pool] = kept
        else:
            meta.pop(pool, None)
        await save_meta(session, meta)
    return removed
