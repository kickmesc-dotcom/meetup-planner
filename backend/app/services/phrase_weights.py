"""GHG6 E5: взвешенный выбор фраз лоха/чухана по `use_count`.

Пользователь надобавлял большой пул кастомных фраз, но в каждом сообщении часто
выпадает уже виденная — `random.choice` равномерен, а пул растёт. Идея:
вес фразы = `1 / (1 + use_count)`. Новые/редко-использованные имеют больший
вес, но никогда не получают «нулевого приоритета» (всегда есть шанс выпасть).

Счётчики живут в `admin_config[<key>]` как JSON-словарь
`{phrase_hash: count}`. Ключ хэшируется (SHA1, hex, усечённый до 16 символов) —
это позволяет при правке списка фраз через `ReasonsEditor` дропать счётчики
исчезнувших фраз без вмешательства в БД: достаточно вызвать `cleanup_use_counts`
с актуальным списком.

Хэш — детерминированный, чувствителен только к содержимому (не к порядку в
списке). Нормализация перед хэшем: `strip()` (без lower — фразы могут
отличаться регистром, и админ может это хотеть; точные дубли всё равно
отбрасываются в `set_loser_reasons`/`set_chukhan_reasons`).
"""
from __future__ import annotations

import hashlib
import json
import random

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.admin_config import _get_value, _set_value

# Ключи в admin_config.
LOSER_USE_COUNTS_KEY = "loser_reasons.use_counts"
CHUKHAN_USE_COUNTS_KEY = "chukhan_reasons.use_counts"


def phrase_hash(phrase: str) -> str:
    """Стабильный короткий хэш для фразы. Длина 16 символов hex — коллизии
    в обозримом пуле (≤ ~10⁴ фраз) пренебрежимо редки."""
    return hashlib.sha1(phrase.strip().encode("utf-8")).hexdigest()[:16]


def weighted_choice(
    phrases: list[str], use_counts: dict[str, int]
) -> str | None:
    """Выбрать одну фразу с весом `1 / (1 + use_count)`.

    `use_counts` — словарь по результату `phrase_hash`. Если в нём нет записи
    для фразы — `count=0`, вес `1.0` (максимум). Если `phrases` пуст —
    возвращает `None`. Возвращаемое значение — элемент `phrases` (не копия).
    """
    if not phrases:
        return None
    weights = [1.0 / (1.0 + max(0, use_counts.get(phrase_hash(p), 0))) for p in phrases]
    # random.choices(weights=...) гарантированно вернёт элемент, если
    # суммарный вес > 0. Все веса > 0 по построению — деление никогда не на 0.
    return random.choices(phrases, weights=weights, k=1)[0]


async def get_use_counts(session: AsyncSession, key: str) -> dict[str, int]:
    raw = await _get_value(session, key)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): int(v) for k, v in data.items() if isinstance(v, int) or (isinstance(v, str) and v.lstrip("-").isdigit())}
    except (ValueError, TypeError):
        return {}
    return {}


async def set_use_counts(
    session: AsyncSession, key: str, counts: dict[str, int]
) -> None:
    await _set_value(session, key, json.dumps(counts, ensure_ascii=False))


async def increment_use_count(
    session: AsyncSession, key: str, phrase: str
) -> None:
    """Атомарность здесь умеренная (read-modify-write одной строки).
    Параллельных роллов чухана/лоха быть не может (cooldown + одиночный
    `roll_loser`), так что race-condition нерелевантен."""
    counts = await get_use_counts(session, key)
    h = phrase_hash(phrase)
    counts[h] = counts.get(h, 0) + 1
    await set_use_counts(session, key, counts)


async def clear_use_counts(session: AsyncSession, key: str) -> int:
    """Сбросить все счётчики. Возвращает сколько записей было до сброса."""
    counts = await get_use_counts(session, key)
    await set_use_counts(session, key, {})
    return len(counts)


async def cleanup_use_counts(
    session: AsyncSession, key: str, active_phrases: list[str]
) -> int:
    """Удалить счётчики фраз, которых нет в `active_phrases`. Возвращает
    количество удалённых записей. Вызывается из `set_*_reasons` после
    сохранения нового списка через `ReasonsEditor`."""
    counts = await get_use_counts(session, key)
    if not counts:
        return 0
    active_hashes = {phrase_hash(p) for p in active_phrases}
    pruned = {h: c for h, c in counts.items() if h in active_hashes}
    removed = len(counts) - len(pruned)
    if removed:
        await set_use_counts(session, key, pruned)
    return removed
