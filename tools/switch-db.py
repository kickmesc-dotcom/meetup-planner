#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Рабочий переключатель базы для meetup-planner.

Заменяет `meetup-switch/*.bat`, которые переключали не то, что нужно: те .bat
меняли URL вебхука Telegram (какой бэкенд обслуживает бота), а база живёт в
переменной окружения `DATABASE_URL`, которую читает контейнер при старте.

Что делает этот скрипт:

  status                  — что сейчас у обоих хостов (код, база, миграции)
  reserves                — состояние ВСЕХ известных баз, включая мёртвые
                            резервы: жива ли, схема, объём, свежесть данных
                            и какой хост на неё сейчас смотрит
  check <кандидат>        — проверить базу ДО переключения (доступность,
                            версия миграций, объём, свежесть данных)
  switch <кандидат>       — поменять DATABASE_URL у ОБОИХ хостов, перезапустить
                            их и подтвердить результат по /api/meta
  webhook amvera|hf       — перевести вебхук Telegram на хост (алиас:
                            `backend <хост>`, — раньше это делали .bat)

Кандидат — это либо полный DSN (`postgresql+asyncpg://…`), либо имя базы:
`current` (та, что стоит в проде), `dsn1`/`dsn2` (по порядку из файлов
токенов) или короткое имя по Neon-endpoint (`cool-union`, `rapid-butterfly`).
Список с маской печатают `reserves` и `check --list`; достаточно префикса
имени, если он однозначен.

Секреты скрипт читает сам: env → DPAPI-хранилище рабочей машины
(`secrets/store.dpapi`, доступ — через `secrets/Get-Secret.ps1`). Руками
подставлять токены в скрипты не нужно; где что лежит — `secrets/README.md`,
а как запускать одним кликом — `meetup-switch/README.md`.

Безопасность: пароли из DSN нигде не печатаются целиком, только маска.

Запуск (можно любым питоном — скрипт сам перезапустится на venv бэкенда, где
есть asyncpg). Канонический файл лежит в монорепо (`meetup-planner-main/tools/`),
в корне рабочей папки оставлен тонкий шим с тем же именем — .bat из
`meetup-switch/` зовут именно его:

    python meetup-planner-main/tools/switch-db.py status
    python meetup-planner-main/tools/switch-db.py reserves
    python meetup-planner-main/tools/switch-db.py check cool-union
    python meetup-planner-main/tools/switch-db.py switch cool-union

Переменные окружения (необязательны — без них всё берётся из secrets/):
    AMVERA_MCP_TOKEN / AMVERA_MCP_URL — токен и адрес MCP Amvera
    HF_TOKEN                          — токен HF
    BOT_TOKEN / TG_WEBHOOK_SECRET     — для `webhook`/`backend`
    AMVERA_SLUG                       — слаг проекта Amvera (по умолчанию meetup-planner)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

def _find_up(start: str, marker: str, limit: int = 5) -> str | None:
    """Ближайшая папка вверх по дереву, где есть `marker`.

    Скрипт запускают и из корня рабочей папки (`tools/switch-db.py`), и из
    монорепо (`meetup-planner-main/tools/switch-db.py` — здесь он и версионируется),
    поэтому пути нельзя вычислять от `__file__` жёстко.
    """
    cur = start
    for _ in range(limit):
        if os.path.exists(os.path.join(cur, marker)):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


HERE = os.path.dirname(os.path.abspath(__file__))
# Секреты и файлы токенов живут в корне рабочей папки (вне репозитория).
WORKSPACE = _find_up(HERE, os.path.join("secrets", "Get-Secret.ps1")) or os.path.dirname(HERE)
# Бэкенд ищем по alembic/versions, а не по имени папки: работает и в монорепо,
# и из старой раскладки (корневой tools/).
MONOREPO = _find_up(HERE, os.path.join("backend", "alembic", "versions")) or os.path.join(
    WORKSPACE, "meetup-planner-main"
)
BACKEND = os.path.join(MONOREPO, "backend")
HF_REPO = os.environ.get("HF_SPACE_REPO", "fryesw/meetup-planner-backend")
AMVERA_SLUG = os.environ.get("AMVERA_SLUG", "meetup-planner")
AMVERA_ENV_NAME = "DATABASE_URL"

