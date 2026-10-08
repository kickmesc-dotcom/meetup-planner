#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Реконструкция записей «бот отреагировал на медиа» для старых постов.

Зачем. GHG11(10) заменил безликую строку журнала на запись ленты, которую лента
берёт из `game_media_posts.reacted_at`. Колонки `media_type` / `media_count` /
`preview_file_id` / `reaction_emoji` / `reaction_phrase` / `reacted_at` появились
миграцией 0028 — у всех постов, созданных ДО неё, они пустые. Поэтому в бою вид
ленты не изменился: подсистема реакций жива (реагирует по шансу), но исторических
записей в ленте нет.

Что делает. Берёт самые свежие посты с `reacted_at IS NULL` и заполняет запись о
реакции: время реакции (чуть позже поста), эмодзи из боевого whitelist'а и, для
части постов, фразу из боевого пула single-фраз. Тип медиа НЕ выдумываем: он
неизвестен (старый код его не писал), лента покажет нейтральное «фото».

Это РЕКОНСТРУКЦИЯ, а не факт: реальный эмодзи/фраза конкретного поста нигде не
сохранились. Поэтому идемпотентность и откат встроены: id затронутых постов
пишутся в `admin_config` под ключом `media.backfill.reacted_ids`, а `--revert`
снимает реконструкцию ровно по этому списку.

Канонический файл лежит в монорепо (`meetup-planner-main/tools/`), в корне рабочей
папки оставлен тонкий шим с тем же именем (как у `switch-db.py`). Секретов в
скрипте нет: DSN читается из `leltokens*.txt` в корне рабочей папки, пароль
печатается только маской.

Запуск (можно любым питоном — скрипт сам перезапустится на venv бэкенда, где
есть asyncpg):

    python tools/backfill-media-reactions.py --show
    python tools/backfill-media-reactions.py --limit 4
    python tools/backfill-media-reactions.py --limit 4 --yes
    python tools/backfill-media-reactions.py --drop-legacy --yes
    python tools/backfill-media-reactions.py --revert --yes

Без `--yes` ни одна команда ничего не пишет — это предпросмотр.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import pathlib
import re
import sys
from datetime import timedelta


