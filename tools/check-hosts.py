"""Сверка «какой код и какая база где живут».

Зачем: фронт и два бэкенда (Amvera — боевой, HF — запасной) деплоятся
независимо, и любой из них может молча отстать на несколько сборок. Раньше это
выяснялось диффом `openapi.json`; теперь у каждого хоста есть `/api/meta`, и
достаточно сравнить его отпечаток с локальным.

Запуск из корня монорепо (нужен venv бэкенда — скрипт импортирует приложение):

    backend/.venv/Scripts/python.exe tools/check-hosts.py

Что показывает по каждому хосту: ревизию кода (отпечаток роутов + head миграций
из кода), куда контейнер пишет (провайдер БД, замаскированный хост, версия
миграций в базе) и чего в этой сборке не хватает относительно локального кода.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

# Консоль Windows по умолчанию в CP866 и превращает русский текст в кашу.
# Пишем UTF-8: в Windows Terminal и PowerShell 7 это читается сразу, а в старом
# cmd достаточно один раз сделать `chcp 65001`.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 — печать не имеет права ронять диагностику
    pass

# Боевой хост один: FastAPI на Hugging Face Space (cpu-basic, бесплатно),
# Cloudflare держит фронт (Pages) и R2. Amvera из проекта убрана — её адрес
# больше не проверяем, иначе «расхождение» показывал бы выключенный хост.
HOSTS: dict[str, str] = {
    "hf (боевой)": "https://fryesw-meetup-planner-backend.hf.space",
}

TIMEOUT = 30


def _local_fingerprint() -> tuple[dict[str, Any], list[str]]:
    """Отпечаток ЛОКАЛЬНОГО кода — эталон для сравнения.

    Приложение импортируется с заглушками в env: реальные секреты для этого не
    нужны, а подключение к базе ленивое (get_engine создаётся при первом запросе).
    """
    for key, value in {
        "BOT_TOKEN": "x",
        "TG_WEBHOOK_SECRET": "x",
        "MINI_APP_URL": "https://x.test",
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
    }.items():
        os.environ.setdefault(key, value)

    sys.path.insert(0, str(BACKEND))
    from app.api.routes_meta import available_features, code_fingerprint
    from app.main import app

    return code_fingerprint(app), available_features(app)


def _fetch_json(
    url: str, headers: dict[str, str] | None = None
) -> tuple[int, dict[str, Any] | None]:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # noqa: BLE001
        print(f"    ! сеть: {type(exc).__name__}: {exc}")
        return 0, None


def _env_secret(key: str) -> str | None:
    """Секрет из окружения или `backend/.env` — как это делают другие tools."""
    value = (os.environ.get(key) or "").strip()
    if value:
        return value
    env_file = BACKEND / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, raw = line.partition("=")
        if name.strip() == key:
            return raw.strip().strip('"').strip("'")
    return None


def _db_details(base: str) -> dict[str, Any]:
    """То, чего больше нет в публичном `/api/meta` (S-12): порт, имя базы, версия СУБД.

    Живёт за секретом в `X-Diag-Token`. Секрета нет (или он не подошёл) — вернём
    пусто: сверка контуров без него всё равно работает по замаскированному хосту
    и миграциям.
    """
    token = _env_secret("TG_WEBHOOK_SECRET")
    if not token:
        return {}
    status, body = _fetch_json(f"{base}/api/meta/net", {"X-Diag-Token": token})
    if status != 200 or not body:
        return {}
    return body.get("db") or {}


def _path_count(base: str) -> int | None:
    """Фолбэк для сборок, которые ещё не знают `/api/meta`."""
    status, body = _fetch_json(f"{base}/openapi.json")
    if status == 200 and body:
        return len(body.get("paths", {}))
    return None


def main() -> int:
    local_fp, local_features = _local_fingerprint()
    print("=== ЛОКАЛЬНЫЙ КОД (эталон) ===")
    print(
        f"  роутов: {local_fp['routes']} (api: {local_fp['api_routes']}) · "
        f"отпечаток: {local_fp['fingerprint']}"
    )
    print(f"  возможностей: {len(local_features)}")

    drifted = 0
    for name, base in HOSTS.items():
        print(f"\n=== {name} — {base} ===")
        status, body = _fetch_json(f"{base}/api/meta")

        if body is None:
            paths = _path_count(base)
            drifted += 1
            print(f"  /api/meta -> HTTP {status}: сборка СТАРШЕ, чем появление /api/meta")
            if paths is not None:
                print(f"  (для справки: путей в openapi = {paths})")
            print("  вердикт: хост отстаёт — нужна пересборка")
            continue

        code = body.get("code", {})
        db = body.get("db", {})
        details = _db_details(base)
        features = body.get("features", [])
        same = code.get("fingerprint") == local_fp["fingerprint"]

        print(f"  код:      роутов {code.get('routes')} · отпечаток {code.get('fingerprint')}"
              f" · head миграций (код) {code.get('alembic_head')}")
        print(f"  база:     {db.get('provider')} · {db.get('host')}"
              f" · миграции в БД: {db.get('alembic_version')}")
        # Порт, имя базы и версия СУБД — только по секрету (S-12): в публичном
        # ответе их нет намеренно, но для сверки контуров они нужны.
        if details:
            print(f"            {details.get('name')} · порт {details.get('port')}"
                  f" · сервер {details.get('server_version')}")
        else:
            print("            (порт, имя базы и версия СУБД — за секретом"
                  " TG_WEBHOOK_SECRET в /api/meta/net)")
        if db.get("error"):
            print(f"  ⚠️  база не ответила: {db['error']}")
        print(f"  возможностей: {len(features)}")

        if same:
            print("  вердикт: АКТУАЛЕН (отпечаток совпадает с локальным)")
        else:
            drifted += 1
            missing = sorted(set(local_features) - set(features))
            extra = sorted(set(features) - set(local_features))
            print("  вердикт: ОТСТАЁТ или уехал вперёд")
            if missing:
                print(f"    нет на хосте: {', '.join(missing)}")
            if extra:
                print(f"    есть только на хосте: {', '.join(extra)}")
            if not missing and not extra:
                print("    состав ручек тот же, но список роутов отличается — смотри diff openapi")

        if code.get("alembic_head") != db.get("alembic_version"):
            print(
                f"  ⚠️  миграции: код ждёт {code.get('alembic_head')}, "
                f"в базе {db.get('alembic_version')} — расхождение схемы"
            )

    print()
    print("=== ИТОГ ===")
    print("  всё актуально" if drifted == 0 else f"  хостов с расхождением: {drifted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