HOSTS = {
    "amvera": "https://meetup-planner-youmakemefry.waw0.amvera.tech",
    "hf": "https://fryesw-meetup-planner-backend.hf.space",
}

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# ------------------------------------------------------- venv и asyncpg -----
def _venv_python() -> str | None:
    for rel in ("Scripts/python.exe", "bin/python"):
        path = os.path.join(BACKEND, ".venv", *rel.split("/"))
        if os.path.exists(path):
            return path
    return None


def _ensure_asyncpg() -> None:
    """asyncpg нужен только для `check`. Если его нет — перезапускаемся на venv."""
    if importlib.util.find_spec("asyncpg") is not None:
        return
    venv = _venv_python()
    if venv and os.path.abspath(sys.executable) != os.path.abspath(venv):
        os.execv(venv, [venv, os.path.abspath(__file__), *sys.argv[1:]])
    sys.exit(
        "Нужен asyncpg. Запустите скрипт питоном из backend/.venv, например:\n"
        f"  {venv or '<backend>/.venv/Scripts/python.exe'} tools/switch-db.py "
        + " ".join(sys.argv[1:])
    )


# ------------------------------------------------------------- секреты -----
SECRET_SCRIPT = os.path.join(WORKSPACE, "secrets", "Get-Secret.ps1")
_STORE: dict[str, str] | None = None


def _store() -> dict[str, str]:
    """Всё DPAPI-хранилище одним вызовом powershell (ключи + значения).

    Русские значения в хранилище местами побиты перекодировкой, поэтому байты
    декодируем сами и с `errors="replace"` — иначе UnicodeDecodeError уронил бы
    чтение всего хранилища.
    """
    global _STORE
    if _STORE is not None:
        return _STORE
    _STORE = {}
    if not os.path.exists(SECRET_SCRIPT):
        return _STORE
    for shell in ("powershell", "pwsh"):
        try:
            proc = subprocess.run(
                [shell, "-NoProfile", "-File", SECRET_SCRIPT, "-Json"],
                capture_output=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        raw = (proc.stdout or b"").decode("utf-8", "replace").lstrip("\ufeff").strip()
        if proc.returncode != 0 or not raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict):
            _STORE = {str(k): ("" if v is None else str(v)) for k, v in data.items()}
            return _STORE
    return _STORE


def secret(key: str) -> str | None:
    """Секрет: env → DPAPI-хранилище (см. secrets/README.md)."""
    if os.environ.get(key):
        return os.environ[key]
    val = (_store().get(key) or "").strip()
    if val:
        return val
    # Страховка на случай, если JSON-дамп целиком не разобрался — точечный вызов.
    if os.path.exists(SECRET_SCRIPT) and not _STORE:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-File", SECRET_SCRIPT, key],
                capture_output=True,
                text=True,
                timeout=60,
            )
            val = (out.stdout or "").strip()
            if val:
                return val
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def secrets_hint(key: str) -> str:
    """Вместо «нет токена» — где секреты вообще лежат."""
    return (
        f"Нет секрета «{key}»: его нет ни в переменных окружения, ни в DPAPI-хранилище.\n"
        f"  Хранилище: {os.path.relpath(SECRET_SCRIPT, WORKSPACE)} "
        f"(значения — в store.dpapi рядом с ним; читается только под этой учётной записью Windows).\n"
        "  Список ключей:    powershell -File secrets\\Get-Secret.ps1\n"
        "  Одно значение:    powershell -File secrets\\Get-Secret.ps1 " + key + "\n"
        "  Обновить из JSON: powershell -File secrets\\Import-Secrets.ps1 -JsonPath <файл>\n"
        "  Подробности — secrets/README.md."
    )


DSN_RE = re.compile(r"postgresql(?:\+asyncpg)?://[^\s\"'<>]+")
NEON_ENDPOINT_RE = re.compile(r"@ep-([a-z0-9]+)-([a-z0-9]+)", re.I)


def dsn_label(dsn: str) -> str | None:
    """Короткое имя базы: Neon-endpoint `ep-cool-union-…` → `cool-union`."""
    match = NEON_ENDPOINT_RE.search(dsn)
    if match:
        return f"{match.group(1).lower()}-{match.group(2).lower()}"
    host = dsn_host(dsn)
    return host.split(".")[0].lower() if host else None


