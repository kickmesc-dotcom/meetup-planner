#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Деплой бэкенда на Hugging Face Spaces (бесплатный docker-хост).

Оригинальная схема meetup-planner: FastAPI-контейнер на HF (cpu-basic, без
оплаты), база в Neon, Cloudflare — фронт (Pages), R2 и прокси для Telegram.
Cloudflare сам Python-бэкенд хостить не может (Containers — платные, Python
Workers не тянут async SQLAlchemy), поэтому «бесплатно и как часы» — это HF.

Подкоманды:

    status      — что сейчас на хосте (стадия сборки, /healthz, /api/meta)
    env         — залить секреты из backend/.env в Space (значения не печатаются)
    mirror      — синхронизировать backend/ в репозиторий Space и запушить
    wait        — дождаться RUNNING и подтвердить свежий код по /api/meta
    all         — env → mirror → wait → status

Запуск из монорепо:

    backend/.venv/Scripts/python.exe tools/deploy-hf.py all

Токен HF берётся из окружения `HF_TOKEN` или из DPAPI-хранилища рабочей машины
(`secrets/Get-Secret.ps1 HF_TOKEN`). Секреты из `.env` читаются, но никогда не
печатаются: в выводе только имена и статус.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 — печать не должна ронять деплой
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BACKEND = os.path.join(ROOT, "backend")
SPACE_REPO = os.environ.get("HF_SPACE_REPO", "fryesw/meetup-planner-backend")
SPACE_URL = os.environ.get(
    "HF_SPACE_URL", "https://fryesw-meetup-planner-backend.hf.space"
)

# Что именно уезжает в Space: без тестов, кешей, venv и .env.
INCLUDE = ("app", "alembic", "alembic.ini", "pyproject.toml", "Dockerfile", "README.md")
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "tests"}

# Секреты, которые нужны приложению в бою. Значения — из backend/.env.
ENV_KEYS = (
    "BOT_TOKEN",
    "TG_WEBHOOK_SECRET",
    "DATABASE_URL",
    "MINI_APP_URL",
    "PUBLIC_BASE_URL",
    "ADMIN_TG_IDS",
    "GROUP_CHAT_ID",
    "WHITELIST_TG_IDS",
    "WHITELIST_NAMES",
    "CORS_ORIGINS",
    "SCHEDULER_TZ",
    "LOG_LEVEL",
    # Web push (шаг 2.4): без пары VAPID подписка браузера не сработает.
    "VAPID_PUBLIC_KEY",
    "VAPID_PRIVATE_KEY",
    "VAPID_SUBJECT",
)


def _secret_store() -> dict[str, str]:
    script = os.path.join(os.path.dirname(ROOT), "secrets", "Get-Secret.ps1")
    if not os.path.exists(script):
        return {}
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-File", script, "-Json"],
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    raw = (proc.stdout or b"").decode("utf-8", "replace").lstrip("\ufeff")
    # В значениях бывают переводы строк — JSON от PowerShell тогда
    # невалиден («Invalid control character»), поэтому служебные символы
    # вырезаем до разбора.
    raw = re.sub(r"[\x00-\x1f]", " ", raw).strip()
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return {str(k): ("" if v is None else str(v)) for k, v in data.items()} if isinstance(data, dict) else {}


def _single_secret(key: str) -> str:
    """Страховка: точечное чтение одного ключа из DPAPI-хранилища."""
    script = os.path.join(os.path.dirname(ROOT), "secrets", "Get-Secret.ps1")
    if not os.path.exists(script):
        return ""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-File", script, key],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (proc.stdout or b"").decode("utf-8", "replace").strip()


def hf_token() -> str:
    token = (os.environ.get("HF_TOKEN") or "").strip()
    if not token:
        token = (_secret_store().get("HF_TOKEN") or "").strip()
    if not token:
        token = _single_secret("HF_TOKEN")
    if not token:
        sys.exit("Нет HF_TOKEN: положите его в secrets/ (Get-Secret.ps1) или в переменную окружения.")
    return token


def read_env_file() -> dict[str, str]:
    path = os.path.join(BACKEND, ".env")
    if not os.path.exists(path):
        sys.exit(f"Нет {path} — нечего заливать в Space.")
    out: dict[str, str] = {}
    for line in open(path, encoding="utf-8", errors="replace").read().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


