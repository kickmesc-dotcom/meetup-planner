#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Логический бэкап боевой базы — точка отката для игры и всего остального.

Это тот самый пункт 0.4 задания GHG10 («предварительно снимаем один массивный
мега-бэкап, готовый к тому чтобы можно было откатиться в любой момент»),
который до сих пор не был закрыт: `pg_dump` на машине нет, а тащить его ради
десятимегабайтной базы незачем.

Что делает:

  dump [--out DIR]   — выгружает ВСЕ таблицы схемы public в DIR/<штамп>/ как
                       gzip-JSONL по таблице + manifest.json (версия миграций,
                       число строк, sha256 каждого файла). Печатает путь.
                       Перед выгрузкой сверяет хост DSN с боевой базой
                       (`/api/meta`): дамп «не той базы» выглядит настоящим,
                       но откатиться на него нельзя.
  verify DIR         — проверяет, что файлы на месте и хэши совпадают
  restore DIR        — заливает дамп обратно (в ПУСТУЮ схему: сначала
                       `alembic upgrade head`). Порядок таблиц — топологический
                       по внешним ключам, чтобы FK не падали.
  list               — какие бэкапы уже сняты
  prune --keep N     — оставить N свежих, остальные удалить (ротация:
                       дампы не должны занимать диск бесконечно)

Почему не SQL-дамп: цель — «откатиться в любой момент», а не «восстановить
pg_dump'ом». JSONL переживает смену схемы (лишние/недостающие колонки
обрабатываются по именам), читается глазами и не требует своих утилит.
Пароли из DSN нигде не печатаются.

Запуск (любым питоном — скрипт сам перезапустится на venv бэкенда):

    python tools/backup-db.py dump
    python tools/backup-db.py verify backups/2026-09-29_1800
    python tools/backup-db.py restore backups/2026-09-29_1800
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(HERE)
# Инструмент лежит ВНУТРИ репозитория (`meetup-planner-main/tools/`), поэтому
# backend — соседняя папка, а не вложенная: после переноса старый путь
# (`workspace/meetup-planner-main/backend`) стал двойным и subprocess падал
# с WinError 267 «directory name is invalid».
BACKEND = os.path.join(WORKSPACE, "backend")
DEFAULT_OUT = os.path.join(WORKSPACE, "backups")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# ------------------------------------------------------- окружение и DSN ----
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


def _secret(key: str) -> str | None:
    if os.environ.get(key):
        return os.environ[key]
    script = os.path.join(WORKSPACE, "secrets", "Get-Secret.ps1")
    if os.path.exists(script):
        out = subprocess.run(
            ["powershell", "-NoProfile", "-File", script, key],
            capture_output=True,
            text=True,
            timeout=60,
        )
        val = (out.stdout or "").strip()
        if val:
            return val
    return None


def _dsn() -> str:
    raw = _secret("DATABASE_URL")
    if not raw:
        sys.exit("Нет DATABASE_URL (ни в env, ни в secrets/).")
    return raw.replace("postgresql+asyncpg://", "postgresql://")


def _mask(dsn: str) -> str:
    import re

    return re.sub(r"://([^:@/]*):[^@]*@", r"://\1:***@", dsn)


def _parts(dsn: str) -> dict[str, str]:
    """host/port/user/db из DSN — без единого секрета."""
    import re

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


# Те же адреса, что у `/api/meta`: боевой контур один, но пока живы две
# площадки (Amvera и HF), проверяем обе — иначе сверка молча пропускалась
# бы при отказе одного хоста.
LIVE_HOSTS = (
    "https://meetup-planner-youmakemefry.waw0.amvera.tech",
    "https://fryesw-meetup-planner-backend.hf.space",
)


