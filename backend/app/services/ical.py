"""iCal (RFC 5545) генерация для подписки в системном календаре.

URL подписки: `webcal://{host}/api/meetings/ical/{user_id}.ics?t={token}`.
Token = HMAC(tg_webhook_secret, user_id) — стабилен, можно копировать раз
и больше не трогать. Если секрет поменяется — все ссылки протухнут.

Про длину подписи (аудит 26.10.2026, S-10). Раньше токен обрезался до 16
hex-символов, то есть 64 бита, и жил вечно: ссылка попадает в логи почтовых
клиентов и прокси, а отозвать её нельзя иначе как сменой секрета вебхука (а это
ломает и сам вебхук, и все прочие подписки). Теперь новые ссылки подписаны
32 символами (128 бит), а ссылки прежней длины **принимаются** — уже
подключённые календари не должны отвалиться.
"""
from __future__ import annotations

import hmac
from datetime import datetime, timezone
from hashlib import sha256
from typing import Iterable

from app.config import get_settings
from app.db.models import Meeting

_LINE_LIMIT = 73  # RFC 5545: 75 octets max, минус CRLF + folding space.
# Сколько символов подписи отдаём сейчас и сколько принимаем как «старый формат».
TOKEN_LENGTH = 32
LEGACY_TOKEN_LENGTH = 16


def _signature(user_id: int, length: int) -> str:
    secret = get_settings().tg_webhook_secret.encode("utf-8")
    digest = hmac.new(secret, str(user_id).encode("utf-8"), sha256).hexdigest()
    return digest[:length]


def make_token(user_id: int) -> str:
    """Подпись ссылки: 128 бит. Меняется вместе с секретом вебхука."""
    return _signature(user_id, TOKEN_LENGTH)


def verify_token(user_id: int, token: str) -> bool:
    """Проверить подпись. Принимаем и новый формат, и прежний 64-битный.

    Сравнение — `compare_digest` и без ранних выходов: обе длины проверяются
    всегда, иначе по времени ответа было бы видно, какой формат угадан.
    """
    given = (token or "").strip().encode("utf-8")
    current_ok = hmac.compare_digest(_signature(user_id, TOKEN_LENGTH).encode(), given)
    legacy_ok = hmac.compare_digest(
        _signature(user_id, LEGACY_TOKEN_LENGTH).encode(), given
    )
    return current_ok or legacy_ok


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    if len(line) <= _LINE_LIMIT:
        return line
    chunks = [line[:_LINE_LIMIT]]
    rest = line[_LINE_LIMIT:]
    while rest:
        chunks.append(" " + rest[: _LINE_LIMIT - 1])
        rest = rest[_LINE_LIMIT - 1 :]
    return "\r\n".join(chunks)


def _fmt_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def render_calendar(meetings: Iterable[Meeting], *, calendar_name: str) -> bytes:
    now = _fmt_utc(datetime.now(timezone.utc))
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//meetup-planner//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        _fold(f"X-WR-CALNAME:{_escape(calendar_name)}"),
        "X-WR-TIMEZONE:Europe/Moscow",
    ]
    for m in meetings:
        if m.status == "cancelled":
            continue
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:meeting-{m.id}@meetup-planner",
                f"DTSTAMP:{now}",
                f"DTSTART:{_fmt_utc(m.starts_at)}",
                f"DTEND:{_fmt_utc(m.ends_at)}",
                _fold(f"SUMMARY:{_escape(m.title)}"),
            ]
        )
        if m.location:
            lines.append(_fold(f"LOCATION:{_escape(m.location)}"))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")
