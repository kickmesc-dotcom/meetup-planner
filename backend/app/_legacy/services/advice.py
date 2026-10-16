"""GHG8 T3.4: «магический шар» — /advice / #совет / #advice + триггер
«@bot …?».

Бот выдаёт случайный совет из редактируемого пула (admin_config). Рандом
ЧЕСТНЫЙ, без счётчиков использования (требование пользователя 13.06 #1).

Чистые функции (pick_advice / text_has_advice_hashtag / ends_with_question)
вынесены сюда без Telegram-IO — их и тестируем. Хранение/редактирование пула
живёт в admin_config (ключи advice.list / advice.enabled), по образцу
loser_reasons.
"""
from __future__ import annotations

import random
import re

# Дефолтный пул — от дежурных «да/нет» до приколюшек «в нашем стиле». Подхватится,
# пока пользователь не начал кастомизацию через админку (как loser_reasons).
DEFAULT_ADVICE_PHRASES: list[str] = [
    "Да.",
    "Нет.",
    "Точно да.",
    "Однозначно нет.",
    "Возможно.",
    "Не факт.",
    "Сейчас — нет, потом — может быть.",
    "Звёзды говорят да, но звёзды — лохи.",
    "Спроси у Сержа, он плохого не посоветует.",
    "Делай, а там разберёмся.",
    "Лучше не надо, чухан.",
    "Идея огонь, но ты её испортишь.",
    "100%. Вообще без вариантов.",
    "Даже не думай.",
    "Сначала встреться с пацанами, потом решай.",
    "Так точно, мой господин.",
    "Не сегодня.",
    "Шанс есть, но я бы не рисковал.",
    "Бросай монетку — она умнее тебя.",
    "Это вопрос не ко мне, а к твоей совести.",
]

# Хештеги-триггеры (без учёта регистра). Считаем триггером, если в тексте
# присутствует #совет или #advice как отдельный «токен» хештега.
_HASHTAG_RE = re.compile(r"(?:^|\s)#(?:совет|advice)\b", re.IGNORECASE)


def pick_advice(phrases: list[str] | None) -> str | None:
    """Честный равномерный выбор одной фразы. None если пул пуст."""
    pool = [p for p in (phrases or []) if p and p.strip()]
    if not pool:
        return None
    return random.choice(pool)


def text_has_advice_hashtag(text: str | None) -> bool:
    """True если в сообщении упомянут #совет или #advice."""
    if not text:
        return False
    return _HASHTAG_RE.search(text) is not None


def ends_with_question(text: str | None) -> bool:
    """True если осмысленный текст заканчивается на «?».

    Триммим хвостовые пробелы и закрывающие эмодзи/символы НЕ трогаем — нам
    важен именно финальный «?». Несколько «???» тоже считаются вопросом.
    """
    if not text:
        return False
    stripped = text.rstrip()
    return stripped.endswith("?")
