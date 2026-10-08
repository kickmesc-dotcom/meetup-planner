"""Стенд для тестов вспомогательных скриптов `tools/`.

Файлы называются с дефисом (`switch-db.py`, `backfill-media-reactions.py`),
поэтому обычным `import` их не взять — грузим через `importlib` по пути и
отдаём тестам фикстурами.

Запуск из корня монорепо (pytest берём из venv бэкенда):

    backend/.venv/Scripts/python.exe -m pytest tools/tests -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1]
SWITCH_DB_PATH = TOOLS_DIR / "switch-db.py"
BACKFILL_PATH = TOOLS_DIR / "backfill-media-reactions.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Регистрируем в sys.modules: модулю это нужно, чтобы видеть себя «как обычно».
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def switch_db():
    return _load_module("switch_db", SWITCH_DB_PATH)


@pytest.fixture(scope="session")
def backfill():
    return _load_module("backfill_media_reactions", BACKFILL_PATH)
