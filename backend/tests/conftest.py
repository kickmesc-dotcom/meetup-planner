"""Общая настройка тестов.

Один файл на весь набор нужен ради одного: счётчики лимита частоты
(`app/api/guards.py`) живут в памяти процесса, а pytest прогоняет все тесты в
одном процессе. Без сброса лимит «вход 20 раз за 5 минут» копился бы между
разными тестами, и падение зависело бы от порядка файлов — то есть тест
проверял бы не приложение, а расположение тестов.
"""

from __future__ import annotations

import pytest

from app.api import guards


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Пустые счётчики перед каждым тестом."""
    guards.reset_rate_limits()
    yield
    guards.reset_rate_limits()