# ----------------------------------------------------------------- секреты ----


def api_request(path: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"https://huggingface.co/api/{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {hf_token()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        return exc.code, {"error": raw[:300]}


def put_secret(key: str, value: str) -> bool:
    status, body = api_request(
        f"spaces/{SPACE_REPO}/secrets", method="POST", payload={"key": key, "value": value}
    )
    ok = status in (200, 201)
    print(f"  {'✓' if ok else '✗'} {key}" + ("" if ok else f" — HTTP {status} {body.get('error', '')}"))
    return ok


def cmd_env(_args) -> int:
    env = read_env_file()
    # Публичный адрес API — это сам Space: от него зависят CORS и редиректы,
    # поэтому берём его не из старого `.env`, а из фактического адреса.
    env["PUBLIC_BASE_URL"] = SPACE_URL
    print(f"Заливаю секреты в {SPACE_REPO} (значения не печатаются):")
    store = _secret_store()
    missing = []
    for key in ENV_KEYS:
        value = env.get(key, "")
        if not value:
            # Часть ключей живёт только в DPAPI-хранилище (доступы, чат) —
            # в `.env` их держать не обязательно.
            value = (store.get(key) or "").strip() or _single_secret(key).strip()
        if not value:
            missing.append(key)
            continue
        put_secret(key, value)
    if missing:
        print(f"  (пусто в backend/.env, пропущено: {', '.join(missing)})")
    return 0


# ------------------------------------------------------------------ mirror ----


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    token = hf_token()
    askpass = os.path.join(tempfile.gettempdir(), "hf-askpass.sh")
    with open(askpass, "w", encoding="utf-8", newline="\n") as fh:
        fh.write('#!/bin/sh\necho "$HF_TOKEN"\n')
    os.chmod(askpass, 0o700)
    environment = dict(os.environ, HF_TOKEN=token, GIT_ASKPASS=askpass, GIT_TERMINAL_PROMPT="0")
    proc = subprocess.run(args, cwd=cwd, capture_output=True, env=environment)
    proc.stdout = (proc.stdout or b"").decode("utf-8", "replace")  # type: ignore[assignment]
    proc.stderr = (proc.stderr or b"").decode("utf-8", "replace")  # type: ignore[assignment]
    return proc


def _sync_tree(dest: str) -> list[str]:
    copied: list[str] = []
    for name in INCLUDE:
        src = os.path.join(BACKEND, name)
        if not os.path.exists(src):
            continue
        target = os.path.join(dest, name)
        if os.path.isdir(src):
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(
                src,
                target,
                ignore=shutil.ignore_patterns(*SKIP_DIRS),
            )
        else:
            shutil.copy2(src, target)
        copied.append(name)
    return copied


def cmd_mirror(_args) -> int:
    workdir = os.path.join(tempfile.gettempdir(), "hf-space-" + SPACE_REPO.replace("/", "-"))
    url = f"https://huggingface.co/spaces/{SPACE_REPO}"
    if os.path.isdir(os.path.join(workdir, ".git")):
        proc = _git(["git", "fetch", "--all", "--prune"], workdir)
        _git(["git", "reset", "--hard", "origin/main"], workdir)
    else:
        shutil.rmtree(workdir, ignore_errors=True)
        proc = _git(["git", "clone", "--depth", "1", url, workdir], os.getcwd())
    if proc.returncode != 0:
        sys.exit(f"git не смог подготовить репозиторий Space:\n{proc.stderr[-1500:]}")

    copied = _sync_tree(workdir)
    print(f"Синхронизировано: {', '.join(copied)}")
    _git(["git", "add", "-A"], workdir)
    diff = _git(["git", "status", "--porcelain"], workdir)
    if not (diff.stdout or "").strip():
        print("Изменений нет — Space уже на этой версии кода.")
        return 0
    message = "deploy: SemiTaskBot backend (кабинет управляющего, обучение, тихие часы)"
    commit = _git(["git", "-c", "core.safecrlf=false", "commit", "-q", "-m", message], workdir)
    if commit.returncode != 0:
        sys.exit(f"commit не прошёл:\n{commit.stderr[-1000:]}")
    push = _git(["git", "push", "origin", "HEAD:main"], workdir)
    if push.returncode != 0:
        sys.exit(f"push не прошёл:\n{push.stderr[-1500:]}")
    print("Запушено — Space начал пересборку.")
    return 0


# ------------------------------------------------------------------ статус ----


def space_stage() -> tuple[str | None, str | None]:
    status, body = api_request(f"spaces/{SPACE_REPO}")
    if status != 200:
        return None, f"HTTP {status}"
    runtime = body.get("runtime") or {}
    return runtime.get("stage"), runtime.get("domain") or SPACE_URL


def fetch(url: str, timeout: float = 25.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:200]
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def _local_head() -> str | None:
    versions = os.path.join(BACKEND, "alembic", "versions")
    revs: dict[str, str | None] = {}
    for name in sorted(os.listdir(versions)):
        if not name.endswith(".py"):
            continue
        text = open(os.path.join(versions, name), encoding="utf-8", errors="replace").read()
        rev = re.search(r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)", text, re.M)
        down = re.search(r"^down_revision(?::[^=]*)?\s*=\s*(.*)$", text, re.M)
        if not rev:
            continue
        downs = re.findall(r"[\"']([^\"']+)[\"']", (down.group(1) if down else "").strip())
        revs[rev.group(1)] = downs[0] if downs else None
    parents = {d for d in revs.values() if d}
    heads = [r for r in revs if r not in parents]
    return heads[0] if len(heads) == 1 else None


def cmd_status(_args) -> int:
    stage, domain = space_stage()
    print(f"Space: {SPACE_REPO} · стадия: {stage} · адрес: {domain}")
    code, body = fetch(f"{SPACE_URL}/healthz")
    print(f"/healthz → HTTP {code} {body[:60]}")
    code, body = fetch(f"{SPACE_URL}/api/meta")
    if code == 200:
        try:
            meta = json.loads(body)
        except ValueError:
            meta = {}
        code_info = meta.get("code", {})
        db = meta.get("db", {})
        print(
            f"/api/meta: путей {code_info.get('routes')} · отпечаток {code_info.get('fingerprint')}"
            f" · head кода {code_info.get('alembic_head')} (локально {_local_head()})"
        )
        print(
            f"           база {db.get('provider')} · {db.get('host')} · {db.get('name')}"
            f" · миграции в БД {db.get('alembic_version')}"
        )
    else:
        print(f"/api/meta → HTTP {code} (старая сборка? {body[:80]})")
    return 0


def cmd_wait(args) -> int:
    deadline = time.time() + args.timeout
    head = _local_head()
    last = None
    while time.time() < deadline:
        stage, _ = space_stage()
        code, _body = fetch(f"{SPACE_URL}/healthz", timeout=15)
        state = f"{stage}/healthz={code}"
        if state != last:
            print(f"  {state}")
            last = state
        if stage in {"RUNNING"} and code == 200:
            mcode, mbody = fetch(f"{SPACE_URL}/api/meta")
            if mcode == 200:
                try:
                    meta = json.loads(mbody)
                except ValueError:
                    meta = {}
                if (meta.get("code") or {}).get("alembic_head") == head:
                    print("✅ Код и миграции свежие, хост отвечает.")
                    return 0
                print("   … контейнер жив, но сборка ещё старше кода.")
        if stage in {"BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR"}:
            print(f"❌ Space в состоянии {stage} — смотрите логи на {SPACE_REPO}")
            return 1
        time.sleep(15)
    print("⌛ Не дождался RUNNING за отведённое время (сборка ещё идёт?).")
    return 1


def cmd_all(args) -> int:
    rc = cmd_env(args)
    if rc:
        return rc
    rc = cmd_mirror(args)
    if rc:
        return rc
    rc = cmd_wait(args)
    cmd_status(args)
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, func in (
        ("status", cmd_status),
        ("env", cmd_env),
        ("mirror", cmd_mirror),
        ("wait", cmd_wait),
        ("all", cmd_all),
    ):
        p = sub.add_parser(name)
        p.add_argument("--timeout", type=int, default=1800, help="сколько ждать сборку, сек")
        p.set_defaults(func=func)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
