"""GHG7 P5: реакции бота на медиа (мемы/подборки).

Подсистема «оживляет» мемы участников, но не заменяет живое общение.

Модель шанса (GHG8 F-media-fix, переписана): **один честный ролл на мем**.
Заданный `chance_pct` — это вероятность, что бот вообще среагирует на медиа
(а не per-tick шанс, который раньше копился по серии из 10 проверок до ~98%).
- `chance`           — ролл сразу, при успехе реагируем без задержки.
- `wait_then_chance` — выждать `wait_window_min` (дать людям отреагировать),
  затем, если живой реакции не было, тот же одиночный ролл.
Серия отложенных проверок (`WAIT_TICKS_MIN`/`tick_chance`) удалена — именно она
превращала «шанс 10–50%» в почти-гарантию.

Этот модуль — чистое ядро (фразы-дефолты, выбор/подстановка, ролл шанса) +
get/set настроек в admin_config. Грязная часть (aiogram-handler, asyncio-ожидание)
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
    MEDIA_RECENT_MEDIA_KEY,
    MEDIA_SINGLE_PHRASES_KEY,
    _get_value,
    _set_value,
)

MediaKind = Literal["single", "collection"]

# Грейс-окно по умолчанию (мин) для режима wait_then_chance: сколько бот ждёт
# после мема, давая людям отреагировать самим, прежде чем сделать одиночный
# ролл. Настраивается в админке (admin_config: media_reactions.wait_window_min).
DEFAULT_WAIT_WINDOW_MIN = 15
# Границы клампа окна (мин): от 1 минуты до 6 часов.
WAIT_WINDOW_MIN_BOUNDS: tuple[int, int] = (1, 360)

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

# GHG8 T2.2/п.15: канонический набор эмодзи, которые Telegram принимает как
# free-реакцию на сообщение (поле `available_reactions`, type "emoji"). Список
# статический — добываем НЕ через live-API (это тронуло бы коннект, который
# заморожен 15.06), а зашиваем из документации Bot API. Если TG расширит набор,
# дополнить здесь. Набор именно для message-реакций (≠ произвольные emoji).
# Источник: Telegram available reactions (≈ те, что видны в пикере реакций).
TELEGRAM_ALLOWED_REACTIONS: frozenset[str] = frozenset({
    "👍", "👎", "❤️", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱", "🤬", "😢",
    "🎉", "🤩", "🤮", "💩", "🙏", "👌", "🕊", "🤡", "🥱", "🥴", "😍", "🐳",
    "❤‍🔥", "🌚", "🌭", "💯", "🤣", "⚡", "🍌", "🏆", "💔", "🤨", "😐", "🍓",
    "🍾", "💋", "🖕", "😈", "😴", "😭", "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈",
    "😇", "😨", "🤝", "✍", "🤗", "🫡", "🎅", "🎄", "☃️", "💅", "🤪", "🗿",
    "🆒", "💘", "🙉", "🦄", "😘", "💊", "🙊", "😎", "👾", "🤷‍♂️", "🤷", "🤷‍♀️",
    "😡",
})

# Варианты с/без VS16 (U+FE0F) — TG порой присылает «голый» кодпоинт. Нормализуем
# по «base» (без VS16), чтобы и "❤" и "❤️" считались валидными.
def _strip_vs16(s: str) -> str:
    return s.replace("️", "")


_ALLOWED_NORMALIZED: frozenset[str] = frozenset(
    _strip_vs16(e) for e in TELEGRAM_ALLOWED_REACTIONS
)


def is_allowed_reaction(emoji: str) -> bool:
    """True, если эмодзи входит в набор разрешённых TG message-реакций
    (сравнение устойчиво к наличию/отсутствию VS16)."""
    e = emoji.strip()
    return e in TELEGRAM_ALLOWED_REACTIONS or _strip_vs16(e) in _ALLOWED_NORMALIZED


def filter_allowed_reactions(emojis: list[str]) -> tuple[list[str], list[str]]:
    """Разделяет список на (валидные, отброшенные). Порядок валидных сохраняется,
    дедуп делается уровнем выше (`_clean_list`). Используется при сохранении
    whitelist'а из админки — чтобы не дать положить эмодзи, который бот всё
    равно не сможет поставить как реакцию (прод-фидбек п.15)."""
    valid: list[str] = []
    rejected: list[str] = []
    for e in emojis:
        (valid if is_allowed_reaction(e) else rejected).append(e)
    return valid, rejected


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


# --- GHG8 Q7.b: persist «последнего медиа» для force-кнопок ---
# In-memory `_recent` хендлера обнуляется при рестарте Space — force-кнопки
# отвечали «не найдено», хотя мем в чате был. Дублируем последнюю запись в
# admin_config (один JSON-ключ на бот, UPSERT при каждом медиа).

def parse_recent_media(raw: str | None) -> dict[int, tuple[str, int, str]]:
    """Чистый парсер значения MEDIA_RECENT_MEDIA_KEY → {chat_id: (kind,
    message_id, author_name)}. Невалидный JSON/структура → пустой dict
    (force-кнопка честно скажет «нет недавнего медиа», не упадёт)."""
    if raw is None:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[int, tuple[str, int, str]] = {}
    for chat_id_str, rec in data.items():
        try:
            chat_id = int(chat_id_str)
        except (ValueError, TypeError):
            continue
        if not isinstance(rec, dict):
            continue
        kind = rec.get("kind")
        message_id = rec.get("message_id")
        author_name = rec.get("author_name", "")
        if kind not in ("single", "collection") or not isinstance(message_id, int):
            continue
        if not isinstance(author_name, str):
            author_name = ""
        out[chat_id] = (kind, message_id, author_name)
    return out


async def get_recent_media_persisted(
    session: AsyncSession, chat_id: int, kind: MediaKind
) -> tuple[int, str] | None:
    """Последнее персистнутое медиа нужного типа: (message_id, author_name)
    или None. Зеркало контракта handlers.get_recent, но из БД."""
    stored = parse_recent_media(await _get_value(session, MEDIA_RECENT_MEDIA_KEY))
    rec = stored.get(chat_id)
    if rec is None or rec[0] != kind:
        return None
    return rec[1], rec[2]


async def save_recent_media(
    session: AsyncSession,
    chat_id: int,
    kind: MediaKind,
    message_id: int,
    author_name: str,
) -> None:
    """UPSERT записи «последнего медиа» чата в общий JSON-ключ. Записи других
    чатов сохраняются (на практике чат один — group_chat_id)."""
    stored = parse_recent_media(await _get_value(session, MEDIA_RECENT_MEDIA_KEY))
    stored[chat_id] = (kind, message_id, author_name)
    payload = {
        str(cid): {"kind": k, "message_id": mid, "author_name": name}
        for cid, (k, mid, name) in stored.items()
    }
    await _set_value(
        session, MEDIA_RECENT_MEDIA_KEY, json.dumps(payload, ensure_ascii=False)
    )


async def get_emoji_whitelist(session: AsyncSession) -> list[str]:
    return _load_or_default(
        await _get_value(session, MEDIA_EMOJI_WHITELIST_KEY), DEFAULT_EMOJI_WHITELIST
    )


async def set_emoji_whitelist(
    session: AsyncSession, emojis: list[str]
) -> list[str]:
    """Сохраняет whitelist, ОТСЕКАЯ эмодзи вне набора разрешённых TG-реакций
    (п.15: не давать положить то, что бот не сможет поставить). Возвращает
    список отброшенных значений — endpoint показывает их админу."""
    cleaned = _clean_list(emojis)
    valid, rejected = filter_allowed_reactions(cleaned)
    await _set_value(
        session, MEDIA_EMOJI_WHITELIST_KEY,
        json.dumps(valid, ensure_ascii=False),
    )
    return rejected


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


def clamp_wait_window(minutes: int) -> int:
    """Зажимает грейс-окно в допустимые границы (1..360 мин)."""
    lo, hi = WAIT_WINDOW_MIN_BOUNDS
    return max(lo, min(hi, minutes))


def roll_chance(pct: int, rng: random.Random | None = None) -> bool:
    """True с вероятностью pct% (0 → никогда, 100 → всегда)."""
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    return (rng or random).random() * 100 < pct
