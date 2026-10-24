# -*- coding: utf-8 -*-
"""Какие строки `tx("…")` ещё без английского перевода.

Страж `coverage.test.ts` знает то же самое, но отвечает через падение всего
прогона vitest. Этот скрипт отвечает списком — им удобно закрывать экран:
обернул строки, запустил, дописал словарь, снова запустил.

    python tools/i18n-missing.py                     # весь src
    python tools/i18n-missing.py src/features/admin  # только папка
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
CONTENT = SRC / "i18n" / "content.ts"

# Ключ словаря — строка в кавычках в начале записи (значение может быть на
# следующей строке, поэтому ищем только ключ).
KEY = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*:', re.M)
TX = re.compile(r'\btx\(\s*(?:locale\s*,\s*)?"((?:[^"\\]|\\.)*)"')
TX_TEMPLATE = re.compile(r'\btx\(\s*(?:locale\s*,\s*)`([^`$]*)`')


def known() -> set[str]:
    return {m.group(1) for m in KEY.finditer(CONTENT.read_text(encoding="utf-8"))}


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return "\n".join(
        "" if line.strip().startswith(("//", "*")) else line
        for line in src.splitlines()
    )


def main(argv: list[str]) -> int:
    if argv:
        given = Path(argv[0])
        target = given if given.is_absolute() else ROOT / given
        if not target.exists():
            # Короткая форма — как в командах vitest: `src/features/...`.
            target = ROOT / "frontend" / given
    else:
        target = SRC
    files = (
        [target]
        if target.is_file()
        else [p for p in target.rglob("*") if p.suffix in {".ts", ".tsx"}]
    )
    have = known()
    missing: dict[str, set[str]] = {}
    for path in files:
        if path.name.endswith(("content.ts", "messages.ts")) or ".test." in path.name:
            continue
        code = strip_comments(path.read_text(encoding="utf-8"))
        keys = TX.findall(code) + TX_TEMPLATE.findall(code)
        gaps = {key for key in keys if key not in have}
        if gaps:
            missing[str(path.relative_to(SRC)).replace("\\", "/")] = gaps
    total = sum(len(v) for v in missing.values())
    for name, gaps in sorted(missing.items()):
        print(f"\n{name}: {len(gaps)}")
        for key in sorted(gaps):
            print(f'  "{key}"')
    print(f"\nвсего без перевода: {total} в {len(missing)} файлах")
    return 1 if total else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — печать не должна ронять проверку
        pass
    raise SystemExit(main(sys.argv[1:]))
