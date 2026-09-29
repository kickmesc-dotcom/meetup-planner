"""GHG10 Э13: «Контрабанда» локальных слов.

Задание:

    Бот отслеживает определённые слова и выражения. Например кто-то пишет
    «нейронка» — бот: 💰 Слово "нейронка" обнаружено (ловим любые формулировки,
    ИИ, Ai, Эйай, нейро-). Серж получает +1 к пассивному заработку.
    Или «пиздец» — это слово принадлежит Митяну (пизда, пизды — любые
    формулировки). Лицензионный сбор: 5 XP. (Митян — слово мило),
    (Никита — согласен), (Руслан — игра/играть). Это заставляет людей
    взаимодействовать с ботом даже без команды.

Ключевое отличие от остальных игровых событий: опыт получает ВЛАДЕЛЕЦ слова, а
не тот, кто его написал. То есть упомянуть чужое кодовое слово — это жест:
ты кормишь приятеля очками совершенно безвозмездно. Ровно поэтому это и
работает как социальная механика.

Три ручки в админке (`game.contraband.*`): включено/выключено, вероятность
срабатывания в процентах и суточный кэп на слово. Сам реестр слов тоже
редактируется — если он не задан, берётся `DEFAULT_WORDS` отсюда.
"""
from __future__ import annotations

import random
import re
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.services.admin_config import (
    get_game_contraband_chance_percent,
    get_game_contraband_daily_cap,
    get_game_contraband_enabled,
    get_game_contraband_words,
)
from app.services.game import awards, journal

log = structlog.get_logger()

# Дефолтный реестр. `variants` — регэкспы (ловим любые формулировки), `labels` —
# то же человеческим языком, потому что показывать человеку регулярку нельзя.
#
# ⚠️ Владельца ищем СНАЧАЛА по `owner_tg_id`, и только потом по имени. Имя —
# плохой ключ: в базе живут «Серж-NEO» и «Русланище», а дефолты когда-то были
# написаны как «Серж» и «Руслан», поэтому два слова из четырёх молча не платили
# никому (в логах `game.contraband_owner_not_found`). Поэтому tg-id проставлены
# всем шестерым участникам — это устойчивый ключ, а имя только для читаемости.
DEFAULT_WORDS: tuple[dict, ...] = (
    {
        "word": "нейронка",
        "owner": "Серж-NEO",
        "owner_tg_id": 306733739,
        "variants": [r"нейронк\w*", r"\bнейро-?\w*", r"\bии\b", r"\bai\b", r"\bэйай\b"],
        "labels": ["нейро", "ИИ", "Ai", "Эйай", "нейро-"],
        "xp": 5,
        "note": "пассивный заработок",
    },
    {
        "word": "пиздец",
        "owner": "Митян",
        "owner_tg_id": 52765607,
        "variants": [r"пизд\w*", r"\bпезд\w*"],
        "labels": ["пизда", "пизды", "пиздец"],
        "xp": 5,
        "note": "лицензионный сбор",
    },
    {
        "word": "согласен",
        "owner": "Никита",
        "owner_tg_id": 380170615,
        "variants": [r"\bсогласен\b", r"\bсогласна\b", r"\bсогласны\b"],
        "labels": ["согласен", "согласна"],
        "xp": 5,
        "note": "слово мило",
    },
    {
        "word": "игра",
        "owner": "Русланище",
        "owner_tg_id": 137348534,
        "variants": [r"\bигр\w*", r"\bпоигра\w*", r"\bгамар\w*"],
        "labels": ["игра", "играть", "поиграть"],
        "xp": 5,
        "note": "лицензионный сбор",
    },
    {
        # Сомов: «я считаю» — его формулировка, плюс его же «скрипт запущен».
        "word": "я считаю",
        "owner": "Сомов",
        "owner_tg_id": 175773775,
        "variants": [r"\bя\s+считаю\b", r"\bскрипт\s+запущен\w*\b"],
        "labels": ["я считаю", "скрипт запущен"],
        "xp": 5,
        "note": "личное мнение",
    },
    {
        # Кравченко: подпись вытащена из его же сообщений («Вся жизнь борьба»).
        # История чата чистится через 7 дней, поэтому это лучшее, что есть в
        # наличии; слово правится в админке, если найдётся более его.
        "word": "вся жизнь борьба",
        "owner": "Кравченко",
        "owner_tg_id": 397594558,
        "variants": [r"вся\s+жизнь\s*[-—]?\s*борьб\w*", r"\bборьб\w*"],
        "labels": ["вся жизнь борьба", "борьба"],
        "xp": 5,
        "note": "жизненная позиция",
    },
)


def word_key(entry: dict) -> str:
    """Стабильный идентификатор слова — он же дискриминатор суточного кэпа."""
    return str(entry.get("word") or "").strip().lower()


def entry_enabled(entry: dict) -> bool:
    return bool(entry.get("enabled", True)) and bool(word_key(entry))


