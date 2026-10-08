"""Тесты `tools/backfill-media-reactions.py` — реконструкции реакций на старые медиа.

Покрываем места, где ошибка стоит дорого: скрипт пишет в БОЕВУЮ базу.

1. **Выбор DSN** (`_dsn_files` + `find_dsn`). Рядом с рабочим `leltokens2.txt` в
   корне папки лежат мёртвые резервы (`leltokens1.txt`): если взять «первый
   попавшийся» файл, скрипт уедет в чужую базу. Проверяем, что рабочий файл идёт
   первым, а `--tokens` перекрывает выбор.
2. **Разбор маркера отката** (`parse_marker`). Маркер — единственное, что
   позволяет снять реконструкцию, не задев настоящие реакции; мусор в нём должен
   давать пустой список, а не исключение.
3. **Списки эмодзи/фраз** (`_load_list`): пустое значение в `admin_config` не
   должно ронять бэкфилл — берём фолбэк.
4. **Маска DSN** (`masked` / `dsn_line`): пароль не печатается в открытом виде,
   но видно, из какого файла взят DSN.

Боевые `secrets/` и `leltokens*.txt` тесты не читают: рабочая папка подменяется
на `tmp_path`.

Запуск из корня монорепо:

    backend/.venv/Scripts/python.exe -m pytest tools/tests -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

LIVE_HOST = "ep-cool-union-aszq9p4u.c-4.eu-central-1.aws.neon.tech"
DEAD_HOST = "ep-rapid-butterfly-al1rllsg-pooler.c-3.eu-central-1.aws.neon.tech"


def _fake_workspace(tmp_path: Path, backfill, files: dict[str, str]) -> Path:
    """Рабочая папка с файлами токенов; боевые пути не трогаем."""
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------------- DSN -----
def test_live_tokens_file_wins_over_reserve(tmp_path, backfill, monkeypatch):
    """Рабочий `leltokens2.txt` важнее соседнего резерва — иначе уедем в мёртвую базу."""
    workspace = _fake_workspace(
        tmp_path,
        backfill,
        {
            "leltokens1.txt": f"postgresql://neondb_owner:pw-dead@{DEAD_HOST}/neondb?ssl=require\n",
            "leltokens2.txt": f"postgresql://neondb_owner:pw-live@{LIVE_HOST}/neondb?ssl=require\n",
        },
    )
    monkeypatch.setattr(backfill, "WORKSPACE", workspace)
    monkeypatch.setattr(backfill, "TOKENS_FILE", "leltokens2.txt")
    dsn = backfill.find_dsn()
    assert LIVE_HOST in dsn
    assert backfill._DSN_SOURCE == "leltokens2.txt"


def test_explicit_tokens_file_overrides(tmp_path, backfill, monkeypatch):
    workspace = _fake_workspace(
        tmp_path,
        backfill,
        {
            "leltokens2.txt": f"postgresql://neondb_owner:pw-live@{LIVE_HOST}/neondb\n",
            "other.txt": f"postgresql://neondb_owner:pw-x@{DEAD_HOST}/neondb\n",
        },
    )
    monkeypatch.setattr(backfill, "WORKSPACE", workspace)
    dsn = backfill.find_dsn("other.txt")
    assert DEAD_HOST in dsn
    assert backfill._DSN_SOURCE == "other.txt"


def test_find_dsn_without_any_file_exits(tmp_path, backfill, monkeypatch):
    monkeypatch.setattr(backfill, "WORKSPACE", tmp_path)
    with pytest.raises(SystemExit):
        backfill.find_dsn()


def test_dsn_files_order_starts_with_live(tmp_path, backfill, monkeypatch):
    workspace = _fake_workspace(
        tmp_path,
        backfill,
        {"leltokens1.txt": "x", "leltokens2.txt": "y", "leltokens9.txt": "z"},
    )
    monkeypatch.setattr(backfill, "WORKSPACE", workspace)
    monkeypatch.setattr(backfill, "TOKENS_FILE", "leltokens2.txt")
    names = [p.name for p in backfill._dsn_files(None)]
    assert names.index("leltokens2.txt") < names.index("leltokens1.txt")


# ---------------------------------------------------------------- маркер -----
@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, []),
        ("", []),
        ("{не json", []),
        ('{"a": 1}', []),
        ('"19"', []),
        ("[19, 20]", [19, 20]),
        ('["21", 22, "мусор", null]', [21, 22]),
    ],
)
def test_parse_marker(backfill, raw, expected):
    assert backfill.parse_marker(raw) == expected


# --------------------------------------------------------- эмодзи и фразы -----
def test_load_list_falls_back_on_bad_value(backfill):
    assert backfill._load_list(None, ["👍"]) == ["👍"]
    assert backfill._load_list("[]", ["👍"]) == ["👍"]
    assert backfill._load_list('{"a":1}', ["👍"]) == ["👍"]
    assert backfill._load_list("[1, 2]", ["👍"]) == ["👍"]
    assert backfill._load_list('["🔥", "💯"]', ["👍"]) == ["🔥", "💯"]


# ------------------------------------------------------------------ маска -----
def test_masked_hides_password(backfill):
    dsn = f"postgresql://neondb_owner:super-secret@{LIVE_HOST}/neondb?ssl=require"
    masked = backfill.masked(dsn)
    assert "super-secret" not in masked
    assert masked == f"postgresql://neondb_owner:***@{LIVE_HOST}/neondb?ssl=require"


def test_dsn_line_shows_source(backfill, monkeypatch):
    monkeypatch.setattr(backfill, "_DSN_SOURCE", "leltokens2.txt")
    line = backfill.dsn_line("postgresql://user:pw@host/db")
    assert "pw" not in line
    assert "leltokens2.txt" in line


def test_plain_dsn_drops_asyncpg_driver(backfill):
    assert backfill.plain_dsn("postgresql+asyncpg://u:p@h/db") == "postgresql://u:p@h/db"
    assert backfill.plain_dsn("postgresql://u:p@h/db") == "postgresql://u:p@h/db"


# ----------------------------------------------------- поиск путей вверх -----
def test_find_up_uses_nearest_marker(tmp_path, backfill):
    marker_dir = tmp_path / "workspace" / "secrets"
    marker_dir.mkdir(parents=True)
    (marker_dir / "Get-Secret.ps1").write_text("", encoding="utf-8")
    nested = tmp_path / "workspace" / "monorepo" / "tools"
    nested.mkdir(parents=True)
    found = backfill._find_up(str(nested), Path("secrets") / "Get-Secret.ps1")
    assert found == str(tmp_path / "workspace")


def test_find_up_returns_none_without_marker(tmp_path, backfill):
    assert backfill._find_up(str(tmp_path), "нет-такого-файла") is None


# ------------------------------------------------------------- venv/asynpg ----
def test_venv_python_detects_windows_layout(tmp_path, backfill, monkeypatch):
    backend = tmp_path / "backend"
    (backend / ".venv" / "Scripts").mkdir(parents=True)
    (backend / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(backfill, "BACKEND", backend)
    assert backfill._venv_python() == str(backend / ".venv" / "Scripts" / "python.exe")


def test_venv_python_none_when_absent(tmp_path, backfill, monkeypatch):
    monkeypatch.setattr(backfill, "BACKEND", tmp_path / "backend")
    assert backfill._venv_python() is None
