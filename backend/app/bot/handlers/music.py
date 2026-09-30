"""Э15: приём треков в музыкальную предложку (только личка).

Задание H.7: «в течение недели участники могут накидывать боту в личку
музыкальные произведения (в идеале прямо вайлом мп3 внутри телеги; либо
ссылкой)». Поэтому хендлер живёт в личке и принимает аудиофайл или ссылку.
Голосовые НЕ трогаем — они принадлежат заданиям (`voice_tasks`).

Хранится только `file_id`/ссылка; файлы не качаем (слабый хост).
"""
from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from app.db.base import get_sessionmaker
from app.services.game import music
from app.services.game.config import MUSIC_PER_USER_WEEKLY

log = structlog.get_logger()
router = Router()

_AUDIO_EXT = (".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus", ".aac")


def _looks_like_audio_document(message: Message) -> bool:
    doc = message.document
    if doc is None:
        return False
    mime = (doc.mime_type or "").lower()
    if mime.startswith("audio/"):
        return True
    name = (doc.file_name or "").lower()
    return name.endswith(_AUDIO_EXT)


async def _answer(message: Message, res: music.TrackResult, *, title: str | None) -> None:
    try:
        if res.status == music.OK:
            label = f" «{title}»" if title else ""
            await message.answer(
                f"🎧 Принял{label}. На этой неделе у тебя "
                f"{res.week_count}/{MUSIC_PER_USER_WEEKLY}.",
                parse_mode="HTML",
            )
        elif res.status == music.LIMIT:
            await message.answer(
                f"🎧 На эту неделю лимит исчерпан ({MUSIC_PER_USER_WEEKLY}). "
                "Кидай ещё после следующей подборки."
            )
        elif res.status == music.DUPLICATE:
            await message.answer("🎧 Этот трек ты уже присылал — он в пуле.")
        elif res.status == music.UNKNOWN_USER:
            await message.answer("Ты не в списке участников — попроси админа добавить.")
        else:
            await message.answer("🎧 Не понял трек. Кинь аудиофайл или ссылку.")
    except Exception as exc:  # noqa: BLE001
        log.warning("music.answer_failed", error=str(exc))


@router.message(Command("music"), F.chat.type == ChatType.PRIVATE)
async def on_music_help(message: Message) -> None:
    await message.answer(
        "🎧 <b>Музыкальная предложка</b>\n"
        "Кидай мне в личку треки — аудиофайлом или ссылкой. Раз в неделю я "
        f"выкладываю подборку в чат. Лимит: {MUSIC_PER_USER_WEEKLY} трека в неделю.",
        parse_mode="HTML",
    )


@router.message(F.audio, F.chat.type == ChatType.PRIVATE)
async def on_private_audio(message: Message) -> None:
    if message.from_user is None or message.audio is None:
        return
    audio = message.audio
    title = audio.title or audio.file_name
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            res = await music.add_track(
                session,
                telegram_id=message.from_user.id,
                kind="audio",
                file_id=audio.file_id,
                title=title,
                performer=audio.performer,
                duration=audio.duration,
                at=message.date,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("music.audio_failed", error=str(exc))
        return
    await _answer(message, res, title=title)


@router.message(F.document, F.chat.type == ChatType.PRIVATE)
async def on_private_audio_document(message: Message) -> None:
    if message.from_user is None or not _looks_like_audio_document(message):
        return
    doc = message.document
    assert doc is not None  # гарантировано `_looks_like_audio_document`
    title = doc.file_name
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            res = await music.add_track(
                session,
                telegram_id=message.from_user.id,
                kind="audio",
                file_id=doc.file_id,
                title=title,
                at=message.date,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("music.document_failed", error=str(exc))
        return
    await _answer(message, res, title=title)


@router.message(F.text, F.chat.type == ChatType.PRIVATE)
async def on_private_link(message: Message) -> None:
    if message.from_user is None or not music.looks_like_link(message.text):
        return
    url = (message.text or "").strip()
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            res = await music.add_track(
                session,
                telegram_id=message.from_user.id,
                kind="link",
                url=url,
                title=url,
                at=message.date,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("music.link_failed", error=str(exc))
        return
    await _answer(message, res, title=None)
