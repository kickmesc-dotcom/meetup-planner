"""Фотоотчёты: приём снимка из мини-аппа, хранение байтов и подписанные ссылки.

Почему так, а не «как раньше»: в HR-ядре фотография жила только как Telegram
`file_id`. Мини-апп не может показать такой файл — у `<img>` нет заголовка с
подписью Telegram, а отдавать токен бота в браузер нельзя. Из-за этого фото
«отправлялось, но никуда не шло», а пункт чек-листа невозможно было закрыть,
не выходя в чат.

Теперь:

* снимок сжимается на клиенте и приходит multipart'ом на `POST /api/media`;
* байты лежат в `media_blobs` (переживают рестарт контейнера, в отличие от
  локального диска HF Space);
* отдаются публично по `/api/media/{id}?s=<подпись>` — ссылка неперебираемая,
  но работает в `<img>` без заголовков;
* фото из чата при первом показе скачивается из Telegram и кешируется в тот же
  блоб, поэтому старые отчёты тоже становятся видимыми.

Ограничения намеренно жёсткие: только изображения, до 8 МБ, тип проверяется по
сигнатуре файла, а не по расширению.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import struct

import structlog
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.hr_models import MediaBlob, TaskPhoto

log = structlog.get_logger()

MAX_BYTES = 8 * 1024 * 1024
# Telegram отдаёт снимки как image/jpeg; webp/PNG приходят из галереи.
ALLOWED = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}


class MediaError(Exception):
    """Понятный клиенту отказ: код, а не текст."""


def _key() -> bytes:
    """Ключ подписи. Отдельного секрета в конфиге нет — берём токен бота.

    Наружу он не уходит: в ссылке только HMAC, восстановить ключ нельзя.
    """
    return get_settings().bot_token.encode("utf-8")


def sign(kind: str, value: int) -> str:
    payload = f"{kind}:{value}".encode()
    return hmac.new(_key(), payload, hashlib.sha256).hexdigest()[:32]


def verify(kind: str, value: int, signature: str | None) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(sign(kind, value), signature)


def url_for(blob_id: int) -> str:
    return f"/api/media/{blob_id}?s={sign('blob', blob_id)}"


def photo_url(photo_id: int) -> str:
    """Публичная ссылка на фото из чата, ещё не снятое в блоб."""
    return f"/api/media/tg/{photo_id}?s={sign('tgphoto', photo_id)}"


def sniff_mime(data: bytes) -> str | None:
    """Тип по сигнатуре: расширению и `Content-Type` не верим."""
    for mime, magics in ALLOWED.items():
        for magic in magics:
            if data.startswith(magic):
                if mime == "image/webp" and data[8:12] != b"WEBP":
                    continue
                return mime
    return None


def image_size(data: bytes, mime: str) -> tuple[int | None, int | None]:
    """Ширина/высота без внешних зависимостей (JPEG, PNG, WebP).

    Нужна только для аккуратной вёрстки превью: если не распознали — вернём
    `(None, None)`, браузер сам разберётся с пропорциями.
    """
    try:
        if mime == "image/png":
            width, height = struct.unpack(">II", data[16:24])
            return int(width), int(height)
        if mime == "image/gif":
            width, height = struct.unpack("<HH", data[6:10])
            return int(width), int(height)
        if mime == "image/webp":
            if data[12:16] == b"VP8X":
                width = int.from_bytes(data[24:27], "little") + 1
                height = int.from_bytes(data[27:30], "little") + 1
                return width, height
            return None, None
        if mime == "image/jpeg":
            pos = 2
            while pos + 9 < len(data):
                if data[pos] != 0xFF:
                    pos += 1
                    continue
                marker = data[pos + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                    height, width = struct.unpack(">HH", data[pos + 5 : pos + 9])
                    return int(width), int(height)
                if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                    pos += 2
                    continue
                length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
                pos += 2 + length
    except (struct.error, IndexError, ValueError):
        return None, None
    return None, None


async def store_bytes(
    session: AsyncSession,
    data: bytes,
    *,
    mime: str | None = None,
    telegram_file_id: str | None = None,
) -> MediaBlob:
    """Положить снимок в БД. Повторная отправка того же файла — тот же блоб."""
    if not data:
        raise MediaError("empty_file")
    if len(data) > MAX_BYTES:
        raise MediaError("file_too_large")
    detected = sniff_mime(data)
    if detected is None:
        raise MediaError("not_an_image")
    digest = hashlib.sha256(data).hexdigest()
    blob = await session.scalar(select(MediaBlob).where(MediaBlob.sha256 == digest))
    if blob is not None:
        if telegram_file_id and not blob.telegram_file_id:
            blob.telegram_file_id = telegram_file_id
        return blob
    width, height = image_size(data, detected)
    blob = MediaBlob(
        sha256=digest,
        mime=mime if mime in ALLOWED else detected,
        size=len(data),
        width=width,
        height=height,
        data=data,
        telegram_file_id=telegram_file_id,
    )
    session.add(blob)
    await session.flush()
    return blob


async def store_upload(session: AsyncSession, upload: UploadFile) -> MediaBlob:
    """Принять снимок с ограничением по размеру ВО ВРЕМЯ чтения.

    Раньше здесь стоял `await upload.read()` без ограничения, а правило «до 8 МБ»
    проверялось позже, в `store_bytes`, — то есть уже после того, как тело целиком
    легло в память или во временный файл. Теперь чтение обрывается на первом же
    куске, который выводит нас за предел: загрузка на гигабайт больше не может
    занять диск контейнера (ауд. 26.10.2026, S-2). Отдельный предохранитель по
    `Content-Length` живёт в `app/api/guards.py`; здесь — защита в глубину на
    случай chunked-тела, у которого длины нет вовсе.
    """
    raw = await read_capped(upload)
    return await store_bytes(session, raw, mime=upload.content_type)


async def read_capped(upload: UploadFile, limit: int = MAX_BYTES) -> bytes:
    """Прочитать тело порциями, оборвавшись на превышении предела."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise MediaError("file_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


