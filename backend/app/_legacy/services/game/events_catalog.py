"""GHG10 Э13: каталог случайных событий («которые именно требуют действия»).

Заказчик просил именно это:

    Первый, кто напишет «я», получает 50 XP. или (маму любишь? да — 10 хп,
    нет — 50 хп) — какие-то такие нарочито рофляные вопросы или призывы к
    действию. Скинь любимый мем в течение двух часов (+50 хп).

Каталог живёт в коде рядом с каталогом ачивок и по тем же причинам: это
содержание, а не тюнинг, его правят в одном файле. Отличие от ачивок — промпт
хранится в БД вместе со своими матчерами (`game_prompts.answers`): событие
может «доигрывать» дольше одного релиза, и старый открытый промпт обязан
матчиться по правилам, с которыми был создан, даже если каталог перепишут.

Матчеры — регулярки (регистронезависимо, по `strip()`-тексту сообщения).
`media=True` означает «засчитывается любое медиа», такие ответы нужны для
призывов «скинь мем» — там текст не требуется.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Answer:
    """Что засчитывается за ответ и сколько за него дают."""

    matcher: str
    xp: int
    reply: str
    media: bool = False
    # Э21: человеческая подпись варианта для мини-аппа. Когда она есть — вопрос
    # можно ответить КНОПКОЙ в ленте («да»/«нет»), а не только текстом в чате.
    # `None` означает «вариант без кнопки» (свободный ответ).
    label: str | None = None


@dataclass(frozen=True)
class Prompt:
    """Призыв к действию: текст в чат, варианты ответа и срок жизни."""

    code: str
    text: str
    answers: tuple[Answer, ...]
    ttl_minutes: int
    # Сколько дней промпт не повторяем после использования (чтобы шутки не
    # затирались: «первый, кто напишет я» три дня подряд — уже не смешно).
    cooldown_days: int = 7
    # Э18: нужен ли поясняющий фоллоу-пост. У вопросов («маму любишь?»,
    # «признайся») правила неочевидны — фоллоу обязателен. У очевидных призывов
    # («скинь мем», «первый, кто напишет я») он избыточен и работает как спам.
    needs_rules: bool = True


PROMPTS: tuple[Prompt, ...] = (
    Prompt(
        code="first_me",
        text="⚡️ <b>Первый</b>, кто напишет «я», получает <b>50 XP</b>.",
        answers=(
            Answer(
                matcher=r"^я\s*[!?.…]*$",
                xp=50,
                reply="⚡️ <b>{name}</b> написал «я» первым: +{xp} XP.",
            ),
        ),
        ttl_minutes=30,
        needs_rules=False,
    ),
    Prompt(
        code="mom_love",
        text=(
            "🫶 <b>Маму любишь?</b>\n"
            "Напиши «да» — 10 XP. Напиши «нет» — 50 XP."
        ),
        answers=(
            Answer(
                matcher=r"^да\s*[!?.…]*$",
                xp=10,
                reply="🫶 <b>{name}</b>: +{xp} XP. Хоть не соврал.",
                label="да",
            ),
            Answer(
                matcher=r"^нет\s*[!?.…]*$",
                xp=50,
                reply="🫶 <b>{name}</b>: +{xp} XP и пожизненный кринж.",
                label="нет",
            ),
        ),
        ttl_minutes=120,
    ),
    Prompt(
        code="confess",
        text=(
            "🙊 Признайся в чём угодно одним сообщением (от 12 символов) — "
            "<b>+30 XP</b>. Час на подумать."
        ),
        answers=(
            Answer(
                matcher=r"^.{12,}$",
                xp=30,
                reply="🙊 <b>{name}</b> признался и получил +{xp} XP.",
            ),
        ),
        ttl_minutes=60,
    ),
    Prompt(
        code="meme",
        text=(
            "🖼 Скинь любимый мем или ссылку на него в течение двух часов — "
            "<b>+50 XP</b>."
        ),
        answers=(
            Answer(
                matcher=r".*",
                xp=50,
                reply="🖼 <b>{name}</b> принёс годноту: +{xp} XP.",
                media=True,
            ),
            Answer(
                matcher=r"^https?://\S+$",
                xp=50,
                reply="🖼 <b>{name}</b> принёс годноту ссылкой: +{xp} XP.",
            ),
        ),
        ttl_minutes=120,
        needs_rules=False,
    ),
    Prompt(
        code="self_roast",
        text=(
            "🔥 <b>Первый</b>, кто признает себя чуханом, получает <b>40 XP</b>. "
            "Слово — и ты в игре."
        ),
        answers=(
            Answer(
                matcher=r"чухан\w*",
                xp=40,
                reply="🔥 <b>{name}</b> признал очевидное: +{xp} XP.",
            ),
        ),
        ttl_minutes=60,
        needs_rules=False,
    ),
)

PROMPTS_BY_CODE: dict[str, Prompt] = {p.code: p for p in PROMPTS}


def prompt_codes() -> tuple[str, ...]:
    return tuple(p.code for p in PROMPTS)


def serialize_answers(prompt: Prompt) -> list[dict]:
    """Ответы промпта в JSONB-форму для `game_prompts.answers`."""
    return [
        {
            "matcher": a.matcher,
            "xp": a.xp,
            "reply": a.reply,
            "media": a.media,
            # Э21: подпись для кнопки в мини-аппе (None — свободный ответ).
            "label": a.label,
        }
        for a in prompt.answers
    ]