def _token_files() -> list[str]:
    """Файлы с токенами: актуальный и старые дампы (`leltokens2.backup-…`).

    Дампы нужны намеренно: актуальный файл чистят, и единственный след второго
    Neon-проекта (мёртвого резерва) остался как раз в дампе — без него резерв
    просто исчезал из списка, то есть «состояние резервов» было неактуальным.
    """
    return [
        os.path.join(WORKSPACE, name)
        for name in sorted(os.listdir(WORKSPACE))
        if re.fullmatch(r"leltokens.*\.txt", name)
    ]


def dsn_candidates() -> dict[str, str]:
    """Все известные DSN с понятными именами (прод первым, дальше резервы)."""
    out: dict[str, str] = {}

    def remember(label: str, dsn: str) -> None:
        dsn = dsn.strip().strip("\"'")
        if not DSN_RE.match(dsn):
            return
        if label not in out:
            out[label] = dsn
        # Короткое имя по endpoint — для ЛЮБОГО источника: база, приехавшая
        # только из хранилища (env/DPAPI), иначе не отзывалась бы на `cool-union`.
        short = dsn_label(dsn)
        if short and short not in out:
            out[short] = dsn

    # 1) то, что заведено в хранилище/окружении: current и (если есть) reserveN
    for suffix in ("", "1", "2", "3"):
        key = "DATABASE_URL" if not suffix else f"DATABASE_URL_RESERVE{suffix}"
        value = secret(key)
        if value:
            remember("current" if not suffix else f"reserve{suffix}", value)

    # 2) всё, что лежит в файлах токенов: позиционные dsn1/dsn2 + короткие имена
    seen: list[str] = []
    for path in _token_files():
        text = open(path, encoding="utf-8", errors="replace").read()
        for dsn in DSN_RE.findall(text):
            if dsn not in seen:
                seen.append(dsn)
    for idx, dsn in enumerate(seen, start=1):
        remember(f"dsn{idx}", dsn)
    return out


def resolve_target(name: str) -> str:
    if DSN_RE.match(name) or name.startswith("postgres"):
        return name
    cands = dsn_candidates()
    if name in cands:
        return cands[name]
    matches = sorted(key for key in cands if key.startswith(name.lower()))
    if len(matches) == 1:
        return cands[matches[0]]
    if matches:
        raise SystemExit(
            f"«{name}» подходит сразу к нескольким базам: {', '.join(matches)}"
        )
    known = ", ".join(sorted(cands)) or "(ни одной — проверьте secrets/ и leltokens*.txt)"
    raise SystemExit(
        f"Не знаю базу «{name}». Известные имена: {known}\n"
        "(полный DSN тоже принимается аргументом; список с маской — `reserves`)"
    )


def as_asyncpg_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


def mask_dsn(dsn: str) -> str:
    dsn = dsn.strip()
    m = re.match(r"^(?P<scheme>[a-z+]+://)(?P<user>[^:@/]*)(?::(?P<pw>[^@/]*))?@(?P<rest>.*)$", dsn)
    if not m:
        return "***"
    user = m.group("user") or "?"
    pw = ":***" if m.group("pw") else ""
    return f"{m.group('scheme')}{user}{pw}@{m.group('rest')}"


def dsn_host(dsn: str) -> str:
    m = re.search(r"@([^/?,]+)", dsn)
    if not m:
        return ""
    hostport = m.group(1)
    return hostport.split(":")[0]


# --------------------------------------------------------- alembic head -----
def local_alembic_head() -> str | None:
    """Вершина цепочки миграций по файлам репозитория (без запуска alembic)."""
    versions = os.path.join(BACKEND, "alembic", "versions")
    if not os.path.isdir(versions):
        return None
    revs: dict[str, str | None] = {}
    for name in os.listdir(versions):
        if not name.endswith(".py"):
            continue
        text = open(os.path.join(versions, name), encoding="utf-8", errors="replace").read()
        rev = re.search(r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)", text, re.M)
        down = re.search(r"^down_revision(?::[^=]*)?\s*=\s*(.*)$", text, re.M)
        if not rev:
            continue
        down_raw = (down.group(1) if down else "").strip()
        downs = re.findall(r"[\"']([^\"']+)[\"']", down_raw)
        revs[rev.group(1)] = downs[0] if downs else None
    parents = {d for d in revs.values() if d}
    heads = [r for r in revs if r not in parents]
    if len(heads) == 1:
        return heads[0]
    return None


# ------------------------------------------------------------- /api/meta ----
def fetch_meta(base: str, timeout: float = 20.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"{base}/api/meta", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError):
        return None


