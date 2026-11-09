import io
import sys

pid, gl, feat, api = sys.argv[1:5]
q = "docs/UX_REORG_PLAN.md"
u = io.open(q, encoding="utf-8").read()
if "приёмник ошибок" not in u:
    row = (
        f"| 08.11.2026 | ААА, этап 1: приёмник ошибок фронта (`POST /api/telemetry`) | "
        f"pytest 5, vitest 8, lines {gl} %, features {feat} %, api {api} %; Pages `{pid}` |"
    )
    lst = u.split("\n")
    idx = max(k for k, l in enumerate(lst) if l.startswith("| 08.11.2026"))
    lst.insert(idx + 1, row)
    io.open(q, "w", encoding="utf-8", newline="").write("\n".join(lst))
    print("журнал: запись добавлена")
