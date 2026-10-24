"""Обёртка русских строк в выражениях экрана в `tx("…")`.

`i18n-wrap.py` берёт разметку (`>Текст<`) и подписи-атрибуты. Остаются строки
в выражениях: тернарники в JSX (`{on ? "Да" : "Нет"}`), `showAlert("…")`,
`showConfirm("…")`, подписи в массивах опций. Их оборачивает этот скрипт.

Комментарии сохраняются: замены идут по смещениям в оригинале, а «код» для
поиска — это копия с пробелами вместо комментариев (длина та же).

Что НЕ трогается (печатается списком — проверить глазами):
  * сравнения (`=== "…"`, `!== "…"`, `.startsWith("…")`, `case "…"`) — это
    значения с сервера, перевод сломал бы логику;
  * ключи объектов (`"…":`) — по ним ищут в таблицах;
  * строки внутри уже готового `tx(...)`;
  * шаблонные строки с подстановками — их надо переписать руками.

Запуск:
    python tools/i18n-autowrap.py src/features/hr/TrainingScreen.tsx
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CYRILLIC = "А-Яа-яЁё"
HAS_CY = re.compile(f"[{CYRILLIC}]")
RISKY = (
    '=== "',
    '!== "',
    '.startsWith("',
    'case "',
    'key: "',
    'value: "',
    "mutate(",
    "import ",
    'from "',
    'icon: "',
    'setTab("',
    "useState",
    "throw ",
)
IMPORT_LINE = re.compile(r"^import .*?;\s*$", re.MULTILINE)
LITERAL = re.compile(r'"([^"\n]*)"')


def mask_comments(src: str) -> str:
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


def inside_tx(code: str, pos: int) -> bool:
    """Литерал стоит внутри вызова `tx( … )` — второй раз не оборачиваем."""
    depth = 0
    i = pos - 1
    while i >= 0:
        char = code[i]
        if char == ")":
            depth += 1
        elif char == "(":
            if depth == 0:
                head = code[max(0, i - 4) : i].strip()
                return head.endswith("tx") or head.endswith("txIn")
            depth -= 1
        i -= 1
    return False


def function_bodies(code: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pattern = re.compile(
        r"(?m)^(?:export\s+default\s+function|export\s+function|function)\s+"
        r"([A-Z]\w*)\s*(?:<[^>]*>)?\s*\(",
    )
    for match in pattern.finditer(code):
        depth = 0
        i = match.end() - 1
        while i < len(code):
            if code[i] == "(":
                depth += 1
            elif code[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        brace = code.find("{", i)
        if brace != -1:
            spans.append((brace + 1, 0))
    spans.sort()
    out = []
    for index, (start, _) in enumerate(spans):
        end = spans[index + 1][0] if index + 1 < len(spans) else len(code)
        out.append((start, end))
    return out


def add_hooks(src: str) -> str:
    code = mask_comments(src)
    for start, end in sorted(function_bodies(code), reverse=True):
        body = code[start:end]
        if "useTx()" in body[:600] or "tx(" not in body:
            continue
        rest = src[start:]
        match = re.match(r"(\r?\n)([ \t]*)", rest)
        if not match:
            continue
        indent = match.group(2) or "  "
        insert_at = start + match.end()
        src = f"{src[:insert_at]}const {{ tx }} = useTx();\n{indent}{src[insert_at:]}"
        code = mask_comments(src)
    return src


def leftover_templates(src: str) -> list[str]:
    rows: list[str] = []
    for line_no, line in enumerate(mask_comments(src).splitlines(), 1):
        for match in re.finditer(r"`([^`]*)`", line):
            if HAS_CY.search(match.group(1)):
                rows.append(f"{line_no}: `{match.group(1)}`")
    return rows


def autowrap(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    code = mask_comments(src)
    skipped: list[str] = []
    edits: list[tuple[int, int, str]] = []
    data_risk = [False] * len(code)

    # Первый проход: пометить строки с рискованными конструкциями.
    offset = 0
    for line in code.splitlines(keepends=True):
        if any(marker in line for marker in RISKY):
            for i in range(offset, offset + len(line)):
                data_risk[i] = True
        offset += len(line)

    for match in LITERAL.finditer(code):
        value = match.group(1)
        if not HAS_CY.search(value) or "\\" in value:
            continue
        start = match.start()
        line_start = code.rfind("\n", 0, start) + 1
        line_end = code.find("\n", start)
        line = code[line_start : line_end if line_end != -1 else len(code)]
        if data_risk[start] or inside_tx(code, start):
            skipped.append(line.strip())
            continue
        before = code[line_start:start].rstrip()
        after = code[match.end() : match.end() + 40].lstrip()
        if after.startswith(":") and before.endswith(("{", ",", "(")):
            skipped.append(line.strip())
            continue
        replacement = f'tx("{value}")'
        if before.endswith("=") and not before.endswith("=>"):
            replacement = "{" + replacement + "}"
        edits.append((match.start(), match.end(), replacement))

    for start, end, replacement in sorted(edits, reverse=True):
        src = src[:start] + replacement + src[end:]

    src = add_import(src)
    src = add_hooks(src)
    path.write_text(src, encoding="utf-8")
    print(f"=== {path} — строк обёрнуто {len(edits)}")
    for row in dict.fromkeys(skipped):
        print(f"  пропущено: {row}")
    for row in leftover_templates(src):
        print(f"  шаблон: {row}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    for target in argv[1:]:
        autowrap(Path(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
