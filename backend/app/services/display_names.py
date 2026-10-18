"""Отображаемые имена: сборка из Telegram и починка битых записей.

Зачем это отдельным модулем. В боевой базе у части старых профилей
`users.display_name` — это не имя, а «ромбики»: строка с U+FFFD (replacement
character). Такие символы появляются, когда UTF-8 байты уже декодировали с
`errors="replace"`: исходный текст потерян, и «починить» его обратным
декодированием нельзя. Единственный надёжный источник — подписанные данные
Telegram (`initData`), поэтому имя берём оттуда и перезаписываем испорченное.

Правила простые и намеренно не «умные»:

* битое имя никогда не показываем как есть — лучше подставить запасное;
* известное имя (из подписи владельца, из Telegram) важнее пустого;
* чистое имя пользователя не трогаем: его может править сам человек.
"""

from __future__ import annotations

# U+FFFD — символ замены. Появление хотя бы одного означает потерю данных.
REPLACEMENT_CHAR = "\ufffd"


def is_corrupted(value: str | None) -> bool:
    """Похоже ли имя на последствие неудачного декодирования."""
    return value is not None and REPLACEMENT_CHAR in value


def has_text(value: str | None) -> bool:
    """Непустое и не испорченное значение — годится в подпись."""
    return bool(value) and bool(value.strip()) and not is_corrupted(value)  # type: ignore[union-attr]


def compose_display_name(
    first_name: str | None,
    last_name: str | None,
    username: str | None = None,
    *,
    fallback_id: int | None = None,
) -> str:
    """Имя для нового профиля: имя+фамилия, иначе username, иначе «Сотрудник N».

    Битые части пропускаем: если Telegram прислал «ромбики», это не имя.
    """
    parts = [part.strip() for part in (first_name, last_name) if has_text(part)]
    candidate = " ".join(parts)
    if candidate:
        return candidate[:120]
    if has_text(username):
        return str(username).strip()[:120]
    return f"Сотрудник {fallback_id}" if fallback_id else "Сотрудник"


__all__ = [
    "REPLACEMENT_CHAR",
    "compose_display_name",
    "has_text",
    "is_corrupted",
]
