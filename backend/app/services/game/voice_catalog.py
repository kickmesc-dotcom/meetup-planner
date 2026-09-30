"""GHG10 Э14: каталог голосовых заданий.

Задание — творческая задача, которую бот ставит в чат, а участники сдают
ГОЛОСОВЫМИ сообщениями: реплаем на сообщение-задание или боту в личку. Через
окно сбора бот вывешивает сводку «кто какой вариант прислал» и (если включено)
опрос «чей вариант лучше».

Каталог живёт в коде рядом с каталогами ачивок/событий и по тем же причинам:
это содержание, а не тюнинг, и его правят в одном файле. Сдаваемые варианты
хранятся в БД (`game_voice_tasks.text`), поэтому задание доигрывает по тексту,
с которым было создано, даже если каталог потом перепишут.

Формулировки — нарочито рофляные (как в случайных событиях): задача не «опросить
людей», а вытащить смешные голосовые.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.game.config import (
    VOICE_REWARD,
    VOICE_TASK_COOLDOWN_DAYS,
    VOICE_TASK_WINDOW_MINUTES,
)


@dataclass(frozen=True)
class VoiceTask:
    """Одно голосовое задание.

    `window_minutes` — сколько идёт приём (часы, не «лимит в час»).
    `cooldown_days` — сколько задание отдыхает после использования, чтобы одни и
    те же шутки не сыпались подряд.
    """

    code: str
    title: str
    text: str
    window_minutes: int = VOICE_TASK_WINDOW_MINUTES
    reward: int = VOICE_REWARD
    cooldown_days: int = VOICE_TASK_COOLDOWN_DAYS


TASKS: tuple[VoiceTask, ...] = (
    VoiceTask(
        code="duck",
        title="Кряканье утки",
        text="🦆 Задание: <b>запиши голосовуху, как крякает утка</b>. Чем натуральнее — тем лучше.",
    ),
    VoiceTask(
        code="lullaby",
        title="Колыбельная чухану",
        text=(
            "🎵 Задание: <b>спой колыбельную для чухана недели</b>. "
            "Одна строчка голосом — уже зачёт."
        ),
    ),
    VoiceTask(
        code="villain",
        title="Речь злодея",
        text=(
            "🦹 Задание: <b>произнеси угрозу как злодей из фильма</b>. "
            "Драматично, с паузами."
        ),
    ),
    VoiceTask(
        code="sob",
        title="Рыдания",
        text=(
            "😭 Задание: <b>запиши, как ты безутешно рыдаешь</b>, потому что "
            "проиграл в рулетку лоха."
        ),
    ),
    VoiceTask(
        code="imitate",
        title="Пародия на участника",
        text=(
            "🎭 Задание: <b>спародируй голосом любого участника чата</b>. "
            "Никаких обид — только кринж."
        ),
    ),
    VoiceTask(
        code="anthem",
        title="Гимн чата",
        text=(
            "🏆 Задание: <b>спой гимн нашего чата</b> — хотя бы две строки, "
            "мотив на твой вкус."
        ),
    ),
)

TASKS_BY_CODE: dict[str, VoiceTask] = {t.code: t for t in TASKS}


def task_codes() -> tuple[str, ...]:
    return tuple(t.code for t in TASKS)
