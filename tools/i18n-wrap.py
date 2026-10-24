"""Механическая обёртка русских подписей в `tx("…")`.

Зачем скрипт, а не руки: подписей в остатке ~700, и 80% из них — обычный
текст в разметке (`>Принять<`) или подпись-атрибут (`aria-label="Назад"`).
Руками это часы однотипной правки и гарантированные пропуски.

Что делает `wrap`:
  * JSX-текст с кириллицей → `>{tx("…")}<` (пробелы внутри схлопываются,
    как их схлопнул бы JSX: `>  Текст  <` и `>Текст<` дают одно и то же);
  * подписи-атрибуты (`placeholder`, `aria-label`, `title`, `label`, `alt`)
    → `attr={tx("…")}`;
  * добавляет `import { useTx } from "@/i18n";`, если его нет;
  * вставляет `const { tx } = useTx();` в начало каждой функции-компонента
    (имя с большой буквы) — только если в ней ещё нет `useTx()`.

Что скрипт НЕ делает (правится руками, он печатает это списком):
  * текст с подстановками (`Ждут приёмки: {n}`) — его надо превратить в
    `tx("Ждут приёмки: {count}", { count: n })`;
  * русские строки в константах-таблицах (`STATUS_LABEL`) и в `showAlert(...)`;
  * `toLocaleString("ru-RU")` — даты переводятся на локаль отдельно.

Запуск:
    python tools/i18n-wrap.py wrap src/features/hr/KpiCard.tsx
    python tools/i18n-wrap.py scan src/features/hr/KpiCard.tsx
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CYRILLIC = "А-Яа-яЁё"
HAS_CY = re.compile(f"[{CYRILLIC}]")
JSX_TEXT = re.compile(f">([^<>{{}}]*)<")
ATTR = re.compile(
    r"(placeholder|aria-label|title|label|alt)\s*=\s*\"([^\"]*)\"",
)
IMPORT_LINE = re.compile(r'^import .*?;\s*$', re.MULTILINE)


def strip_comments(src: str) -> str:
    """Комментарии заменяются пробелами: смещения остаются прежними."""
    out = list(src)

    def blank(start: int, end: int) -> None:
        for i in range(start, end):
            if out[i] not in "\r\n":
                out[i] = " "

    for match in re.finditer(r"/\*[\s\S]*?\*/", src):
        blank(match.start(), match.end())
    for match in re.finditer(r"(?m)^\s*//[^\n]*", src):
        blank(match.start(), match.end())
    return "".join(out)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def scan(src: str) -> list[str]:
    code = strip_comments(src)
    found: list[str] = []
    for match in JSX_TEXT.finditer(code):
        text = normalize(match.group(1))
        if text and HAS_CY.search(text):
            found.append(f"text: {text}")
    for match in ATTR.finditer(code):
        if HAS_CY.search(match.group(2)):
            found.append(f"attr {match.group(1)}: {match.group(2)}")
    return found


def leftovers(src: str) -> list[str]:
    """Русские строки, которые остались вне `tx(...)` — для ручной правки."""
    code = strip_comments(src)
    rows: list[str] = []
    for line_no, line in enumerate(code.splitlines(), 1):
        for match in re.finditer(r'"([^"\n]*)"', line):
            value = match.group(1)
            if not HAS_CY.search(value):
                continue
            before = line[: match.start()]
            if re.search(r"\btx\(\s*$", before):
                continue
            rows.append(f"{line_no}: {value}")
    return rows


def find_function_bodies(src: str) -> list[tuple[str, int]]:
    """Пары «имя компонента → смещение сразу после открывающей `{` тела»."""
    bodies: list[tuple[str, int]] = []
    pattern = re.compile(
        r"(?m)^(?:export\s+default\s+function|export\s+function|function)\s+"
        r"([A-Z]\w*)\s*(?:<[^>]*>)?\s*\(",
    )
    for match in pattern.finditer(src):
        depth = 0
        i = match.end() - 1
        while i < len(src):
            char = src[i]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        brace = src.find("{", i)
        if brace == -1:
            continue
        bodies.append((match.group(1), brace + 1))
    return bodies


def add_hook(src: str, name: str, offset: int, end: int) -> str:
    """Вставляет хук в тело компонента, если он там нужен и его ещё нет."""
    body = src[offset:end]
    if "useTx()" in body[:600] or "tx(" not in body:
        return src
    hook = "const { tx } = useTx();"
    # Первая непустая строка тела: вставляем хук перед ней, сохраняя отступ.
    rest = src[offset:]
    match = re.match(r"(\r?\n)([ \t]*)", rest)
    if not match:
        return src
    indent = match.group(2) or "  "
    insert_at = offset + match.end()
    return f"{src[:insert_at]}{hook}\n{indent}{src[insert_at:]}"


def add_import(src: str) -> str:
    if re.search(r'import \{[^}]*\buseTx\b[^}]*\} from "@/i18n";', src):
        return src
    if re.search(r'import \{[^}]*\} from "@/i18n";', src):
        return re.sub(
            r'import \{([^}]*)\} from "@/i18n";',
            lambda m: f'import {{{m.group(1).rstrip()}, useTx }} from "@/i18n";',
            src,
            count=1,
        )
    imports = list(IMPORT_LINE.finditer(src))
    if not imports:
        return src
    last = imports[-1]
    return f'{src[:last.end()]}\nimport {{ useTx }} from "@/i18n";{src[last.end():]}'


def wrap(src: str) -> tuple[str, list[str]]:
    code = strip_comments(src)
    edits: list[tuple[int, int, str]] = []
    keys: list[str] = []

    for match in JSX_TEXT.finditer(code):
        text = normalize(match.group(1))
        if not text or not HAS_CY.search(text) or "\\" in text:
            continue
        keys.append(text)
        start, end = match.span(1)
        nl = chr(10)
        if len(text) > 64:
            line_start = src.rfind(nl, 0, start) + 1
            indent = re.match(r"[ \t]*", src[line_start:]).group(0) + "  "
            replacement = f'{{tx({nl}{indent}"{escape(text)}",{nl}{indent[:-2]})}}'
        else:
            replacement = f'{{tx("{escape(text)}")}}'
        edits.append((start, end, replacement))

    for start, end, replacement in sorted(edits, key=lambda e: -e[0]):
        src = src[:start] + replacement + src[end:]
    return src, keys


def fix_attrs(src: str) -> tuple[str, list[str]]:
    code = strip_comments(src)
    keys: list[str] = []
    edits: list[tuple[int, int, str]] = []
    for match in ATTR.finditer(code):
        value = match.group(2)
        if not HAS_CY.search(value) or "\\" in value:
            continue
        keys.append(value)
        edits.append(
            (match.start(), match.end(), f'{match.group(1)}={{tx("{escape(value)}")}}'),
        )
    for start, end, replacement in sorted(edits, key=lambda e: -e[0]):
        src = src[:start] + replacement + src[end:]
    return src, keys


def bare_text(src: str) -> list[str]:
    """Кириллица вне строк и комментариев: JSX-текст с `{...}` и шаблоны."""
    rows: list[str] = []
    for line_no, line in enumerate(strip_comments(src).splitlines(), 1):
        stripped = re.sub(r'"[^"]*"', "", line)
        stripped = re.sub(r"'[^']*'", "", stripped)
        stripped = re.sub(r"`[^`]*`", "", stripped)
        if HAS_CY.search(stripped):
            rows.append(f"{line_no}: {line.strip()}")
    return rows


def command_wrap(path: Path) -> None:
    src = path.read_text(encoding="utf-8", newline="")
    src, text_keys = wrap(src)
    src, attr_keys = fix_attrs(src)
    src = add_import(src)
    bodies = sorted(find_function_bodies(src), key=lambda p: p[1])
    spans = [
        (name, offset, bodies[i + 1][1] if i + 1 < len(bodies) else len(src))
        for i, (name, offset) in enumerate(bodies)
    ]
    for name, offset, end in sorted(spans, key=lambda s: -s[1]):
        src = add_hook(src, name, offset, end)
    path.write_text(src, encoding="utf-8", newline="")
    keys = text_keys + attr_keys
    print(f"=== {path} — обёрнуто {len(keys)}")
    for key in dict.fromkeys(keys):
        print(f"  + {key}")
    rest = leftovers(src)
    if rest:
        print("  строки руками:")
        for row in rest:
            print(f"    {row}")
    bare = bare_text(src)
    if bare:
        print("  разметка руками:")
        for row in bare:
            print(f"    {row}")


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    mode, targets = argv[1], argv[2:]
    for target in targets:
        path = Path(target)
        if mode == "scan":
            for row in scan(path.read_text(encoding="utf-8")):
                print(f"{path}: {row}")
        elif mode == "bare":
            for row in bare_text(path.read_text(encoding="utf-8")):
                print(f"{path}: {row}")
        elif mode == "leftovers":
            for row in leftovers(path.read_text(encoding="utf-8")):
                print(f"{path}: {row}")
        elif mode == "wrap":
            command_wrap(path)
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
