#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Счётчики roadmap → блок в `docs/STATUS.md`.

Зачем. Сводка состояния — единственный документ, который обязан меняться
вместе с планом; вручную она отстаёт на первой же галочке, а «сколько осталось»
по ней становится неверным. Здесь числа считаются из разметки
`docs/AAA_ROADMAP.md`, а не переписываются руками.

Что делает:

  (без флагов)  — переписать блок между `<!-- roadmap:begin -->` и
                  `<!-- roadmap:end -->` в `docs/STATUS.md`;
  --check       — ничего не менять, вернуть 1, если блок отстал (для CI).

Считаются только пункты верхнего уровня (`- [x]  …`): вложенные строки
продолжают тот же пункт и отдельными задачами не являются.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs" / "AAA_ROADMAP.md"
STATUS = ROOT / "docs" / "STATUS.md"

BEGIN = "<!-- roadmap:begin -->"
END = "<!-- roadmap:end -->"

_ITEM = re.compile(r"^- \[(?P<mark>[ x~])\] ", re.MULTILINE)


def counts(text: str) -> dict[str, int]:
    marks = [m.group("mark") for m in _ITEM.finditer(text)]
    return {
        "done": marks.count("x"),
        "active": marks.count("~"),
        "open": marks.count(" "),
        "total": len(marks),
    }


def render(stats: dict[str, int]) -> str:
    total = stats["total"] or 1
    percent = round(stats["done"] * 100 / total)
    return (
        f"{BEGIN}\n"
        f"| Закрыто | В работе | Открыто | Всего |\n"
        f"|---:|---:|---:|---:|\n"
        f"| {stats['done']} | {stats['active']} | {stats['open']} | {stats['total']} |\n"
        f"\n"
        f"Закрыто {percent} % пунктов плана (`docs/AAA_ROADMAP.md`). "
        f"Открытые — те, что требуют живого аккаунта, человека или панели; "
        f"этот блок пересобирается командой "
        f"`backend/.venv/Scripts/python.exe tools/roadmap-status.py`.\n"
        f"{END}"
    )


def replace_block(status_text: str, block: str) -> str:
    if BEGIN not in status_text or END not in status_text:
        sys.exit(f"В {STATUS.name} нет маркеров {BEGIN} / {END}")
    start = status_text.index(BEGIN)
    end = status_text.index(END) + len(END)
    return status_text[:start] + block + status_text[end:]


def main() -> int:
    # Консоль Windows по умолчанию cp1251 и роняет печать на «✓»/«✗».
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — печать не имеет права ронять проверку
        pass
    parser = argparse.ArgumentParser(prog="roadmap-status.py", description=__doc__)
    parser.add_argument("--check", action="store_true", help="только проверить, не менять")
    args = parser.parse_args()

    for path in (ROADMAP, STATUS):
        if not path.exists():
            sys.exit(f"Нет файла: {path}")

    stats = counts(ROADMAP.read_text(encoding="utf-8"))
    current = STATUS.read_text(encoding="utf-8")
    expected = replace_block(current, render(stats))

    if args.check:
        if expected != current:
            print(
                "✗ docs/STATUS.md отстал от roadmap: "
                "запусти tools/roadmap-status.py",
            )
            return 1
        print(f"✓ статус актуален: закрыто {stats['done']} / {stats['total']}")
        return 0

    if expected == current:
        print(f"Статус уже актуален: закрыто {stats['done']} / {stats['total']}")
        return 0

    STATUS.write_text(expected, encoding="utf-8")
    print(
        f"Обновлено: закрыто {stats['done']}, в работе {stats['active']}, "
        f"открыто {stats['open']} из {stats['total']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
