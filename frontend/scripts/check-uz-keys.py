"""Проверка словаря узбекского: дубликаты ключей и пустые значения.

Зачем отдельный скрипт, а не только тест. В `uz.guard.test.ts` проверяется, что
ключи узбекского есть в английском, что нет кириллицы и что плейсхолдеры
совпадают. Но **дубликат ключа** в объекте JS — законный код: второе значение
молча перекрывает первое, и страж этого не видит, потому что `Object.keys`
возвращает уникальные имена. При ручном переводе экрана за экраном это самый
вероятный способ испортить строку — и самый незаметный.

Запуск: `python scripts/check-uz-keys.py` из `frontend/`.
"""

from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FILE = HERE / "src" / "i18n" / "content.uz.ts"

KEY_RE = re.compile(r'^\s{2}"((?:[^"\\]|\\.)*)":', re.M)
VALUE_RE = re.compile(r'^\s{2}"(?:[^"\\]|\\.)*":\s*"((?:[^"\\]|\\.)*)"', re.M)


def main() -> int:
    source = FILE.read_text(encoding="utf-8")
    keys = KEY_RE.findall(source)
    duplicates = [key for key, count in collections.Counter(keys).items() if count > 1]
    empty = [key for key, value in zip(keys, VALUE_RE.findall(source)) if not value.strip()]

    print(f"ключей: {len(keys)}")
    for key in duplicates:
        print(f"  дубликат: {key}")
    for key in empty:
        print(f"  пустое значение: {key}")
    return 1 if duplicates or empty else 0


if __name__ == "__main__":
    raise SystemExit(main())