def _find_up(start: str, marker: str, limit: int = 5) -> str | None:
    """Ближайшая папка вверх по дереву, где есть `marker`.

    Скрипт запускают и из корня рабочей папки (`tools/backfill-…`), и из монорепо
    (`meetup-planner-main/tools/backfill-…` — здесь он и версионируется), поэтому
    пути нельзя вычислять от `__file__` жёстко.
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
WORKSPACE = pathlib.Path(
    _find_up(HERE, os.path.join("secrets", "Get-Secret.ps1")) or os.path.dirname(HERE)
)
# Бэкенд (venv с asyncpg) ищем по alembic/versions, а не по имени папки.
MONOREPO = pathlib.Path(
    _find_up(HERE, os.path.join("backend", "alembic", "versions"))
    or WORKSPACE / "meetup-planner-main"
)
BACKEND = MONOREPO / "backend"

# Ключ-маркер: какие посты мы реконструировали (для честного отката).
MARKER_KEY = "media.backfill.reacted_ids"
EMOJI_KEY = "media_reactions.emoji_whitelist"
SINGLE_PHRASES_KEY = "media_reactions.single_phrases"

# Нейтральный фолбэк, если боевой whitelist почему-то пуст.
FALLBACK_EMOJI = ["👍", "🔥", "❤️", "😁", "🤣", "💯"]

DSN_RE = re.compile(r"postgresql(?:\+asyncpg)?://[^\s\"'<>]+")

# Рабочий файл с DSN. В корне папки лежат и мёртвые резервы (`leltokens1.txt`),
# поэтому «взять первый попавшийся» нельзя — порядок файлов задан явно.
TOKENS_FILE = os.environ.get("MEETUP_TOKENS_FILE", "leltokens2.txt")

# Куда положили DSN — печатается рядом с маской, чтобы было видно, что за база.
_DSN_SOURCE = ""

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# ------------------------------------------------------- venv и asyncpg -----
def _venv_python() -> str | None:
    for rel in ("Scripts/python.exe", "bin/python"):
        path = BACKEND / ".venv" / rel
        if path.exists():
            return str(path)
    return None


def _ensure_asyncpg() -> None:
    """asyncpg нужен всегда. Если его нет — перезапускаемся на venv бэкенда."""
    if importlib.util.find_spec("asyncpg") is not None:
        return
    venv = _venv_python()
    if venv and os.path.abspath(sys.executable) != os.path.abspath(venv):
        os.execv(venv, [venv, os.path.abspath(__file__), *sys.argv[1:]])
    sys.exit(
        "Нужен asyncpg. Запустите скрипт питоном из backend/.venv, например:\n"
        f"  {venv or str(BACKEND / '.venv' / 'Scripts' / 'python.exe')} "
        "tools/backfill-media-reactions.py " + " ".join(sys.argv[1:])
    )


# ------------------------------------------------------------------ DSN -----
def _dsn_files(explicit: str | None) -> list[pathlib.Path]:
    """Файлы с DSN в порядке доверия: явный → рабочий → любые остальные.

    Рабочий файл (`TOKENS_FILE`, по умолчанию `leltokens2.txt`) идёт первым: в
    корне папки рядом лежат резервы, и часть из них мертва.
    """
    if explicit:
        path = pathlib.Path(explicit)
        return [path if path.is_absolute() else WORKSPACE / path]
    out: list[pathlib.Path] = [
        WORKSPACE / TOKENS_FILE,
        WORKSPACE / "meetup-planner-backend" / TOKENS_FILE,
    ]
    rest = sorted(WORKSPACE.glob("leltokens*.txt"))
    rest += sorted((WORKSPACE / "meetup-planner-backend").glob("leltokens*.txt"))
    out += [p for p in rest if p not in out]
    return out


def find_dsn(explicit: str | None = None) -> str:
    """DSN из корня рабочей папки: `leltokens*.txt` (как `switch-db.py`)."""
    global _DSN_SOURCE
    for path in _dsn_files(explicit):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            found = DSN_RE.findall(line)
            if found:
                _DSN_SOURCE = path.name
                return found[0]
    raise SystemExit(
        f"Не нашёл DSN: ожидал postgresql://… в {TOKENS_FILE} рядом с {WORKSPACE}"
    )


def dsn_line(dsn: str) -> str:
    """Строка «что за база»: маска DSN + имя файла, откуда он взялся."""
    return f"DSN: {masked(dsn)}" + (f"  [{_DSN_SOURCE}]" if _DSN_SOURCE else "")


def masked(dsn: str) -> str:
    return re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", dsn)


def plain_dsn(dsn: str) -> str:
    return dsn.replace("+asyncpg", "")


def _load_list(raw: str | None, fallback: list[str]) -> list[str]:
    if raw is None:
        return list(fallback)
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return list(fallback)
    if isinstance(data, list) and all(isinstance(x, str) for x in data) and data:
        return list(data)
    return list(fallback)


def parse_marker(raw: str | None) -> list[int]:
    if raw is None:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[int] = []
    for item in data:
        try:
            out.append(int(item))
        except (ValueError, TypeError):
            continue
    return out


async def _config_value(conn, key: str) -> str | None:
    return await conn.fetchval("select value from admin_config where key = $1", key)


async def _set_config(conn, key: str, value: str) -> None:
    await conn.execute(
        """
        insert into admin_config (key, value) values ($1, $2)
        on conflict (key) do update set value = excluded.value
        """,
        key,
        value,
    )


async def cmd_show(conn, dsn: str) -> None:
    rows = await conn.fetch(
        """
        select id, user_id, kind, posted_at, reacted_at
        from game_media_posts
        where reacted_at is null
        order by posted_at desc, id desc
        """
    )
    print(dsn_line(dsn))
    print(f"Постов без записи о реакции: {len(rows)}")
    for row in rows:
        print(
            f"  #{row['id']:<3} user={row['user_id']:<3} {row['kind']:<10} "
            f"posted={row['posted_at']:%Y-%m-%d %H:%M}"
        )
    marker = parse_marker(await _config_value(conn, MARKER_KEY))
    print(f"Маркер реконструкции ({MARKER_KEY}): {marker or '—'}")


async def cmd_revert(conn, dsn: str, *, yes: bool) -> int:
    ids = parse_marker(await _config_value(conn, MARKER_KEY))
    print(dsn_line(dsn))
    if not ids:
        print("Маркер пуст — откатывать нечего.")
        return 0
    print(f"Снимаю реконструкцию с {len(ids)} постов: {ids}")
    if not yes:
        print("\nЭто предпросмотр. Повтори с --yes, чтобы записать.")
        return 0
    await conn.execute(
        """
        update game_media_posts
        set reacted_at = null, reaction_emoji = null, reaction_phrase = null
        where id = any($1::int[])
        """,
        ids,
    )
    await _set_config(conn, MARKER_KEY, "[]")
    print("Готово: записи о реакциях сняты, маркер очищен.")
    return 0


# Legacy-анонс старого кода: «📸 Бот отреагировал на медиа (Сомов)» в game_journal.
LEGACY_TEXT_PREFIX = "📸 Бот отреагировал на медиа"


async def cmd_drop_legacy(conn, dsn: str, *, yes: bool) -> int:
    rows = await conn.fetch(
        """
        select id, kind, text, created_at from game_journal
        where kind = 'feature' and text like $1
        order by id
        """,
        LEGACY_TEXT_PREFIX + "%",
    )
    print(dsn_line(dsn))
    if not rows:
        print("Legacy-строк журнала не найдено.")
        return 0
    print(f"Legacy-строк «{LEGACY_TEXT_PREFIX}…»: {len(rows)}")
    for row in rows:
        print(f"  journal#{row['id']:<3} {row['created_at']:%Y-%m-%d %H:%M} | {row['text']}")
    print(
        "Их заменяет запись ленты вида `media` (с типом медиа и реакцией бота), "
        "поэтому оставляем только новую форму."
    )
    if not yes:
        print("\nЭто предпросмотр. Повтори с --yes, чтобы удалить.")
        return 0
    await conn.execute(
        "delete from game_journal where id = any($1::int[])",
        [int(row["id"]) for row in rows],
    )
    print(f"\nУдалено строк: {len(rows)}.")
    return 0


async def cmd_backfill(conn, dsn: str, *, limit: int | None, yes: bool) -> int:
    rows = await conn.fetch(
        """
        select id, user_id, kind, media_count, posted_at
        from game_media_posts
        where reacted_at is null
        order by posted_at desc, id desc
        """
    )
    if limit is not None:
        rows = rows[:limit]
    print(dsn_line(dsn))
    if not rows:
        print("Нет постов без реакции — реконструировать нечего.")
        return 0

    emojis = _load_list(await _config_value(conn, EMOJI_KEY), FALLBACK_EMOJI)
    phrases = _load_list(await _config_value(conn, SINGLE_PHRASES_KEY), [])

    planned: list[dict] = []
    for i, row in enumerate(rows):
        posted = row["posted_at"]
        # Разносим реакции по времени детерминированно: чуть позже поста и без
        # «одной секунды на всё» — иначе лента выглядит как один залп.
        offset_min = 4 + (i * 7) % 11
        emoji = emojis[i % len(emojis)]
        # Половине постов — ещё и фразу, как это делает боевой режим random_one.
        phrase = None
        if phrases and i % 2 == 1:
            phrase = phrases[(i // 2) % len(phrases)]
        planned.append(
            {
                "id": int(row["id"]),
                "user_id": int(row["user_id"]),
                "kind": row["kind"],
                "reacted_at": posted + timedelta(minutes=offset_min),
                "emoji": emoji,
                "phrase": phrase,
            }
        )

    print(
        f"Реконструирую реакцию у {len(planned)} постов "
        f"(эмодзи из {len(emojis)} боевых, фразы из {len(phrases)}):"
    )
    for p in planned:
        tail = f" + «{p['phrase']}»" if p["phrase"] else ""
        print(
            f"  #{p['id']:<3} user={p['user_id']:<3} {p['kind']:<8} "
            f"reacted_at={p['reacted_at']:%Y-%m-%d %H:%M} {p['emoji']}{tail}"
        )

    if not yes:
        print("\nЭто предпросмотр. Повтори с --yes, чтобы записать.")
        return 0

    for p in planned:
        await conn.execute(
            """
            update game_media_posts
            set reacted_at = $2,
                reaction_emoji = $3,
                reaction_phrase = $4,
                media_count = coalesce(media_count, 1)
            where id = $1
            """,
            p["id"],
            p["reacted_at"],
            p["emoji"],
            p["phrase"],
        )

    marker = parse_marker(await _config_value(conn, MARKER_KEY))
    merged = sorted(set(marker) | {p["id"] for p in planned})
    await _set_config(conn, MARKER_KEY, json.dumps(merged))
    print(f"\nЗаписано. Реконструировано постов: {len(planned)}.")
    print(f"Маркер отката: {MARKER_KEY} = {merged}")
    return 0


async def run(args) -> int:
    import asyncpg

    global _DSN_SOURCE
    if args.dsn:
        _DSN_SOURCE = "--dsn"
    dsn = args.dsn or find_dsn(args.tokens)
    conn = await asyncpg.connect(dsn=plain_dsn(dsn), timeout=30, command_timeout=120)
    try:
        if args.show:
            await cmd_show(conn, dsn)
            return 0
        if args.revert:
            return await cmd_revert(conn, dsn, yes=args.yes)
        if args.drop_legacy:
            return await cmd_drop_legacy(conn, dsn, yes=args.yes)
        limit = None if args.all else args.limit
        return await cmd_backfill(conn, dsn, limit=limit, yes=args.yes)
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", action="store_true", help="только показать состояние")
    parser.add_argument("--revert", action="store_true", help="снять реконструкцию")
    parser.add_argument(
        "--drop-legacy", action="store_true", help="убрать legacy-строку журнала о реакции"
    )
    parser.add_argument(
        "--limit", type=int, default=6, help="сколько свежих постов взять (по умолчанию 6)"
    )
    parser.add_argument("--all", action="store_true", help="взять все посты без реакции")
    parser.add_argument("--dsn", default=None, help="перекрыть DSN")
    parser.add_argument(
        "--tokens",
        default=None,
        help=f"файл с DSN (по умолчанию {TOKENS_FILE} в корне рабочей папки)",
    )
    parser.add_argument("--yes", action="store_true", help="действительно записать")
    args = parser.parse_args(argv)
    _ensure_asyncpg()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