async def cache_telegram_photo(
    session: AsyncSession, file_id: str
) -> MediaBlob | None:
    """Скачать фото из Telegram и запомнить байты, чтобы апп мог его показать.

    Ошибки сети не ломают рабочий поток: фото уже принято (`TaskPhoto`), просто
    в приложении оно появится позже — при первом открытии сработает ленивый
    кеш в `GET /api/media/tg/{photo_id}`.
    """
    from app.bot.dispatcher import get_bot
    from app.services.avatars import fetch_avatar_bytes

    existing = await session.scalar(
        select(MediaBlob).where(MediaBlob.telegram_file_id == file_id)
    )
    if existing is not None:
        return existing
    fetched = await fetch_avatar_bytes(get_bot(), file_id)
    if fetched is None:
        return None
    data, _content_type = fetched
    try:
        return await store_bytes(session, data, telegram_file_id=file_id)
    except MediaError as exc:
        log.info("media.telegram_cache_skipped", reason=str(exc))
        return None


async def blob_or_404(session: AsyncSession, blob_id: int) -> MediaBlob:
    blob = await session.get(MediaBlob, blob_id)
    if blob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="media_not_found")
    return blob


async def ensure_task_photo_blob(
    session: AsyncSession, photo: TaskPhoto
) -> MediaBlob | None:
    """Блоб для фотоотчёта: уже загруженный или снятый с Telegram по file_id."""
    if photo.media_id is not None:
        blob = await session.get(MediaBlob, photo.media_id)
        if blob is not None:
            return blob
    if not photo.file_id:
        return None
    blob = await cache_telegram_photo(session, photo.file_id)
    if blob is not None and photo.media_id != blob.id:
        photo.media_id = blob.id
        await session.commit()
    return blob


async def ensure_checklist_photo_blob(
    session: AsyncSession, completion_id: int
) -> MediaBlob | None:
    """Блоб для фото пункта чек-листа (в том числе старого, из чата)."""
    from app.db.hr_models import ChecklistCompletion

    completion = await session.get(ChecklistCompletion, completion_id)
    if completion is None:
        return None
    if completion.photo_media_id is not None:
        blob = await session.get(MediaBlob, completion.photo_media_id)
        if blob is not None:
            return blob
    if not completion.photo_file_id:
        return None
    blob = await cache_telegram_photo(session, completion.photo_file_id)
    if blob is not None:
        completion.photo_media_id = blob.id
        await session.commit()
    return blob


def png_placeholder() -> bytes:
    """1×1 прозрачный PNG — на случай, если кеш не удался, но нужен ответ."""
    return io.BytesIO(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c6360000002000154a24f5a0000000049454e44ae426082"
        )
    ).read()
