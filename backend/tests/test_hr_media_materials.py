"""Фото и материалы: чистые правила без БД.

Проверяем именно те места, где раньше была тихая поломка:

* тип файла по сигнатуре (переименованный `.txt` не должен стать «фото»);
* подпись ссылки (по чужому id фото не открыть);
* разбор ссылок Google Sheets и CSV — на них держится «динамически
  подтягивается содержимое»;
* `is_stale` не падает на naive-дате из SQLite.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("ADMIN_TG_IDS", "")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from app.services import hr_materials, hr_media  # noqa: E402

# 1×1 PNG из `hr_media.png_placeholder`; JPEG — минимальный заголовок с SOF0.
PNG = hr_media.png_placeholder()
JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xc0\x00\x11\x08\x00\x10\x00\x20\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    b"\xff\xd9"
)


def test_sniff_accepts_real_images_and_rejects_text() -> None:
    assert hr_media.sniff_mime(PNG) == "image/png"
    assert hr_media.sniff_mime(JPEG) == "image/jpeg"
    assert hr_media.sniff_mime(b"RIFF1234WEBPVP8 ") == "image/webp"
    assert hr_media.sniff_mime(b"GIF89a\x01\x00\x01\x00") == "image/gif"
    assert hr_media.sniff_mime(b"<html>login</html>") is None


def test_image_size_reads_png_and_jpeg() -> None:
    assert hr_media.image_size(PNG, "image/png") == (1, 1)
    assert hr_media.image_size(JPEG, "image/jpeg") == (32, 16)


def test_media_signature_is_per_id_and_kind() -> None:
    signed = hr_media.sign("blob", 7)
    assert hr_media.verify("blob", 7, signed)
    assert not hr_media.verify("blob", 8, signed)
    assert not hr_media.verify("tgphoto", 7, signed)
    assert not hr_media.verify("blob", 7, None)


def test_media_urls_are_signed() -> None:
    blob_url = hr_media.url_for(12)
    assert blob_url.startswith("/api/media/12?s=")
    photo_url = hr_media.photo_url(34)
    assert photo_url.startswith("/api/media/tg/34?s=")


def test_parse_sheet_understands_owner_links() -> None:
    sheet, gid = hr_materials.parse_sheet(
        "https://docs.google.com/spreadsheets/d/1ELeiAoEd5Dm6piTIXmFXjmgBEyOWORSLWi_mjH1pmag"
        "/edit?pli=1&gid=1840299687#gid=1840299687"
    )
    assert sheet == "1ELeiAoEd5Dm6piTIXmFXjmgBEyOWORSLWi_mjH1pmag"
    assert gid == "1840299687"


def test_export_and_gviz_urls_include_gid() -> None:
    assert "format=csv" in hr_materials.export_url("abc", "42")
    assert "gid=42" in hr_materials.export_url("abc", "42")
    assert "tqx=out:csv" in hr_materials.gviz_url("abc", None)


def test_parse_csv_trims_and_pads() -> None:
    rows = hr_materials.parse_csv(
        "День,Смена,Кто\r\n"
        "20.10,09:00,Аня\r\n"
        "\r\n"
        "21.10,09:00\r\n"
    )
    assert rows.columns == 3
    assert rows.rows[0] == ["День", "Смена", "Кто"]
    assert rows.rows[1] == ["20.10", "09:00", "Аня"]
    # Пустая строка выброшена, короткая — выровнена по ширине.
    assert rows.rows[2] == ["21.10", "09:00", ""]


def test_is_stale_handles_naive_and_aware() -> None:
    class Fake:
        synced_at = None

    source = Fake()
    assert hr_materials.is_stale(source) is True

    source.synced_at = datetime.now(UTC) - timedelta(minutes=1)
    assert hr_materials.is_stale(source) is False

    # SQLite отдаёт naive datetime (в UTC, мы пишем `datetime.now(UTC)`).
    source.synced_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
    assert hr_materials.is_stale(source) is True



class _FakeSession:
    """Мини-сессия: проверяем логику дедупликации без диалекта SQL.

    SQLite не умеет `BIGINT PRIMARY KEY` с автоинкрементом (это особенность
    диалекта, а не наша), поэтому вместо реальной таблицы подставляем объект с
    теми же тремя вызовами, которые использует `store_bytes`.
    """

    def __init__(self) -> None:
        self.rows: list[object] = []
        self.flushed = 0

    async def scalar(self, _stmt):  # noqa: ANN001
        return self.rows[-1] if self.rows else None

    def add(self, obj) -> None:  # noqa: ANN001
        obj.id = len(self.rows) + 1
        self.rows.append(obj)

    async def flush(self) -> None:
        self.flushed += 1


async def test_store_bytes_dedupes_and_rejects_non_images() -> None:
    """Повторная отправка того же снимка — тот же блоб; текст не принимается."""
    import pytest

    session = _FakeSession()
    first = await hr_media.store_bytes(session, PNG)
    second = await hr_media.store_bytes(session, PNG)
    assert first is second
    assert first.id == 1
    assert first.mime == "image/png"
    assert (first.width, first.height) == (1, 1)
    assert first.size == len(PNG)
    with pytest.raises(hr_media.MediaError) as exc:
        await hr_media.store_bytes(session, b"not an image")
    assert str(exc.value) == "not_an_image"