def _live_db_host() -> str | None:
    """Маскированный хост боевой базы из `/api/meta` или None."""
    for base in LIVE_HOSTS:
        try:
            with urllib.request.urlopen(f"{base}/api/meta", timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 — хост может быть недоступен
            continue
        host = (data.get("db") or {}).get("host")
        if host:
            return str(host)
    return None


def _host_prefix(masked: str) -> str:
    """`/api/meta` маскирует хвост: `ep-dry-cherry-….neon.tech`."""
    return masked.split("…")[0].split("...")[0]


def _same_host(dsn_host: str, live_host: str) -> bool:
    """Тот же сервер? Сравниваем префикс: pooler-адрес длиннее боевого."""
    prefix = _host_prefix(live_host)
    return bool(prefix) and dsn_host.startswith(prefix)


def _local_host(dsn: str) -> bool:
    """База на этой машине (контейнер для проверки восстановления)."""
    host = _parts(dsn)["host"].lower()
    return "localhost" in host or "127.0.0.1" in host or host == "::1"


def _connect_kwargs(dsn: str) -> dict:
    """SSL передаётся аргументом `connect()`, а не в DSN.

    asyncpg не принимает `ssl` ни как `?ssl=`, ни как `?sslmode=` — оба
    попадают в runtime-параметры и падают с «parameter \"ssl\" cannot be
    changed now». Прод требует SSL (оставляем умолчание asyncpg),
    локальному контейнеру он не нужен и только мешает.
    """
    return {"ssl": False} if _local_host(dsn) else {}


def _ensure_prod(dsn: str, *, allow_any: bool) -> None:
    """Не снимать дамп «неизвестно чего».

    Худший вид бэкапа — тот, что выглядит настоящим: файлы на месте, хэши
    сходятся, а данных боевой базы в нём нет. Ровно это случилось 03.11.2026:
    `secrets/` указывал на старую базу (0028), боевая ушла на 0067, а
    единственный дамп был от 29.09. Поэтому адрес назначения проверяется
    фактом (`/api/meta`), а не тем, что переменная задана.
    """
    if allow_any:
        return
    live = _live_db_host()
    if live is None:
        sys.exit(
            "Не удалось узнать хост боевой базы (/api/meta недоступен).\n"
            "Дамп «неизвестно чего» — не точка отката: повторите позже или\n"
            "снимайте копию стенда с --allow-any."
        )
    if not _same_host(_parts(dsn)["host"], live):
        sys.exit(
            "DSN указывает НЕ на боевую базу.\n"
            f"  в DSN : {_parts(dsn)['host']}\n"
            f"  боевая: {live}\n"
            "Бэкап не той базы выглядит настоящим, но откатиться на него\n"
            "нельзя. Проверьте DATABASE_URL/BACKUP_DATABASE_URL, либо\n"
            "снимайте копию стенда с --allow-any."
        )


# ------------------------------------------------------------ сериализация --
def _enc(value: Any) -> Any:
    """Значение → JSON-совместимое. Строки/числа/bool/None остаются как есть."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return {"__t": "dt", "v": value.isoformat()}
    if isinstance(value, date):
        return {"__t": "date", "v": value.isoformat()}
    if isinstance(value, time):
        return {"__t": "time", "v": value.isoformat()}
    if isinstance(value, UUID):
        return {"__t": "uuid", "v": str(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__t": "b64", "v": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, (dict, list)):
        return value  # JSONB: как есть
    return {"__t": "repr", "v": repr(value)}


def _dec(value: Any) -> Any:
    """Обратно: то, что упаковал `_enc`."""
    if isinstance(value, dict) and "__t" in value:
        kind, raw = value["__t"], value.get("v")
        if kind == "dt":
            return datetime.fromisoformat(raw)
        if kind == "date":
            return date.fromisoformat(raw)
        if kind == "time":
            return time.fromisoformat(raw)
        if kind == "uuid":
            return UUID(raw)
        if kind == "b64":
            return base64.b64decode(raw)
        return raw
    return value


# ------------------------------------------------------------------ схема ---
async def _tables(conn) -> list[str]:
    rows = await conn.fetch(
        "select table_name from information_schema.tables "
        "where table_schema='public' and table_type='BASE TABLE' order by table_name"
    )
    return [r["table_name"] for r in rows]


async def _fk(conn, child: dict[str, list[str]], tables: list[str]) -> None:
    """Наполнить граф зависимостей child → родители (по внешним ключам)."""
    rows = await conn.fetch(
        "select tc.table_name as child, ccu.table_name as parent "
        "from information_schema.table_constraints tc "
        "join information_schema.constraint_column_usage ccu "
        "  on ccu.constraint_name = tc.constraint_name "
        "where tc.constraint_type='FOREIGN KEY' and tc.table_schema='public'"
    )
    for row in rows:
        child.setdefault(row["child"], [])
        if row["parent"] != row["child"]:
            child[row["child"]].append(row["parent"])
    for name in tables:
        child.setdefault(name, [])


def _topo_order(child: dict[str, list[str]], tables: list[str]) -> list[str]:
    """Родители раньше детей (детерминированно: алфавит при равных правах)."""
    ordered: list[str] = []
    pending = set(tables)
    while pending:
        ready = sorted(
            name
            for name in pending
            if all(parent in ordered or parent not in pending for parent in child.get(name, []))
        )
        if not ready:  # цикл FK — выгружаем остаток по алфавиту, не падаем
            ready = sorted(pending)
        ordered.extend(ready)
        pending.difference_update(ready)
    return ordered


# ------------------------------------------------------------------- dump ---
async def cmd_dump(args) -> int:
    import asyncpg

    dsn = _dsn()
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = os.path.abspath(args.out)
    target = os.path.join(out_dir, stamp)
    os.makedirs(target, exist_ok=True)

    _ensure_prod(dsn, allow_any=args.allow_any)
    print(f"Бэкап боевой базы → {target}")
    print(f"  DSN: {_mask(dsn)}  (хост сверен с /api/meta)\n")

    conn = await asyncpg.connect(
        dsn=dsn, timeout=30, command_timeout=300, **_connect_kwargs(dsn)
    )
    try:
        tables = await _tables(conn)
        manifest: dict[str, Any] = {
            "created_at": datetime.now().isoformat(),
            "dsn": _mask(dsn),
            "host": _parts(dsn)["host"],
            "revision": await conn.fetchval("select version_num from alembic_version"),
            "server_version": await conn.fetchval("show server_version"),
            "database": await conn.fetchval("select current_database()"),
            "tables": {},
        }
        total_rows = 0
        for name in tables:
            rows = await conn.fetch(f'select * from "{name}"')
            payload = "".join(
                json.dumps({k: _enc(v) for k, v in dict(row).items()}, ensure_ascii=False)
                + "\n"
                for row in rows
            )
            raw = payload.encode("utf-8")
            path = os.path.join(target, f"{name}.jsonl.gz")
            with gzip.open(path, "wb") as fh:
                fh.write(raw)
            manifest["tables"][name] = {
                "rows": len(rows),
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            total_rows += len(rows)
            print(f"  {name:<28} {len(rows):>6} строк")
        manifest["total_rows"] = total_rows
        with open(os.path.join(target, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
    finally:
        await conn.close()

    size = sum(
        os.path.getsize(os.path.join(target, f)) for f in os.listdir(target)
    )
    print(
        f"\n✅ Готово: {len(manifest['tables'])} таблиц, {manifest['total_rows']} строк, "
        f"миграции {manifest['revision']}, на диске {size / 1024:.0f} kB"
    )
    print(f"   Откат: python tools/backup-db.py restore {target}")
    return 0


# ----------------------------------------------------------------- verify ---
def _load_manifest(path: str) -> dict:
    with open(os.path.join(path, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def cmd_verify(args) -> int:
    path = os.path.abspath(args.path)
    manifest = _load_manifest(path)
    print(f"Проверяю {path}\n  снят: {manifest['created_at']} · миграции {manifest['revision']}")
    bad = 0
    for name, info in manifest["tables"].items():
        file = os.path.join(path, f"{name}.jsonl.gz")
        if not os.path.exists(file):
            print(f"  ✗ {name}: файла нет")
            bad += 1
            continue
        with gzip.open(file, "rb") as fh:
            raw = fh.read()
        digest = hashlib.sha256(raw).hexdigest()
        ok = digest == info["sha256"]
        if not ok:
            bad += 1
        print(
            f"  {'✓' if ok else '✗'} {name}: {len(raw.decode('utf-8').splitlines())} строк, "
            f"sha256 {'совпал' if ok else 'НЕ совпал'}"
        )
    if manifest.get("total_rows", 0) == 0:
        print("\n⚠️ Дамп пустой: 0 строк. Целые файлы без данных — не точка отката.")
        return 1
    print("\n✅ Дамп целый: строк", manifest.get("total_rows"), "· миграции", manifest.get("revision"))
    return 0 if bad == 0 else 1


# ---------------------------------------------------------------- restore ---
async def _pk_columns(conn, table: str) -> list[str]:
    """Колонки первичного ключа в порядке объявления. Пусто — PK нет."""
    rows = await conn.fetch(
        """
        select kcu.column_name
          from information_schema.table_constraints tc
          join information_schema.key_column_usage kcu
            on kcu.constraint_name = tc.constraint_name
           and kcu.table_schema = tc.table_schema
         where tc.table_schema = 'public'
           and tc.constraint_type = 'PRIMARY KEY'
           and tc.table_name = $1
         order by kcu.ordinal_position
        """,
        table,
    )
    return [r["column_name"] for r in rows]


async def _resync_sequences(conn) -> int:
    """Подтянуть serial/identity-последовательности к max(id) в таблице.

    Без этого откат опасен: дамп вставляет строки с явными id, а последовательность
    остаётся на старом значении — и следующий же обычный INSERT в приложении падает
    с duplicate key. Точка отката, которая ломается на первой записи, — не точка
    отката.
    """
    rows = await conn.fetch(
        """
        select c.relname as table_name, a.attname as column_name,
               pg_get_serial_sequence(quote_ident(c.relname), a.attname) as seq
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
          join pg_attribute a on a.attrelid = c.oid
         where n.nspname = 'public' and c.relkind = 'r'
           and a.attnum > 0 and not a.attisdropped
           and pg_get_serial_sequence(quote_ident(c.relname), a.attname) is not null
        """
    )
    done = 0
    for row in rows:
        table, column, seq = row["table_name"], row["column_name"], row["seq"]
        try:
            await conn.execute(
                f'select setval($1, coalesce((select max("{column}") from "{table}"), 0) + 1, false)',
                seq,
            )
            done += 1
        except Exception as exc:  # noqa: BLE001 — не блокируем восстановление
            print(f"  {table}.{column}: последовательность не выставлена ({exc})")
    return done


async def cmd_restore(args) -> int:
    import asyncpg

    path = os.path.abspath(args.path)
    manifest = _load_manifest(path)
    dsn = _dsn()
    conn = await asyncpg.connect(
        dsn=dsn, timeout=30, command_timeout=600, **_connect_kwargs(dsn)
    )
    child: dict[str, list[str]] = {}
    try:
        existing = set(await _tables(conn))
        try:
            await _fk(conn, child, list(existing))
        except Exception:  # noqa: BLE001 — граф не критичен, порядок будет алфавитным
            pass
        order = _topo_order(child, list(existing))
        if not args.yes:
            answer = input(
                f"\nЗалить {manifest['total_rows']} строк из {path}\nв базу {_mask(dsn)}?\n"
                "Схема должна быть пустой и уже промигрированной. Введите 'да': "
            ).strip().lower()
            if answer not in {"да", "yes", "y", "д"}:
                print("Отменено.")
                return 1
        restored = 0
        for name in order:
            info = manifest["tables"].get(name)
            if not info:
                print(f"  {name}: нет в дампе — пропускаю")
                continue
            file = os.path.join(path, f"{name}.jsonl.gz")
            with gzip.open(file, "rt", encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh if line.strip()]
            if not rows:
                continue
            columns = sorted({key for row in rows for key in row})
            placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
            quoted = ", ".join('"' + col + '"' for col in columns)
            pk = await _pk_columns(conn, name)
            if pk and set(pk) <= set(columns):
                # ВАЖНО: не `do nothing`, а upsert. Миграции засевают часть
                # таблиц сами (например, дефолтный Новый год в `game_holidays`),
                # и `do nothing` молча оставляла в базе ЗАСЕЯННУЮ строку вместо
                # строки из дампа с тем же PK: восстановление выглядело успешным,
                # а данные были чужие. Правило восстановления простое: дамп
                # всегда главнее того, что лежит в целевой базе.
                target = ", ".join('"' + col + '"' for col in pk)
                updates = ", ".join(
                    f'"{col}" = excluded."{col}"' for col in columns if col not in pk
                )
                conflict = (
                    f"on conflict ({target}) do update set {updates}"
                    if updates
                    else f"on conflict ({target}) do nothing"
                )
                sql = (
                    f'insert into "{name}" ({quoted}) values ({placeholders}) {conflict}'
                )
            else:
                # Без PK (или PK нет в дампе) конфликт не на что навесить.
                sql = (
                    f'insert into "{name}" ({quoted}) '
                    f"values ({placeholders}) on conflict do nothing"
                )
            records = [
                tuple(_dec(row.get(col)) for col in columns) for row in rows
            ]
            await conn.executemany(sql, records)
            restored += len(rows)
            extra = 0
            if pk and len(pk) == 1 and not args.no_prune:
                # Убрать строки, которых в дампе нет. Без этого в целевой базе
                # остаются засеянные миграциями (или оставшиеся от прошлого
                # прогона) строки, и «восстановлено» перестаёт означать
                # «совпадает с дампом». Сравниваем через text — тип колонки
                # может быть любой, а таблицы здесь и так маленькие.
                keys = [str(row.get(pk[0])) for row in rows]
                status = await conn.execute(
                    f'delete from "{name}" where "{pk[0]}"::text <> all($1::text[])',
                    keys,
                )
                extra = int(status.split()[-1]) if status.startswith("DELETE") else 0
            note = f"  (убрано лишних: {extra})" if extra else ""
            print(f"  {name:<28} {len(rows):>6} строк{note}")
        synced = await _resync_sequences(conn)
        print(f"\n✅ Залито {restored} строк; последовательностей выставлено: {synced}")
    finally:
        await conn.close()
    return 0


def cmd_prune(args) -> int:
    """Оставить `--keep` свежих бэкапов, остальные удалить.

    Без ротации бэкапы занимают диск до отказа, а отказ диска — это отказ
    записи (в том числе журналов и медиа). Храним по умолчанию 7 штук: неделя
    истории — тот же горизонт, который даёт PITR провайдера на бесплатном
    тарифе, и его хватает, чтобы заметить ошибку «удалили не то».
    Недельный горизонт выбран не из жадности: HR-ошибку находят не в тот же
    час, а на разборе смены.
    """
    base = os.path.abspath(args.out)
    if not os.path.isdir(base):
        print("Бэкапов нет.")
        return 0
    stamps = sorted(
        name
        for name in os.listdir(base)
        if os.path.exists(os.path.join(base, name, "manifest.json"))
    )
    keep = max(1, args.keep)
    doomed = stamps[:-keep]
    if not doomed:
        print(f"Удалять нечего: бэкапов {len(stamps)}, храним {keep}.")
        return 0
    for name in doomed:
        if args.dry_run:
            print(f"  (бы удалил) {name}")
            continue
        shutil.rmtree(os.path.join(base, name))
        print(f"  удалён {name}")
    print(f"\n✅ Оставлено {min(len(stamps), keep)} из {len(stamps)}")
    return 0


def cmd_list(_args) -> int:
    base = DEFAULT_OUT
    if not os.path.isdir(base):
        print("Бэкапов нет.")
        return 0
    for name in sorted(os.listdir(base)):
        manifest = os.path.join(base, name, "manifest.json")
        if os.path.exists(manifest):
            data = json.load(open(manifest, encoding="utf-8"))
            print(
                f"  {name}  таблиц {len(data['tables'])}, строк {data['total_rows']}, "
                f"миграции {data['revision']}"
            )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="backup-db.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dump = sub.add_parser("dump", help="снять бэкап")
    p_dump.add_argument("--out", default=DEFAULT_OUT)
    p_dump.add_argument(
        "--allow-any",
        action="store_true",
        help="снять копию стенда, не сверяя хост с боевой базой",
    )
    p_dump.set_defaults(func=cmd_dump)

    p_verify = sub.add_parser("verify", help="проверить целостность дампа")
    p_verify.add_argument("path")
    p_verify.set_defaults(func=cmd_verify)

    p_restore = sub.add_parser("restore", help="залить дамп в пустую схему")
    p_restore.add_argument("path")
    p_restore.add_argument("--yes", "-y", action="store_true")
    p_restore.add_argument(
        "--no-prune",
        action="store_true",
        help="не удалять строки, которых нет в дампе (по умолчанию удаляются: "
        "восстановление должно давать ровно дамп)",
    )
    p_restore.set_defaults(func=cmd_restore)

    sub.add_parser("list", help="список бэкапов").set_defaults(func=cmd_list)

    p_prune = sub.add_parser("prune", help="ротация: оставить N свежих")
    p_prune.add_argument("--out", default=DEFAULT_OUT)
    p_prune.add_argument("--keep", type=int, default=7)
    p_prune.add_argument("--dry-run", action="store_true")
    p_prune.set_defaults(func=cmd_prune)

    args = parser.parse_args()
    if args.func in (cmd_dump, cmd_restore):
        _ensure_asyncpg()
        import asyncio

        return asyncio.run(args.func(args))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
