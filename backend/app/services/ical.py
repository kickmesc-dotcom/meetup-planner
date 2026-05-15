"""iCal (RFC 5545) генерация для подписки в системном календаре.

URL подписки: `webcal://{host}/api/meetings/ical/{user_id}.ics?t={token}`.
Token = HMAC(tg_webhook_secret, user_id) — стабилен, можно копировать раз
и больше не трогать. Если секрет поменяется — все ссылки протухнут.
"""
from __future__ import annotations

import hmac
from datetime import datetime, timezone
from hashlib import sha256
from typing import Iterable

from app.config import get_settings
from app.db.models import Meeting

_LINE_LIMIT = 73  # RFC 5545: 75 octets max, минус CRLF + folding space.


def make_token(user_id: int) -> str:
    secret = get_settings().tg_webhook_secret.encode("utf-8")
    return hmac.new(secret, str(user_id).encode("utf-8"), sha256).hexdigest()[:16]


def verify_token(user_id: int, token: str) -> bool:
    return hmac.compare_digest(make_token(user_id), token)


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
