"""Временный скрипт: подставить в журнал живые значения из /api/meta."""

from __future__ import annotations

import json
import pathlib
import urllib.request

URL = "https://meetup-planner-youmakemefry.waw0.amvera.tech/api/meta"
ROOT = pathlib.Path(__file__).resolve().parent.parent

with urllib.request.urlopen(URL, timeout=20) as rsp:  # noqa: S310 — свой прод
    meta = json.loads(rsp.read().decode("utf-8"))

build = str((meta.get("code") or {}).get("build") or "")
head = str((meta.get("code") or {}).get("alembic_head") or "")
db = str((meta.get("db") or {}).get("alembic_version") or "")
sched = meta.get("scheduler") or {}
running = sched.get("running")
leader = sched.get("leader")
print(f"build={build} head={head} db={db} sched={running}/{leader}")

path = ROOT / "docs/MOBILE_PARALLEL.md"
raw = path.read_bytes()
crlf = b"\r\n" in raw
text = raw.decode("utf-8").replace("\r\n", "\n")

before = text
text = text.replace("Amvera build `` — ", f"Amvera build `{build}` — ")
text = text.replace(
    "`scheduler.running`/`leader` = true.",
    f"`scheduler.running`/`leader` = {str(running).lower()}/{str(leader).lower()}.",
)
text = text.replace(
    "= `0071_api_import_runs`, `scheduler.running`",
    f"= `{db}`, `code.alembic_head` = `{head}`, `scheduler.running`",
)
if text == before:
    print("no change — паттерн не найден")
else:
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    print("journal meta fixed")