def host_row(name: str, base: str) -> dict:
    meta = fetch_meta(base)
    if not meta:
        return {"host": name, "url": base, "ok": False, "error": "нет ответа от /api/meta"}
    code = meta.get("code", {})
    db = meta.get("db", {})
    return {
        "host": name,
        "url": base,
        "ok": True,
        "routes": code.get("routes"),
        "fingerprint": code.get("fingerprint"),
        "code_head": code.get("alembic_head"),
        "db_provider": db.get("provider"),
        "db_host": db.get("host"),
        "db_name": db.get("name"),
        "db_rev": db.get("alembic_version"),
        "db_server": db.get("server_version"),
        "features": len(meta.get("features", []) or []),
    }


def print_hosts(rows: list[dict]) -> None:
    for r in rows:
        if not r["ok"]:
            print(f"  {r['host']:<7} ✗ {r['error']}")
            continue
        print(
            f"  {r['host']:<7} код {r['fingerprint']} · {r['routes']} путей · "
            f"миграции-код {r['code_head']}"
        )
        print(
            f"          база {r['db_provider']} · {r['db_host']} / {r['db_name']} · "
            f"миграции-БД {r['db_rev']} · фич {r['features']}"
        )


def _mask_like_meta(host: str) -> str:
    """Та же маска, что и в `/api/meta` (app/api/routes_meta.py::_mask_host):
    первый сегмент до 14 символов (+«…», если он длиннее) и два последних домена."""
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) < 2:
        return host
    head = parts[0][:14] + ("…" if len(parts[0]) > 14 else "")
    return f"{head}.{'.'.join(parts[-2:])}"


def meta_host_matches(meta_db_host: str | None, dsn: str) -> bool:
    """Сверяет замаскированный хост из /api/meta с хостом кандидата.

    /api/meta печатает хост с маской в середине (`ep-cool-union-….neon.tech`),
    поэтому маскируем хост кандидата ТОЙ ЖЕ функцией и сравниваем строки.
    Раньше здесь хватало совпадения по «neon.tech», из-за чего любая Neon-база
    считалась боевой (в `reserves` обе базы выглядели как «на неё смотрят
    хосты»).
    """
    if not meta_db_host:
        return False
    real = dsn_host(dsn).lower()
    masked = meta_db_host.lower()
    if _mask_like_meta(real) == masked:
        return True
    # Совместимость: короткая маска без «…» — сверяем видимый префикс.
    head = masked.split("…")[0].rstrip("-.")
    return bool(head) and real.startswith(head)


