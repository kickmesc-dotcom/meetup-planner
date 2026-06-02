"""GHG7 P5: реакции бота на медиа (мемы/подборки).

Подсистема «оживляет» мемы участников, но не заменяет живое общение: реакция
ставится только если люди сами не отреагировали (серия отложенных проверок с
динамическим шансом — см. handlers/media_reactions.py).

Этот модуль — чистое ядро (фразы-дефолты, выбор/подстановка, ролл шанса) +
get/set настроек в admin_config. Грязная часть (aiogram-handler, asyncio-серия)
живёт в app/bot/handlers/media_reactions.py.
"""

from __future__ import annotations

import json
import random
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.admin_config import (
    MEDIA_COLLECTION_PHRASES_KEY,
    MEDIA_EMOJI_WHITELIST_KEY,
    MEDIA_SINGLE_PHRASES_KEY,
    _get_value,
    _set_value,
)

MediaKind = Literal["single", "collection"]

# Серия отложенных проверок «отсутствия реакции» — моменты в минутах ОТ мема.
# Чем раньше тик, тем ниже шанс (растёт равномерно по номеру тика, см.
# tick_chance). Решено с пользователем (GHG7 P5).
WAIT_TICKS_MIN: tuple[int, ...] = (5, 10, 15, 30, 45, 60, 90, 120, 180, 260)

# Дефолтные фразы — из GHG7.txt (стр. 58-101 single, 105-140 collection).
# Хранятся в admin_config как JSON; пока админ не кастомизировал — берём отсюда
# (паттерн loser_reasons: новые фразы в коде подхватываются до первой правки).
DEFAULT_SINGLE_PHRASES: list[str] = [
    "жиза",
    "четко",
    "ну база же",
    "внатуре",
    "осуждаю",
    "смэрть",
    "лол",
    "было сложно, но я подрочил",
    "агонь",
    "хорошо",
    "баян вроде",
    "охуенчик",
    "а ведь и правда...",
    "тупа я",
    "напомнил детство",
    "уже было в симпсонах",
    "Хорош, прям в точку.",
    "Разъеб",
    "Это мощно",
    "Мем дня, однозначно",
    "%username% Мемолог от бога",
    "Респект",
    "Что за годнота",
    "Легендарный вброс.",
    "Слишком хорошо.",
    "Это в золотой фонд.",
    "Отличный мем!",
    "Очень зашло!",
    "Хорошая находка!",
    "Спасибо, поднял настроение!",
    "Это реально смешно!",
    "Сильная подача!",
    "Прям порадовал!",
    "Качественный контент!",
    "Хороший вкус, как всегда!",
    "Ну всё, интернет можно закрывать.",
    "Это настолько тупо, что даже хорошо.",
    "Мем-пушка, мозг в щепки.",
    "Спасибо, отупел.",
    "Это должно быть незаконно",
    "Кринжанул",
    "У тебя скрытый талант, продолжай его скрывать",
    "Мем уровня “сохранить и стыдиться”.",
]

DEFAULT_COLLECTION_PHRASES: list[str] = [
    "Сегодня лучше",
    "На удивление борденько",
    "Хорошо постарался %username%",
    "красава",
    "спасибо, вкусно покушал",
    "без тебя чат бы умер... или стал лучше",
    "Мемный сомелье нашего болота.",
    "Спасибо за ежедневную дозу дегенеративного искусства.",
    "Ты как контент-ферма, только бесплатно",
    "Наш локальный министр мемологии",
    "Благодаря тебе продуктивность в чате стабильно на нуле",
    "Человек, который не дает умереть кринжу",
    "Спасибо за вклад в коллективную деградацию",
    "Мемный спам-террорист, но любимый.",
    "Респект за стабильную поставку годноты.",
    "Главный по мемам, без вопросов.",
    "Ты держишь этот чат на плаву.",
    "Поставщик хорошего настроения.",
    "Без тебя тут было бы скучнее.",
    "Спасибо за контент, легенда.",
    "Мемный MVP компании.",
    "Ты реально делаешь чат живым.",
    "Уровень вклада — национальное достояние.",
    "Спасибо за регулярный подгон настроения.",
    "Спасибо, что постоянно радуешь нас!",
    "Ты реально добавляешь жизни в этот чат!",
    "Ценим твой вклад в общее настроение!",
    "Спасибо за внимание к компании!",
    "Ты создаешь атмосферу!",
    "Очень круто, что ты так стараешься!",
    "Спасибо за позитив!",
    "С тобой чат становится лучше!",
    "Ценим твою активность!",
    "Реально приятно, что ты всегда накидываешь что-то веселое. Ты молодец и хороший друг!",
]

