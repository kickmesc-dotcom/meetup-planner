# -*- coding: utf-8 -*-
"""Убирает переведённые экраны из списка `PENDING` в страже покрытия.

`coverage.test.ts` держит ратчет: список непереведённого может только
сокращаться. Руками это две правки на каждый экран (строка в списке и число в
пределе) и одна забытая — падение теста. Скрипт делает обе одним движением:

    python tools/i18n-shrink.py src/features/hr/KpiCard.tsx src/App.tsx

Предел пересчитывается по фактическому размеру списка, поэтому «минус строка,
минус единица» держится само. Файла нет в списке — скрипт скажет об этом и
выйдет с кодом 1: значит его уже убрали или имя набрано с ошибкой.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TEST = ROOT / "frontend" / "src" / "i18n" / "coverage.test.ts"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 0

    src = io.open(TEST, encoding="utf-8", newline="").read()
    # `src/features/hr/KpiCard.tsx` → `features/hr/KpiCard.tsx`.
    wanted = {
        re.sub(r"^.*?\bsrc/", "", arg.replace("\\", "/").lstrip("./")) for arg in argv
    }

    lines = src.splitlines(True)
    out: list[str] = []
    removed: set[str] = set()
    for line in lines:
        match = re.match(r'^\s*"([^"]+)",\s*$', line.rstrip("\r\n"))
        if match and match.group(1) in wanted:
            removed.add(match.group(1))
            continue
        out.append(line)

    missing = sorted(wanted - removed)
    if missing:
        print("нет в списке PENDING:", ", ".join(missing), file=sys.stderr)

    src = "".join(out)
    size = len(re.findall(r'^\s*"[^"]+",\s*$', src, re.M))
    src = re.sub(
        r"expect\(PENDING\.size\)\.toBeLessThanOrEqual\(\d+\);",
        f"expect(PENDING.size).toBeLessThanOrEqual({size});",
        src,
    )
    io.open(TEST, "w", encoding="utf-8", newline="").write(src)
    print(f"убрано {len(removed)}, в списке осталось {size}")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
