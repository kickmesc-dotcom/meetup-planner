"""Тесты `tools/backup-db.py` — сверка боевой базы и ротация.

Покрываем то, что уже один раз сломалось тихо (03.11.2026):

1. **Сверка хоста с `/api/meta`.** `secrets/` указывал на старую базу (0028),
   боевая ушла на 0067, а единственный дамп был от 29.09. Дамп «не той базы»
   выглядит настоящим: файлы на месте, хэши сходятся — и это худший вид бэкапа,
   потому что откатиться на него нельзя. Поэтому `dump` без явного `--allow-any`
   обязан отказаться, если хост не боевой.
2. **Сравнение с pooler-адресом.** Боевой DSN идёт через `-pooler`, а
   `/api/meta` маскирует хвост: `ep-dry-cherry-….neon.tech`. Сравнение по
   префиксу — единственный способ не отвергать правильную базу.
3. **Ротация.** Без `prune` дампы занимают диск до отказа, а отказ диска — это
   отказ записи, то есть отказ продукта.

Запуск из корня монорепо:

    backend/.venv/Scripts/python.exe -m pytest tools/tests -q
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

LIVE_MASKED = "ep-dry-cherry-….neon.tech"
PROD_HOST = "ep-dry-cherry-baraqxe8-pooler.c-8.eu-central-1.aws.neon.tech"
OLD_HOST = "ep-cool-union-aszq9p4u.c-4.eu-central-1.aws.neon.tech"


# --- сверка боевой базы ----------------------------------------------------


def test_same_host_accepts_pooler_address(backup_db):
    assert backup_db._same_host(PROD_HOST, LIVE_MASKED)


def test_same_host_rejects_other_database(backup_db):
    """Старая база — не боевая, даже если это тот же провайдер."""
    assert not backup_db._same_host(OLD_HOST, LIVE_MASKED)


def test_ensure_prod_refuses_foreign_host(backup_db, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(backup_db, "_live_db_host", lambda: LIVE_MASKED)
    dsn = f"postgresql://neondb_owner:pw@{OLD_HOST}/neondb"
    with pytest.raises(SystemExit) as caught:
        backup_db._ensure_prod(dsn, allow_any=False)
    message = str(caught.value)
    assert "НЕ на боевую" in message
    # В сообщении не должно быть пароля: оно попадает в логи CI.
    assert "pw@" not in message and "pw" not in message.replace("postgresql", "")


def test_ensure_prod_allows_prod_or_explicit_allow_any(
    backup_db, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(backup_db, "_live_db_host", lambda: LIVE_MASKED)
    backup_db._ensure_prod(f"postgresql://u:p@{PROD_HOST}/neondb", allow_any=False)
    # Стенд: снимать копию можно, но только явным флагом.
    backup_db._ensure_prod(f"postgresql://u:p@{OLD_HOST}/neondb", allow_any=True)


def test_ensure_prod_refuses_when_production_unknown(
    backup_db, monkeypatch: pytest.MonkeyPatch
):
    """`/api/meta` недоступен — это не повод снимать «что-то»."""
    monkeypatch.setattr(backup_db, "_live_db_host", lambda: None)
    with pytest.raises(SystemExit) as caught:
        backup_db._ensure_prod(f"postgresql://u:p@{PROD_HOST}/neondb", allow_any=False)
    assert "/api/meta" in str(caught.value)


# --- ротация ---------------------------------------------------------------


def _fake_backups(base: Path, stamps: list[str]) -> None:
    for stamp in stamps:
        folder = base / stamp
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(
            json.dumps({"total_rows": 1, "revision": "0067", "tables": {}}),
            encoding="utf-8",
        )


def test_prune_keeps_newest(backup_db, tmp_path: Path):
    stamps = [
        "2026-10-01_030000",
        "2026-10-02_030000",
        "2026-10-03_030000",
        "2026-10-04_030000",
    ]
    _fake_backups(tmp_path, stamps)
    backup_db.cmd_prune(SimpleNamespace(out=str(tmp_path), keep=2, dry_run=False))
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == stamps[-2:]


def test_prune_dry_run_changes_nothing(backup_db, tmp_path: Path):
    stamps = ["2026-10-01_030000", "2026-10-02_030000"]
    _fake_backups(tmp_path, stamps)
    backup_db.cmd_prune(SimpleNamespace(out=str(tmp_path), keep=1, dry_run=True))
    assert sorted(p.name for p in tmp_path.iterdir()) == stamps


def test_prune_without_backups_is_not_an_error(backup_db, tmp_path: Path):
    assert backup_db.cmd_prune(SimpleNamespace(out=str(tmp_path), keep=7, dry_run=False)) == 0
