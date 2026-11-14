#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Проверка точки отката и взаимозаменяемости баз — «настоящий» rehearsal.

Зачем отдельный инструмент. `tools/backup-db.py` снимает и заливает дамп, но
проверить восстановление по-настоящему можно только так: поднять **пустую**
базу, залить в неё дамп и сверить содержимое с боевой. Логическая проверка
(«файлы на месте, хэши совпали, порядок FK корректен») этого не заменяет: она
ничего не говорит о том, что данные действительно вернулись.

Что здесь есть:

  info                     — что за базы вообще есть в `leltokens2.txt`:
                             маскированный хост, версия сервера, версия
                             миграций, таблиц, строк. Плюс какая из них боевая
                             (сверяем с `/api/meta` живого хоста).
  snapshot -o FILE         — канонический слепок всех таблиц базы: по таблице
                             мультимножество хэшей строк (порядок не важен,
                             поэтому слепок не зависит от плана запроса).
  compare A B              — сравнить два слепка: расхождения по таблицам,
                             сколько строк только слева / только справа.
                             Это и есть ответ на «данные совпадают?».
  rehearse DIR             — полный цикл: создать scratch-базу на резервном
                             инстансе, `alembic upgrade head`, залить дамп,
                             снять слепки боевой и scratch, сравнить, убрать за
                             собой (`--keep` — оставить для разбора).
  rehearse-local DIR       — то же, но в ОДНОРАЗОВОМ Postgres в Docker: боевую
                             инфраструктуру не трогаем вообще (нужен docker).
  cutover DIR              — репетиция переезда: две одноразовые базы (цель и
                             база отката), дамп в каждую, живое приложение
                             поверх цели и поверх отката. Отвечает на вопрос
                             «переезд обратим?», а не только «дамп цел?».
  check DIR --dsn DSN      — сверить восстановленную базу с дампом (для CI:
                             сервисный Postgres уже поднят, нужен только ответ
                             «совпало или нет»).

Почему не `pg_dump | psql`: ни `pg_dump`, ни `psql` на машине нет, а тянуть их
ради десятимегабайтной базы незачем. Плюс scratch-база на том же движке и с тем
же SSL, что у боевой, — то есть проверяем ровно тот сценарий, который случится
в аварии.

Пароли не печатаются никогда: любой DSN проходит через `_mask`.

Запуск (скрипт сам перезапустится на venv бэкенда, где есть asyncpg):

    python tools/db-rehearsal.py info
    python tools/db-rehearsal.py rehearse backups/2026-09-29_185244
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(HERE)
BACKEND = os.path.join(WORKSPACE, "backend")
# Реестр баз лежит в корне монорепо — на уровень выше репозитория. Его
# может не быть (CI, чистая машина): тогда работает только DSN из env.
TOKENS = os.path.join(os.path.dirname(WORKSPACE), "leltokens2.txt")
LIVE_HOSTS = (
    "https://meetup-planner-youmakemefry.waw0.amvera.tech",
    "https://fryesw-meetup-planner-backend.hf.space",
)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# ------------------------------------------------------------- окружение ----
def _venv_python() -> str | None:
    for rel in ("Scripts/python.exe", "bin/python"):
        path = os.path.join(BACKEND, ".venv", *rel.split("/"))
        if os.path.exists(path):
            return path
    return None


def _ensure_asyncpg() -> None:
    if importlib.util.find_spec("asyncpg") is not None:
        return
    venv = _venv_python()
    if venv and os.path.abspath(sys.executable) != os.path.abspath(venv):
        os.execv(venv, [venv, os.path.abspath(__file__), *sys.argv[1:]])
    sys.exit("Нужен asyncpg: запустите питоном из backend/.venv")


