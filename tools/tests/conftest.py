"""Стенд для тестов `tools/switch-db.py`.

Файл называется с дефисом (`switch-db.py`), поэтому обычным `import` его не
взять — грузим через `importlib` по пути и отдаём тестам фикстурой.

Запуск из корня монорепо (pytest берём из venv бэкенда):

    backend/.venv/Scripts/python.exe -m pytest tools/tests -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SWITCH_DB_PATH = Path(__file__).resolve().parents[1] / "switch-db.py"


@pytest.fixture(scope="session")
def switch_db():
    spec = importlib.util.spec_from_file_location("switch_db", SWITCH_DB_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Регистрируем в sys.modules: модулю это нужно, чтобы видеть себя «как обычно».
    sys.modules["switch_db"] = module
    spec.loader.exec_module(module)
    return module