def chance_for(entry: dict, *, global_chance: int) -> int:
    """Вероятность для конкретного слова: своя, если задана, иначе общая."""
    raw = entry.get("chance")
    if raw is None:
        return global_chance
    try:
        return max(0, min(100, int(raw)))
    except (TypeError, ValueError):
        return global_chance


def matched(entry: dict, text: str) -> bool:
    """Есть ли в тексте хоть одна формулировка слова. Чистая функция (тесты)."""
    for pattern in entry.get("variants") or []:
        try:
            if re.search(str(pattern), text, re.IGNORECASE):
                return True
        except re.error:
            log.warning("game.contraband_bad_variant", variant=str(pattern))
    return False


def announcement(
    entry: dict, *, owner_name: str, author_name: str, xp: int
) -> str:
    """Текст срабатывания. Чистая функция — тестируется без БД."""
    labels = ", ".join(str(x) for x in (entry.get("labels") or []))
    head = f"💰 Слово «{entry.get('word')}» обнаружено"
    if labels:
        head += f" (ловим формулировки: {labels})"
    head += f" — сказал {author_name}."
    tail = f"<b>{owner_name}</b> получает +{xp} XP"
    note = entry.get("note")
    if note:
        tail += f" ({note})"
    return f"{head}\n{tail}."


async def resolve_owner(session: AsyncSession, entry: dict) -> tuple[int | None, str | None]:
    """Кому принадлежит слово: (user_id, отображаемое имя).

    Приоритет — явный `owner_tg_id` (его ставит админка), иначе поиск по имени
    среди участников. «Не нашли» — не повод падать: просто некому начислять,
    и слово не срабатывает (см. `scan`).
    """
    title = entry.get("owner")
    owner_tg = entry.get("owner_tg_id")
    if owner_tg:
        row = await session.execute(
            select(User.id, User.display_name).where(User.telegram_id == int(owner_tg))
        )
        found = row.first()
        if found:
            return int(found[0]), found[1]
    if title:
        # Имя — запасной ключ, поэтому ищем терпимо: сначала точное совпадение
        # без регистра, потом «начинается с», потом «содержит». Иначе «Серж» не
        # находит «Серж-NEO» и слово молча не платит никому.
        for pattern in (str(title), f"{title}%", f"%{title}%"):
            found = await session.scalar(
                select(User.id)
                .where(User.display_name.ilike(pattern))
                .order_by(User.id.asc())
                .limit(1)
            )
            if found is not None:
                return int(found), str(title)
    return None, (str(title) if title else None)


async def configured_words(session: AsyncSession) -> list[dict]:
    """Реестр слов: из админки, а если его там нет — дефолтный из кода."""
    stored = await get_game_contraband_words(session)
    if stored is None:
        return [dict(item) for item in DEFAULT_WORDS]
    return stored


async def scan(
    session: AsyncSession,
    *,
    author_id: int,
    author_name: str,
    text: str,
    at: datetime | None = None,
    rng: random.Random | None = None,
) -> list[str]:
    """Проверить сообщение на контрабанду. Возвращает сработавшие слова.

    Best-effort и без исключений наружу: это часть обработки сообщения, а не
    его смысл. Начисление идёт владельцу слова и один раз в сутки на слово
    (суточный кэп живёт в `xp_grants`, поэтому перезапуск его не сбрасывает).
    """
    if not text:
        return []
    dice = rng or random.Random()
    hit_words: list[str] = []
    try:
        if not await get_game_contraband_enabled(session):
            return []
        global_chance = await get_game_contraband_chance_percent(session)
        cap = await get_game_contraband_daily_cap(session)
        entries = await configured_words(session)
        if not entries:
            return []
        # Резолвим владельцев один раз на сообщение, а не на каждое слово.
        cache: dict[str, tuple[int | None, str | None]] = {}
        for entry in entries:
            if not entry_enabled(entry):
                continue
            word = word_key(entry)
            chance = chance_for(entry, global_chance=global_chance)
            if chance < 100 and dice.randint(1, 100) > chance:
                continue
            if not matched(entry, text):
                continue
            if word not in cache:
                cache[word] = await resolve_owner(session, entry)
            owner_id, owner_name = cache[word]
            if owner_id is None:
                log.warning(
                    "game.contraband_owner_not_found",
                    word=word,
                    owner=entry.get("owner"),
                )
                continue
            xp_value = int(entry.get("xp") or 0)
            granted = await awards.contraband(
                session,
                owner_id=owner_id,
                word=word,
                points=xp_value,
                daily_cap=cap,
                at=at,
            )
            if not granted:
                continue  # суточный кэп уже выбран — молчим, чтобы не спамить
            hit_words.append(word)
            await journal.announce(
                session,
                kind=journal.KIND_CONTRABAND,
                subject_user_id=owner_id,
                text=announcement(
                    entry,
                    owner_name=owner_name or "владелец",
                    author_name=author_name,
                    xp=xp_value,
                ),
            )
    except Exception as exc:  # noqa: BLE001 — контрабанда не стоит сообщения
        log.warning("game.contraband_scan_failed", error=str(exc))
    return hit_words