def _load_backup_tool():
    """Подключаем `backup-db.py` как модуль (в имени дефис) — кодировщик строк
    должен быть ОДИН на оба инструмента, иначе слепки несовместимы."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("ghg_backup_db", os.path.join(HERE, "backup-db.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_backup = _load_backup_tool()
_enc = _backup._enc
_dec = _backup._dec


def _mask(dsn: str) -> str:
    return re.sub(r"://([^:@/]*):[^@]*@", r"://\1:***@", dsn)


def _parts(dsn: str) -> dict[str, str]:
    """host/port/user/db из DSN без печати секретов."""
    m = re.match(r"postgres(?:ql)?(?:\+asyncpg)?://([^@]*)@([^/]+)/(.*)", dsn)
    if not m:
        return {"host": "?", "user": "?", "db": "?"}
    userinfo, hostport, db = m.groups()
    user = userinfo.split(":")[0]
    host, _, port = hostport.partition(":")
    return {
        "host": host,
        "port": port or "5432",
        "user": user,
        "db": db.split("?")[0],
    }


def _read_dsns() -> list[str]:
    """Все DSN из leltokens2.txt в порядке появления (файл в cp1251).

    Нечётный файл — но другого реестра секретов в проекте нет, а `secrets/`
    хранит значения по одному имени. Поэтому реестр «сколько баз и какие» —
    именно этот файл: он же человекочитаемый список для владельца.
    """
    if not os.path.exists(TOKENS):
        if found:
            return found
        sys.exit(f"Нет {TOKENS}")
    text = open(TOKENS, "rb").read().decode("cp1251", "replace")
    found: list[str] = []
    # Окружение — первым: именно из него работает боевой контур (и CI).
    # `leltokens2.txt` — человекочитаемый реестр, он отстаёт: 03.11.2026 в нём
    # лежал DSN базы на миграции 0028, пока боевая ушла на 0067. Дамп «не той
    # базы» — худший вид бэкапа, поэтому порядок источников важен.
    for key in ("BACKUP_DATABASE_URL", "DATABASE_URL"):
        value = (os.environ.get(key) or "").strip()
        if value and value not in found:
            found.append(value)
    for raw in re.findall(r"postgres(?:ql)?(?:\+asyncpg)?://\S+", text):
        dsn = raw.rstrip(".,;")
        if dsn not in found:
            found.append(dsn)
    return found


def _live_db_host() -> str | None:
    """Маскированный хост боевой базы из /api/meta (без секретов)."""
    for base in LIVE_HOSTS:
        try:
            with urllib.request.urlopen(f"{base}/api/meta", timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 — хост может быть недоступен, это не ошибка
            continue
        host = (data.get("db") or {}).get("host")
        if host:
            return str(host)
    return None


def _is_prod(dsn: str, live_host: str | None) -> bool:
    """Совпадает ли DSN с боевой базой. `/api/meta` отдаёт хост замаскированным
    (`ep-cool-union-….neon.tech`), поэтому сравниваем по префиксу до '…'."""
    if not live_host:
        return False
    prefix = live_host.split("…")[0].split("...")[0]
    return bool(prefix) and _parts(dsn)["host"].startswith(prefix)


# --------------------------------------------------------- канонический вид --
def _canon(record: dict[str, Any]) -> str:
    """Канонический вид строки. Кодировщик берём тот же, что у `backup-db.py`:
    иначе дамп (где NUMERIC хранится строкой) не сойдётся с живой базой, где тот
    же NUMERIC вернётся как Decimal. `_enc` с обоих сторон убирает этот зазор."""
    return json.dumps(
        {k: _enc(v) for k, v in record.items()},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def row_digest(record: Any) -> str:
    return hashlib.sha1(_canon(dict(record)).encode("utf-8")).hexdigest()


def _digest_of(digests: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(digests)).encode("utf-8")).hexdigest()


def dump_snapshot(path: str) -> dict[str, Any]:
    """Слепок ДАМПА (а не боевой базы). Сверять восстановленное нужно именно
    с ним: боевая база живёт и пишется, поэтому любое сравнение с ней ловит не
    дефект восстановления, а свежие записи."""
    import gzip

    out: dict[str, Any] = {"tables": {}}
    for name in sorted(os.listdir(path)):
        if not name.endswith(".jsonl.gz"):
            continue
        table = name[: -len(".jsonl.gz")]
        digests: list[str] = []
        with gzip.open(os.path.join(path, name), "rt", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                digests.append(hashlib.sha1(_canon(_dec(json.loads(line))).encode("utf-8")).hexdigest())
        out["tables"][table] = {
            "rows": len(digests),
            "sha256": _digest_of(digests),
            "hashes": sorted(digests),
        }
    out["total_rows"] = sum(t["rows"] for t in out["tables"].values())
    out["tables_count"] = len(out["tables"])
    manifest = os.path.join(path, "manifest.json")
    if os.path.exists(manifest):
        meta = json.load(open(manifest, encoding="utf-8"))
        out["at"] = meta.get("created_at")
        out["revision"] = meta.get("revision")
    return out


async def _tables(conn) -> list[str]:
    return [
        r["table_name"]
        for r in await conn.fetch(
            "select table_name from information_schema.tables "
            "where table_schema='public' and table_type='BASE TABLE' order by table_name"
        )
    ]


async def snapshot(conn) -> dict[str, Any]:
    """Мультимножество хэшей строк по каждой таблице. Порядок строк не важен —
    именно поэтому слепок не зависит от плана запроса и годится для сверки двух
    баз между собой."""
    tables = await _tables(conn)
    out: dict[str, Any] = {"tables": {}}
    for name in tables:
        rows = await conn.fetch(f'select * from "{name}"')
        digests = sorted(row_digest(r) for r in rows)
        out["tables"][name] = {
            "rows": len(digests),
            "sha256": _digest_of(digests),
            "hashes": digests,
        }
    out["total_rows"] = sum(t["rows"] for t in out["tables"].values())
    out["tables_count"] = len(tables)
    return out


def _ssl_for(dsn: str) -> bool | None:
    """SSL аргументом, а не в DSN: локальному контейнеру он не нужен."""
    host = _parts(dsn)["host"].lower()
    if "localhost" in host or "127.0.0.1" in host or host == "::1":
        return False
    return None


async def connect(dsn: str):
    import asyncpg

    kwargs: dict = {}
    ssl_value = _ssl_for(dsn)
    if ssl_value is not None:
        kwargs["ssl"] = ssl_value
    return await asyncpg.connect(
        dsn=dsn.replace("postgresql+asyncpg://", "postgresql://"),
        timeout=30,
        command_timeout=900,
        **kwargs,
    )


def compare(a: dict[str, Any], b: dict[str, Any]) -> int:
    names = sorted(set(a["tables"]) | set(b["tables"]))
    bad = 0
    for name in names:
        ta = a["tables"].get(name)
        tb = b["tables"].get(name)
        if ta is None or tb is None:
            bad += 1
            print(f"  ✗ {name:<28} есть только в одной базе")
            continue
        if ta["sha256"] == tb["sha256"]:
            print(f"  ✓ {name:<28} {ta['rows']:>6} строк — совпало")
            continue
        ca, cb = collections.Counter(ta["hashes"]), collections.Counter(tb["hashes"])
        only_a = sum((ca - cb).values())
        only_b = sum((cb - ca).values())
        bad += 1
        print(
            f"  ✗ {name:<28} A={ta['rows']} B={tb['rows']} "
            f"только в A={only_a} только в B={only_b}"
        )
    return bad


# ------------------------------------------------------------------ команды --
async def cmd_info(args) -> int:
    live = _live_db_host()
    print(f"Боевая база по /api/meta: {live or 'не удалось узнать'}\n")
    dsns = _read_dsns()
    for i, dsn in enumerate(dsns, 1):
        p = _parts(dsn)
        mark = " ← БОЕВАЯ" if _is_prod(dsn, live) else ""
        print(f"[{i}] {_mask(dsn)}{mark}")
        try:
            conn = await connect(dsn)
        except Exception as exc:  # noqa: BLE001
            print(f"    недоступна: {type(exc).__name__}: {str(exc)[:120]}\n")
            continue
        try:
            ver = await conn.fetchval("show server_version")
            rev = await conn.fetchval("select version_num from alembic_version")
            tables = await _tables(conn)
            rows = 0
            for name in tables:
                rows += await conn.fetchval(f'select count(*) from "{name}"')
            size = await conn.fetchval("select pg_size_pretty(pg_database_size(current_database()))")
            print(
                f"    {p['user']}@{p['host']}/{p['db']} · PG {ver} · миграции {rev}\n"
                f"    таблиц {len(tables)} · строк {rows} · размер {size}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"    ошибка чтения: {type(exc).__name__}: {str(exc)[:160]}")
        finally:
            await conn.close()
        print()
    return 0


async def _snapshot_dsn(dsn: str, path: str) -> dict[str, Any]:
    conn = await connect(dsn)
    try:
        data = await snapshot(conn)
    finally:
        await conn.close()
    data["dsn"] = _mask(dsn)
    data["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    return data


async def cmd_snapshot(args) -> int:
    dsns = _read_dsns()
    dsn = dsns[args.dsn_index - 1] if args.dsn_index else dsns[0]
    data = await _snapshot_dsn(dsn, args.out)
    print(
        f"Слепок {_mask(dsn)}\n  таблиц {data['tables_count']} · строк {data['total_rows']}\n"
        f"  → {args.out}"
    )
    return 0


def cmd_compare(args) -> int:
    a = json.load(open(args.a, encoding="utf-8"))
    b = json.load(open(args.b, encoding="utf-8"))
    print(f"A: {a.get('dsn')} ({a.get('at')})\nB: {b.get('dsn')} ({b.get('at')})\n")
    bad = compare(a, b)
    if bad == 0:
        print(f"\n✅ Содержимое совпадает: {a['total_rows']} строк, таблиц {a['tables_count']}")
        return 0
    print(f"\n⚠️ Расхождений по таблицам: {bad}")
    return 1


def _alembic_env(dsn: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "DATABASE_URL": dsn,
            "BOT_TOKEN": env.get("BOT_TOKEN") or "0:rehearsal",
            "TG_WEBHOOK_SECRET": env.get("TG_WEBHOOK_SECRET") or "rehearsal",
            "MINI_APP_URL": env.get("MINI_APP_URL") or "https://rehearsal.invalid",
        }
    )
    return env


def _run(cmd: list[str], env: dict[str, str], label: str) -> None:
    print(f"  $ {label}")
    proc = subprocess.run(
        cmd, env=env, cwd=BACKEND, capture_output=True, text=True, timeout=1200
    )
    tail = (proc.stdout or "").strip().splitlines()[-6:]
    for line in tail:
        print(f"      {line}")
    if proc.returncode != 0:
        print((proc.stderr or "")[-1500:])
        raise SystemExit(f"✗ Шаг «{label}» упал с кодом {proc.returncode}")


async def cmd_rehearse(args) -> int:
    import asyncpg

    dsns = _read_dsns()
    live = _live_db_host()
    prod = next((d for d in dsns if _is_prod(d, live)), None)
    if prod is None:
        if not args.prod_index:
            sys.exit(
                "Не понял, какая база боевая: /api/meta недоступен. "
                "Укажите --prod-index N (см. `info`)."
            )
        prod = dsns[args.prod_index - 1]
    others = [d for d in dsns if d != prod]
    same_instance = not others
    if same_instance:
        # Отдельного инстанса под scratch нет (в реестре один DSN). Создаём
        # scratch-базу на ТОМ ЖЕ инстансе: это всё ещё пустая база, которую
        # строит alembic и наполняет дамп, то есть проверка восстановления
        # настоящая. Чего она не проверяет — независимость от провайдера.
        print(
            "⚠️  В leltokens2.txt только один DSN: scratch-база поднимется на том же\n"
            "    инстансе. Восстановление дампа проверяется, отказоустойчивость — нет.\n"
        )
        scratch_root = prod
    else:
        scratch_root = others[(args.scratch_index or 1) - 1]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dump_path = os.path.abspath(args.path)   # steps run with cwd=BACKEND
    name = f"ghg_rehearsal_{stamp}"
    root_parts = _parts(scratch_root)
    scratch = re.sub(
        rf"(://[^@]*@[^/]+/)[^?]*", rf"\g<1>{name}", scratch_root
    )
    prod_parts = _parts(prod)

    print("Проверка точки отката\n" + "=" * 60)
    print(f"дамп      : {dump_path}")
    print(f"боевая    : {prod_parts['user']}@{prod_parts['host']}/{prod_parts['db']}  ({_mask(prod)})")
    print(f"scratch   : {root_parts['user']}@{root_parts['host']}/{name}")
    if same_instance:
        print("            (на том же инстансе, что боевая — отдельная ПУСТАЯ база)")
    print("=" * 60)

    admin = await asyncpg.connect(
        dsn=scratch_root.replace("postgresql+asyncpg://", "postgresql://"),
        timeout=30,
        command_timeout=600,
    )
    try:
        await admin.execute(f'create database "{name}"')
        print(f"\n1. Создана пустая база {name}")
    finally:
        await admin.close()

    scratch_dsn = scratch.replace("postgresql://", "postgresql+asyncpg://")
    ok = False
    try:
        venv = _venv_python() or sys.executable
        print("\n2. Миграции на пустой базе (alembic upgrade head)")
        _run(
            [venv, "-m", "alembic", "upgrade", "head"],
            _alembic_env(scratch_dsn),
            "alembic upgrade head",
        )

        print("\n3. Заливка дампа")
        _run(
            [sys.executable, os.path.join(HERE, "backup-db.py"), "restore", dump_path, "--yes"],
            _alembic_env(scratch_dsn),
            "backup-db.py restore",
        )

        print("\n4. Слепки")
        stamp_out = os.path.join(args.out, name)
        dump_snap = dump_snapshot(dump_path)
        prod_snap = await _snapshot_dsn(prod, f"{stamp_out}_prod.json")
        scratch_snap = await _snapshot_dsn(scratch_dsn, f"{stamp_out}_scratch.json")
        scratch_snap["dsn"] = f"ghg_rehearsal (из {dump_path})"
        with open(f"{stamp_out}_dump.json", "w", encoding="utf-8") as fh:
            json.dump(dump_snap, fh, ensure_ascii=False)
        print(f"   дамп    : {dump_snap['total_rows']} строк / {dump_snap['tables_count']} таблиц")
        print(f"   scratch : {scratch_snap['total_rows']} строк / {scratch_snap['tables_count']} таблиц")
        print(f"   боевая  : {prod_snap['total_rows']} строк / {prod_snap['tables_count']} таблиц (живая)")

        print("\n5. Сверка: восстановленное против ДАМПА (это и есть проверка отката)")
        bad = compare(dump_snap, scratch_snap)
        ok = bad == 0

        print("\n6. Дрейф боевой базы с момента снятия дампа (не ошибка — просто жизнь)")
        drifted = []
        for table, info in sorted(prod_snap["tables"].items()):
            dumped = dump_snap["tables"].get(table)
            if dumped is None:
                continue
            if info["sha256"] == dumped["sha256"]:
                continue
            new_rows = collections.Counter(info["hashes"]) - collections.Counter(dumped["hashes"])
            drifted.append((table, sum(new_rows.values()), info["rows"] - dumped["rows"]))
        if not drifted:
            print("   боевая база не изменилась с момента дампа — сверка точная, без оговорок")
        else:
            for table, changed, delta in drifted:
                print(f"   · {table:<24} +{max(delta, 0)} строк, изменено {changed}")
            print(
                f"   итого таблиц {len(drifted)} — это записи, появившиеся ПОСЛЕ "
                f"{dump_snap.get('at') or 'снятия дампа'}"
            )

        print()
        if ok:
            print("✅ ВОССТАНОВЛЕНИЕ ПОДТВЕРЖДЕНО")
            print(
                f"   Из дампа поднято {scratch_snap['total_rows']} строк "
                f"({scratch_snap['tables_count']} таблиц) — без потерь и без лишнего:"
            )
            print("   слепок восстановленной базы совпал со слепком дампа по каждой таблице.")
            print("   Значит, дамп действительно является точкой отката: тем, что можно залить")
            print("   в пустую базу и получить рабочее состояние.")
        else:
            print(f"⚠️ ОТКАТ НЕ ПОДТВЕРЖДЁН: расхождений по таблицам — {bad}")
        print(f"\n   слепки: {stamp_out}_dump.json\n           {stamp_out}_scratch.json\n           {stamp_out}_prod.json")
    finally:
        if args.keep:
            print(f"\n(--keep) scratch-база оставлена: {name} на {root_parts['host']}")
        else:
            admin = await asyncpg.connect(
                dsn=scratch_root.replace("postgresql+asyncpg://", "postgresql://"),
                timeout=30,
                command_timeout=600,
            )
            try:
                await admin.execute(f'drop database if exists "{name}" with (force)')
                print(f"\n6. Scratch-база {name} удалена")
            finally:
                await admin.close()
    return 0 if ok else 1


DOCKER_IMAGE = "postgres:16-alpine"


def _docker(*args: str, **kwargs) -> subprocess.CompletedProcess:
    """Вызов docker с человеческой ошибкой вместо трейсбека."""
    try:
        return subprocess.run(
            ["docker", *args], capture_output=True, text=True, **kwargs
        )
    except FileNotFoundError:
        sys.exit("Docker не найден: для rehearse-local нужен docker в PATH.")


def _wait_postgres(name: str, seconds: int = 90) -> None:
    """Ждать готовности контейнера фактом `pg_isready`, а не паузой."""
    deadline = datetime.now().timestamp() + seconds
    while datetime.now().timestamp() < deadline:
        probe = _docker(
            "exec", name, "pg_isready", "-U", "postgres", "-d", "rehearsal"
        )
        if probe.returncode == 0:
            return
        time.sleep(1)
    sys.exit(f"Postgres в контейнере {name} не поднялся за {seconds} с.")


async def cmd_rehearse_local(args) -> int:
    """Восстановить дамп в одноразовый Postgres и сверить с дампом.

    Зачем Docker, а не scratch-база на боевом инстансе: проверка восстановления
    не должна требовать прав на боевой сервер и не должна оставлять на нём
    мусор, если прогон прервётся. Одноразовый контейнер либо есть, либо его
    нет; данных боевой базы он не касается.
    """
    import asyncio
    import gzip  # noqa: F401 - нужен для dump_snapshot ниже
    import socket

    dump_path = os.path.abspath(args.path)
    if not os.path.isdir(dump_path):
        sys.exit(f"Нет каталога дампа: {dump_path}")
    dump_snap = dump_snapshot(dump_path)
    print(f"Дамп: {dump_snap['total_rows']} строк / {dump_snap['tables_count']} таблиц")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    name = f"ghg-rehearsal-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    start = _docker(
        "run", "-d", "--rm", "--name", name,
        "-e", "POSTGRES_PASSWORD=rehearsal",
        "-e", "POSTGRES_DB=rehearsal",
        "-p", f"127.0.0.1:{port}:5432",
        DOCKER_IMAGE,
    )
    if start.returncode != 0:
        sys.exit((start.stderr or start.stdout or "docker run failed")[-800:])
    # `ssl=disable` обязателен: у контейнера нет сертификата, а asyncpg по
    # умолчанию пытается SSL и падает на «rejected SSL upgrade». Прод-база
    # наоборот требует SSL — поэтому параметр задаётся здесь явно, а не
    # глобально.
    # Без query-параметров: SSL для локальной базы решает `connect()` (см.
    # `_ssl_for`). asyncpg не принимает `ssl` в DSN — он становится
    # runtime-параметром и падает с «parameter ssl cannot be changed now».
    scratch = f"postgresql+asyncpg://postgres:rehearsal@127.0.0.1:{port}/rehearsal"
    ok = False
    try:
        _wait_postgres(name)
        print(f"1. Postgres {DOCKER_IMAGE} поднят на 127.0.0.1:{port}")

        venv = _venv_python() or sys.executable
        # До ревизии дампа, а не до head: иначе колонки, добавленные позже,
        # заполнятся `server_default` и сверка покажет ложное расхождение.
        rev = dump_snap.get("revision") or "head"
        print(f"2. Миграции на пустой базе (alembic upgrade {rev})")
        _run(
            [venv, "-m", "alembic", "upgrade", rev],
            _alembic_env(scratch),
            f"alembic upgrade {rev}",
        )

        print("3. Заливка дампа")
        _run(
            [sys.executable, os.path.join(HERE, "backup-db.py"), "restore", dump_path, "--yes"],
            _alembic_env(scratch),
            "backup-db.py restore",
        )

        print("4. Сверка восстановленного с дампом")
        conn = await connect(scratch)
        try:
            restored = await snapshot(conn)
        finally:
            await conn.close()
        bad = compare(dump_snap, restored)
        ok = bad == 0
        print()
        if ok:
            print("✅ ВОССТАНОВЛЕНИЕ ПОДТВЕРЖДЕНО")
            print(
                f"   {restored['total_rows']} строк / {restored['tables_count']} таблиц "
                "совпали с дампом по каждой таблице."
            )
        else:
            print(f"⚠️ ОТКАТ НЕ ПОДТВЕРЖДЁН: расхождений по таблицам — {bad}")
    finally:
        _docker("rm", "-f", name)
        print(f"\n5. Контейнер {name} удалён")
    return 0 if ok else 1


async def cmd_check(args) -> int:
    """Сверить базу по DSN с дампом (без восстановления: оно уже сделано)."""
    dump_snap = dump_snapshot(os.path.abspath(args.path))
    conn = await connect(args.dsn)
    try:
        actual = await snapshot(conn)
    finally:
        await conn.close()
    bad = compare(dump_snap, actual)
    if bad == 0:
        print(f"\n✅ Восстановленная база совпала с дампом: {actual['total_rows']} строк")
        return 0
    print(f"\n⚠️ Расхождений по таблицам: {bad}")
    return 1


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_pg_container(name: str, port: int) -> None:
    """Поднять одноразовый Postgres — эмуляция целевой базы у провайдера."""
    start = _docker(
        "run", "-d", "--rm", "--name", name,
        "-e", "POSTGRES_PASSWORD=rehearsal",
        "-e", "POSTGRES_DB=rehearsal",
        "-p", f"127.0.0.1:{port}:5432",
        DOCKER_IMAGE,
    )
    if start.returncode != 0:
        sys.exit((start.stderr or start.stdout or "docker run failed")[-800:])
    _wait_postgres(name)


def _local_dsn(port: int) -> str:
    return f"postgresql+asyncpg://postgres:rehearsal@127.0.0.1:{port}/rehearsal"


def _http_json(url: str, timeout: float = 5.0) -> tuple[int | None, dict | None]:
    """GET и JSON, без падения на 4xx/5xx: код ответа — тоже результат."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 — тело может быть пустым или не JSON
            return exc.code, None
    except Exception:  # noqa: BLE001 — порт ещё не слушает
        return None, None