# ---------------------------------------------------------------- MCP -------
def mcp():
    """Ленивая загрузка CLI-клиента Amvera MCP (файл с дефисом в имени)."""
    path = os.path.join(HERE, "amvera-mcp.py")
    spec = importlib.util.spec_from_file_location("amvera_mcp_cli", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def amvera_set_env(dsn: str, extra: dict[str, str] | None = None) -> None:
    cli = mcp()
    client = cli.McpClient(cli.get_token())
    client.initialize()
    listing = cli._tool_text(
        client.call_tool("listEnvVars", {"slug": AMVERA_SLUG, "isSecret": True})
    )
    wanted = {AMVERA_ENV_NAME: dsn}
    wanted.update(extra or {})
    for key, value in wanted.items():
        match = re.search(rf"ID=(\d+) {re.escape(key)}=.*?type=(\w+)", listing)
        if not match:
            created = cli._tool_text(
                client.call_tool(
                    "createEnvVars",
                    {
                        "slug": AMVERA_SLUG,
                        "envVarsJson": json.dumps(
                            [{"name": key, "value": value, "isSecret": True, "type": "RUN"}]
                        ),
                    },
                )
            )
            print(f"  Amvera: создана переменная {key} ({created.strip()[:60]})")
            continue
        env_id, env_type = match.group(1), match.group(2)
        result = cli._tool_text(
            client.call_tool(
                "updateEnvVar",
                {
                    "slug": AMVERA_SLUG,
                    "id": int(env_id),
                    "name": key,
                    "value": value,
                    "isSecret": True,
                    "type": env_type,
                },
            )
        )
        print(f"  Amvera: {key} (ID={env_id}) обновлена — {result.strip()[:80]}")


def hf_set_secret(key: str, value: str) -> None:
    token = secret("HF_TOKEN")
    if not token:
        sys.exit("Нет HF_TOKEN (ни в env, ни в secrets/).")
    body = json.dumps({"key": key, "value": value}).encode("utf-8")
    req = urllib.request.Request(
        f"https://huggingface.co/api/spaces/{HF_REPO}/secrets",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(f"  HF: {key} обновлён (HTTP {resp.status})")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        sys.exit(f"HF отверг обновление секрета: HTTP {exc.code} {detail}")


# --------------------------------------------------------- подкоманды ------
def cmd_status(_args) -> int:
    print("Состояние хостов:")
    rows = [host_row(name, base) for name, base in HOSTS.items()]
    print_hosts(rows)
    live = [r for r in rows if r["ok"]]
    if len(live) == 2:
        same_db = live[0]["db_host"] == live[1]["db_host"]
        same_code = live[0]["fingerprint"] == live[1]["fingerprint"]
        print(
            f"\n  база одна: {'да' if same_db else 'НЕТ — хосты пишут в разные базы'}"
            f" · код одинаковый: {'да' if same_code else 'НЕТ — один хост отстал'}"
        )
    print(
        "\n  резервы:  python tools/switch-db.py reserves"
        "\n  база:     python tools/switch-db.py switch <имя>"
        "\n  вебхук:   python tools/switch-db.py webhook amvera|hf"
    )
    return 0


async def _probe_async(dsn: str) -> dict:
    import asyncpg

    conn = await asyncpg.connect(dsn=dsn, timeout=20, command_timeout=30)
    try:
        info: dict = {}
        info["server"] = await conn.fetchval("show server_version")
        info["database"] = await conn.fetchval("select current_database()")
        info["size"] = await conn.fetchval(
            "select pg_size_pretty(pg_database_size(current_database()))"
        )
        info["tables"] = await conn.fetchval(
            "select count(*) from information_schema.tables "
            "where table_schema='public' and table_type='BASE TABLE'"
        )
        row = await conn.fetchrow("select version_num from alembic_version limit 1")
        info["revision"] = row["version_num"] if row else None
        for table in (
            "users",
            "chat_messages",
            "game_profiles",
            "xp_grants",
            "user_achievements",
        ):
            try:
                info[table] = await conn.fetchval(f"select count(*) from {table}")
            except asyncpg.PostgresError:
                info[table] = None
        try:
            info["last_message"] = await conn.fetchval(
                "select max(sent_at) from chat_messages"
            )
        except asyncpg.PostgresError:
            info["last_message"] = None
        return info
    finally:
        await conn.close()


def probe_dsn(dsn: str) -> dict:
    """Read-only снимок базы. Отказ возвращается как {'error': …}, а не исключением:
    недоступный резерв — это данные для отчёта, а не падение скрипта."""
    import asyncio

    try:
        return asyncio.run(_probe_async(as_asyncpg_dsn(dsn)))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def print_probe(dsn: str, info: dict, prefix: str = "  ") -> bool:
    """Печатает состояние базы. True — база жива и схема не отстала."""
    if info.get("error"):
        print(f"{prefix}✗ база недоступна: {info['error']}")
        return False
    head = local_alembic_head()
    behind = head is not None and info["revision"] not in (head, None)
    print(f"{prefix}сервер:        PostgreSQL {info['server']}")
    print(f"{prefix}база/размер:   {info['database']} · {info['size']} · таблиц {info['tables']}")
    print(f"{prefix}миграции:      {info['revision']} (в коде: {head})")
    print(f"{prefix}users / msg:   {info['users']} / {info['chat_messages']}")
    print(
        f"{prefix}game_profiles: {info['game_profiles']} · xp_grants {info['xp_grants']} "
        f"· ачивки {info['user_achievements']}"
    )
    print(f"{prefix}последнее сообщение: {info['last_message']}")
    print(
        f"{prefix}вердикт: "
        + (
            "⚠️ схема отстала — переключать только через `--migrate`"
            if behind
            else "✅ база живая"
        )
    )
    return not behind


def cmd_check(args) -> int:
    if args.target == "--list" or getattr(args, "list", False):
        print("Известные кандидаты:")
        for name, dsn in dsn_candidates().items():
            print(f"  {name:<16} {mask_dsn(dsn)}")
        return 0
    _ensure_asyncpg()
    dsn = resolve_target(args.target)
    print(f"Проверяю кандидата {args.target}: {mask_dsn(dsn)}\n")
    ok = print_probe(dsn, probe_dsn(dsn))
    if not ok:
        print("\nКандидат НЕ готов. Переключение отменено.")
        return 1
    return 0


def cmd_reserves(_args) -> int:
    """Состояние всех известных баз — «актуализировать резервы» одним экраном."""
    _ensure_asyncpg()
    groups: dict[str, list[str]] = {}
    for name, dsn in dsn_candidates().items():
        groups.setdefault(dsn, []).append(name)
    if not groups:
        print("Не нашёл ни одного DSN: ни в secrets/, ни в leltokens*.txt.")
        return 1

    hosts = [host_row(name, base) for name, base in HOSTS.items()]
    print(f"Известные базы: {len(groups)}\n")
    alive = 0
    for idx, (dsn, aliases) in enumerate(groups.items(), start=1):
        watching = [h["host"] for h in hosts if h["ok"] and meta_host_matches(h["db_host"], dsn)]
        print(f"  {idx}) {', '.join(aliases)}")
        print(f"     {mask_dsn(dsn)}")
        if print_probe(dsn, probe_dsn(dsn), prefix="     "):
            alive += 1
        if watching:
            print(f"     ← на неё смотрят боевые хосты: {', '.join(watching)}")
        print()
    print(f"Живых баз: {alive} из {len(groups)}")
    print(
        "Переключить базу:   python tools/switch-db.py switch <имя>\n"
        "Переключить вебхук: python tools/switch-db.py webhook amvera|hf"
    )
    return 0


def cmd_switch(args) -> int:
    dsn = resolve_target(args.target)
    print(f"Кандидат: {mask_dsn(dsn)}\n")

    if not args.skip_check:
        rc = cmd_check(argparse.Namespace(target=args.target, list=False))
        if rc != 0:
            return rc
    if args.migrate:
        print("\nМигрирую кандидата до head…")
        env = dict(os.environ)
        env["DATABASE_URL"] = dsn
        for key in ("BOT_TOKEN", "TG_WEBHOOK_SECRET", "MINI_APP_URL"):
            if secret(key):
                env.setdefault(key, secret(key) or "")
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
        )
        print((proc.stdout + proc.stderr).strip()[:1500])
        if proc.returncode != 0:
            sys.exit("Миграция не прошла — переключение отменено.")

    if not args.yes:
        answer = input(
            f"\nПоменять DATABASE_URL у обоих хостов (Amvera + HF) на "
            f"{mask_dsn(dsn)}?\nВведите 'да' для подтверждения: "
        ).strip().lower()
        if answer not in {"да", "yes", "y", "д"}:
            print("Отменено.")
            return 1

    extra = {"DB_SSL": args.db_ssl} if args.db_ssl else None
    print("\n1) Переменные окружения")
    amvera_set_env(dsn, extra)
    hf_set_secret(AMVERA_ENV_NAME, dsn)
    if extra:
        hf_set_secret("DB_SSL", args.db_ssl)

    print("\n2) Перезапуск (HF перезапускается сам при смене секрета)")
    cli = mcp()
    client = cli.McpClient(cli.get_token())
    client.initialize()
    print("  Amvera:", cli._tool_text(client.call_tool("restartProject", {"slug": AMVERA_SLUG})).strip())

    print("\n3) Ожидание, пока оба хоста подтвердят новую базу…")
    deadline = time.time() + args.timeout
    rows: list[dict] = []
    while time.time() < deadline:
        rows = [host_row(name, base) for name, base in HOSTS.items()]
        good = [
            r
            for r in rows
            if r["ok"] and meta_host_matches(r["db_host"], dsn) and r["db_rev"] == r["code_head"]
        ]
        if len(good) == len(HOSTS):
            break
        time.sleep(10)

    print()
    print_hosts(rows)
    ok = all(
        r["ok"] and meta_host_matches(r["db_host"], dsn) and r["db_rev"] == r["code_head"]
        for r in rows
    )
    print()
    if ok:
        print("✅ Готово: оба хоста видят базу " + mask_dsn(dsn))
        return 0
    print("⚠️ Не все хосты подтвердили переключение — смотрите таблицу выше.")
    print("   Если хост отдаёт 503, он мог не подняться на новой базе: проверьте")
    print("   логи (`tools/amvera-mcp.py call getRunLogs …`) и при необходимости")
    print("   поставьте DB_SSL=disable — см. docs/DB_CHOICE.md.")
    return 1


def cmd_webhook(args) -> int:
    """Перевести вебхук бота на хост.

    Вебхук у бота один, так что активный бэкенд — это тот, на который он смотрит
    (база и бот-токен у хостов общие). Прошлые .bat собирали эту ссылку руками
    (с `^&` внутри кавычек и захардкоженными токенами) — здесь се же строит сам
    скрипт по urlencode, а токены берёт из хранилища.
    """
    token = secret("BOT_TOKEN")
    secret_token = secret("TG_WEBHOOK_SECRET")
    if not token:
        sys.exit(secrets_hint("BOT_TOKEN"))
    if not secret_token:
        sys.exit(
            "Вебхук без secret_token не годится: приложение отбросит такие апдейты.\n"
            + secrets_hint("TG_WEBHOOK_SECRET")
        )
    expected = f"{HOSTS[args.target]}/tg/webhook"

    # Не переключаем вебхук на хост, который не отвечает: бот просто зависнет
    # (апдейты будут копиться в очереди Telegram). `--force` — если очень надо.
    if not fetch_meta(HOSTS[args.target]):
        if not getattr(args, "force", False):
            sys.exit(
                f"{args.target} не отвечает на /api/meta — вебхук не переключаю.\n"
                "  Живы ли хосты:   python tools/switch-db.py status\n"
                "  Всё равно перевести: добавьте --force"
            )
        print(f"⚠️ {args.target} не отвечает на /api/meta — перевожу всё равно (--force).\n")

    params = urllib.parse.urlencode(
        {
            "url": expected,
            "secret_token": secret_token,
            "drop_pending_updates": "false",
        }
    )
    print(f"Перевожу вебхук на {args.target}: {expected}\n")
    with urllib.request.urlopen(
        f"https://api.telegram.org/bot{token}/setWebhook?{params}", timeout=30
    ) as resp:
        answer = json.loads(resp.read().decode("utf-8", "replace"))
    if not answer.get("ok"):
        sys.exit(f"Telegram отверг setWebhook: {json.dumps(answer, ensure_ascii=False)}")

    with urllib.request.urlopen(
        f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=30
    ) as resp:
        info = json.loads(resp.read().decode("utf-8", "replace")).get("result", {})
    url = (info.get("url") or "").rstrip("/")
    print(f"  вебхук:    {url or '(пусто — бот не получает апдейты)'}")
    print(f"  в очереди: {info.get('pending_update_count')} апдейт(ов)")
    if info.get("last_error_message"):
        print(f"  ⚠️ последняя ошибка доставки: {info['last_error_message']}")
    if url != expected.rstrip("/"):
        print(f"\n⚠️ Telegram записал другой адрес — ожидался {expected}")
        return 1
    print(f"\n✅ Бот переведён на {args.target}: апдейты уходят на {url}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="switch-db.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="что сейчас у обоих хостов")
    p_status.set_defaults(func=cmd_status)

    p_reserves = sub.add_parser(
        "reserves", help="состояние всех известных баз (включая мёртвые резервы)"
    )
    p_reserves.set_defaults(func=cmd_reserves)

    p_check = sub.add_parser("check", help="проверить кандидата до переключения")
    p_check.add_argument("target", nargs="?", default="--list", help="имя базы или сам DSN")
    p_check.add_argument("--list", action="store_true", help="показать известные базы")
    p_check.set_defaults(func=cmd_check)

    p_switch = sub.add_parser("switch", help="переключить оба хоста и подтвердить")
    p_switch.add_argument("target")
    p_switch.add_argument("--db-ssl", choices=["auto", "require", "disable"], default=None)
    p_switch.add_argument("--migrate", action="store_true", help="сначала прогнать alembic upgrade head")
    p_switch.add_argument("--skip-check", action="store_true", help="не проверять кандидата")
    p_switch.add_argument("--yes", "-y", action="store_true", help="без вопроса")
    p_switch.add_argument("--timeout", type=int, default=300, help="сколько ждать подтверждения, сек")
    p_switch.set_defaults(func=cmd_switch)

    for alias in ("webhook", "backend"):
        p_hook = sub.add_parser(
            alias, help="перевести вебхук Telegram на хост (`backend` — то же самое)"
        )
        p_hook.add_argument("target", choices=sorted(HOSTS))
        p_hook.add_argument(
            "--force", action="store_true", help="переводить даже если хост не отвечает"
        )
        p_hook.set_defaults(func=cmd_webhook)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