# Telegram разрешает реакции только из фиксированного набора эмодзи. Дефолт —
# осмысленные «реакционные» (смех/огонь/сердце/100 и т.п.), НЕ цифры/служебные.
# Если админ добавит неподдерживаемый эмодзи — set_message_reaction вернёт
# ошибку, handler её проглотит (best-effort).
DEFAULT_EMOJI_WHITELIST: list[str] = [
    "👍", "🔥", "❤️", "😁", "🤣", "💯", "👏", "🤝", "🥰", "😱", "🤯", "🫡",
]


def _clean_list(items: list[str]) -> list[str]:
    """Дедуп + чистка пустых, порядок сохраняется."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for it in items:
        it = it.strip()
        if not it or it in seen:
            continue
        seen.add(it)
        cleaned.append(it)
    return cleaned


def _load_or_default(raw: str | None, default: list[str]) -> list[str]:
    if raw is None:
        return list(default)
    try:
        data = json.loads(raw)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return data
    except (ValueError, TypeError):
        pass
    return list(default)


async def get_single_phrases(session: AsyncSession) -> list[str]:
    return _load_or_default(
        await _get_value(session, MEDIA_SINGLE_PHRASES_KEY), DEFAULT_SINGLE_PHRASES
    )


async def set_single_phrases(session: AsyncSession, phrases: list[str]) -> None:
    await _set_value(
        session, MEDIA_SINGLE_PHRASES_KEY,
        json.dumps(_clean_list(phrases), ensure_ascii=False),
    )


async def get_collection_phrases(session: AsyncSession) -> list[str]:
    return _load_or_default(
        await _get_value(session, MEDIA_COLLECTION_PHRASES_KEY),
        DEFAULT_COLLECTION_PHRASES,
    )


async def set_collection_phrases(session: AsyncSession, phrases: list[str]) -> None:
    await _set_value(
        session, MEDIA_COLLECTION_PHRASES_KEY,
        json.dumps(_clean_list(phrases), ensure_ascii=False),
    )


async def get_emoji_whitelist(session: AsyncSession) -> list[str]:
    return _load_or_default(
        await _get_value(session, MEDIA_EMOJI_WHITELIST_KEY), DEFAULT_EMOJI_WHITELIST
    )


async def set_emoji_whitelist(session: AsyncSession, emojis: list[str]) -> None:
    await _set_value(
        session, MEDIA_EMOJI_WHITELIST_KEY,
        json.dumps(_clean_list(emojis), ensure_ascii=False),
    )


# --- Чистые функции (юнит-тестируемые без БД) ---

def substitute_username(template: str, username: str) -> str:
    """Подставляет имя автора вместо %username% в шаблон фразы."""
    return template.replace("%username%", username)


def pick_phrase(phrases: list[str], rng: random.Random | None = None) -> str | None:
    """Случайная фраза из пула, None если пул пуст."""
    if not phrases:
        return None
    return (rng or random).choice(phrases)


def pick_emoji(whitelist: list[str], rng: random.Random | None = None) -> str | None:
    """Случайный эмодзи из whitelist'а, None если пуст."""
    if not whitelist:
        return None
    return (rng or random).choice(whitelist)


def tick_chance(
    tick_index: int, base_pct: int, max_pct: int, n_ticks: int = len(WAIT_TICKS_MIN)
) -> int:
    """Шанс (в %) на тике серии выжидания.

    Растёт равномерно по НОМЕРУ тика: tick_index=0 → base_pct,
    tick_index=n_ticks-1 → max_pct (линейная интерполяция). Решено с
    пользователем: чем раньше проверка, тем ниже шанс среагировать сейчас.
    """
    if n_ticks <= 1:
        return max(0, min(100, max_pct))
    idx = max(0, min(n_ticks - 1, tick_index))
    span = max_pct - base_pct
    pct = base_pct + round(span * idx / (n_ticks - 1))
    return max(0, min(100, pct))


def roll_chance(pct: int, rng: random.Random | None = None) -> bool:
    """True с вероятностью pct% (0 → никогда, 100 → всегда)."""
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    return (rng or random).random() * 100 < pct