def _spawn_app(dsn: str, port: int) -> tuple[subprocess.Popen, str]:
    """Настоящее приложение против конкретной базы — «пускают ли в него трафик»."""
    import tempfile

    log_path = os.path.join(tempfile.gettempdir(), f"cutover-app-{port}.log")
    handle = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            _venv_python() or sys.executable,
            "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        cwd=BACKEND,
        env=_alembic_env(dsn),
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    return proc, log_path


def _stop_app(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _app_probe(dsn: str, port: int, label: str) -> dict[str, Any]:
    """Поднять приложение на базе и спросить его о готовности."""
    proc, log_path = _spawn_app(dsn, port)

    def tail() -> str:
        try:
            return open(log_path, encoding="utf-8").read()[-1500:]
        except OSError:
            return ""

    try:
        deadline = time.monotonic() + 120
        while True:
            if proc.poll() is not None:
                raise SystemExit(f"✗ {label}: приложение упало.\n{tail()}")
            status, _ = _http_json(f"http://127.0.0.1:{port}/healthz")
            if status == 200:
                break
            if time.monotonic() > deadline:
                raise SystemExit(f"✗ {label}: /healthz не ответил за 120 с.\n{tail()}")
            time.sleep(0.5)

        ready_status, ready = None, None
        for _ in range(120):
            ready_status, ready = _http_json(f"http://127.0.0.1:{port}/readyz")
            if ready_status == 200:
                break
            time.sleep(0.5)
        _, meta = _http_json(f"http://127.0.0.1:{port}/api/meta")
        return {"ready_status": ready_status, "ready": ready or {}, "meta": meta or {}}
    finally:
        _stop_app(proc)


async def cmd_cutover(args) -> int:
    """Репетиция переезда: цель, данные, живое приложение, откат.

    Чем отличается от `rehearse-local`. Тот отвечает на вопрос «дамп — это
    рабочая точка отката?». Этот — на вопрос переезда: поднимется ли
    приложение на новой базе и можно ли вернуться на прежнюю, если что-то не
    так. Работает в двух одноразовых контейнерах: «цель» и «база отката»,
    обе получают дамп, поверх каждой поднимается настоящее приложение.
    """
    dump_path = os.path.abspath(args.path)
    if not os.path.isdir(dump_path):
        sys.exit(f"Нет каталога дампа: {dump_path}")
    dump_snap = dump_snapshot(dump_path)
    print(
        f"Дамп: {dump_snap['total_rows']} строк / {dump_snap['tables_count']} таблиц, "
        f"ревизия {dump_snap.get('revision') or '—'}"
    )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    names = {
        "target": f"ghg-cutover-target-{stamp}",
        "rollback": f"ghg-cutover-back-{stamp}",
    }
    ports = {"target": _free_port(), "rollback": _free_port()}
    started = time.monotonic()
    timings: list[tuple[str, float]] = []
    ok = False
    try:
        print("\n1. Две пустые базы: цель и база отката")
        for key, name in names.items():
            _start_pg_container(name, ports[key])
            print(f"   · {key}: {DOCKER_IMAGE} на 127.0.0.1:{ports[key]}")
        timings.append(("базы подняты", time.monotonic() - started))

        # Схема накатывается ровно до ревизии дампа, а не до head: иначе
        # колонки, добавленные позже, заполнятся `server_default`, и сверка
        # покажет ложное расхождение (так и вышло с `organizations.media_key`
        # из 0075). Миграции после restore — следующий шаг.
        rev = dump_snap.get("revision") or "head"
        print(f"\n2. Схема на ревизию дампа ({rev}) и данные: alembic upgrade {rev} → restore")
        venv = _venv_python() or sys.executable
        for key in ("target", "rollback"):
            dsn = _local_dsn(ports[key])
            _run(
                [venv, "-m", "alembic", "upgrade", rev],
                _alembic_env(dsn),
                f"{key}: alembic upgrade {rev}",
            )
            _run(
                [sys.executable, os.path.join(HERE, "backup-db.py"), "restore", dump_path, "--yes"],
                _alembic_env(dsn),
                f"{key}: restore дампа",
            )

        print("\n3. Сверка целевой базы с дампом (до догона миграций)")
        conn = await connect(_local_dsn(ports["target"]))
        try:
            restored = await snapshot(conn)
        finally:
            await conn.close()
        bad = compare(dump_snap, restored)
        if bad:
            raise SystemExit(f"✗ Данные цели не совпали с дампом: расхождений {bad}")
        print(f"   ✅ {restored['total_rows']} строк / {restored['tables_count']} таблиц совпало")
        timings.append(("данные залиты и сверены", time.monotonic() - started))

        # Дамп помнит ревизию на момент снятия, поэтому после restore база
        # откатывается на неё. Новый код не должен получить старую схему —
        # догоняем миграции до head.
        print("\n4. Догон миграций до head в обеих базах")
        for key in ("target", "rollback"):
            _run(
                [venv, "-m", "alembic", "upgrade", "head"],
                _alembic_env(_local_dsn(ports[key])),
                f"{key}: alembic upgrade head",
            )
        timings.append(("схема догнана до head", time.monotonic() - started))

        print("\n5. Приложение против ЦЕЛИ")
        target_port = _free_port()
        target = _app_probe(_local_dsn(ports["target"]), target_port, "цель")
        head = (target["meta"].get("code") or {}).get("alembic_head")
        db_rev = (target["meta"].get("db") or {}).get("alembic_version")
        target_ok = (
            target["ready_status"] == 200
            and target["ready"].get("db") == "ok"
            and bool(head)
            and db_rev == head
        )
        print(
            f"   /healthz 200, /readyz {target['ready_status']} db={target['ready'].get('db')} "
            f"({target['ready'].get('ms')} мс), миграции {db_rev} / head {head}"
        )
        timings.append(("приложение работает на цели", time.monotonic() - started))

        print("\n6. Откат: приложение против БАЗЫ ОТКАТА")
        rollback_port = _free_port()
        rollback = _app_probe(_local_dsn(ports["rollback"]), rollback_port, "откат")
        rollback_ok = (
            rollback["ready_status"] == 200
            and rollback["ready"].get("db") == "ok"
            and (rollback["meta"].get("db") or {}).get("alembic_version") == head
        )
        print(
            f"   /healthz 200, /readyz {rollback['ready_status']} db={rollback['ready'].get('db')} "
            f"({rollback['ready'].get('ms')} мс)"
        )
        timings.append(("откат проверен", time.monotonic() - started))

        ok = target_ok and rollback_ok
        print()
        if ok:
            print("✅ ПЕРЕЕЗД ОБРАТИМ")
            print(
                "   Цель приняла данные и подняла приложение; "
                "возврат на прежнюю базу тоже работает."
            )
        else:
            print("⚠️ ПЕРЕЕЗД НЕ ПОДТВЕРЖДЁН")
            if not target_ok:
                print("   · цель: приложение не вышло в готовность или версия схемы не head")
            if not rollback_ok:
                print("   · откат: приложение не вышло в готовность")
    finally:
        for name in names.values():
            _docker("rm", "-f", name)
        print("\n7. Одноразовые базы удалены")
        print("   время по шагам:")
        for label, seconds in timings:
            print(f"   · {label:<32} {seconds:6.1f} с")
        print(f"   · {'всего':<32} {time.monotonic() - started:6.1f} с")
    return 0 if ok else 1



def main() -> int:
    parser = argparse.ArgumentParser(
        prog="db-rehearsal.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="какие базы есть и какая боевая").set_defaults(func=cmd_info)

    p_snap = sub.add_parser("snapshot", help="канонический слепок базы")
    p_snap.add_argument("--dsn-index", type=int, default=0)
    p_snap.add_argument("-o", "--out", default=os.path.join(WORKSPACE, "backups", "digests", "snap.json"))
    p_snap.set_defaults(func=cmd_snapshot)

    p_cmp = sub.add_parser("compare", help="сравнить два слепка")
    p_cmp.add_argument("a")
    p_cmp.add_argument("b")
    p_cmp.set_defaults(func=cmd_compare)

    p_reh = sub.add_parser("rehearse", help="пустая база → дамп → сверка с боевой")
    p_reh.add_argument("path", help="каталог дампа (backups/<штамп>)")
    p_reh.add_argument("--prod-index", type=int, default=0)
    p_reh.add_argument("--scratch-index", type=int, default=0)
    p_reh.add_argument("--out", default=os.path.join(WORKSPACE, "backups", "digests"))
    p_reh.add_argument("--keep", action="store_true", help="не удалять scratch-базу")
    p_reh.set_defaults(func=cmd_rehearse)

    p_local = sub.add_parser("rehearse-local", help="восстановление в одноразовый Postgres (docker)")
    p_local.add_argument("path", help="каталог дампа (backups/<штамп>)")
    p_local.set_defaults(func=cmd_rehearse_local)

    p_cut = sub.add_parser(
        "cutover", help="репетиция переезда: цель и откат под живым приложением (docker)"
    )
    p_cut.add_argument("path", help="каталог дампа (backups/<штамп>)")
    p_cut.set_defaults(func=cmd_cutover)

    p_check = sub.add_parser("check", help="сверить базу по DSN с дампом")
    p_check.add_argument("path")
    p_check.add_argument("--dsn", required=True)
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args()
    if args.cmd in {"info", "snapshot", "rehearse", "rehearse-local", "check", "cutover"}:
        _ensure_asyncpg()
        return asyncio.run(args.func(args))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
