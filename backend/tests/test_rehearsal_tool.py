"""Инструмент репетиции первого запуска действительно работает.

Проверяется не логика приложения (она в других тестах), а сам сценарий
разработчика: «одна команда — новая база с руководителем, вторая — новый
сотрудник, третья — вернуть человека в начало». Если этот инструмент сломается
молча, ручной прогон начнётся с получаса возни и снова перестанет быть
повторяемым.

Запуск через подпроцесс: утилита подменяет переменные окружения (`BOT_TOKEN`,
`DATABASE_URL`), и делать это внутри pytest-процесса — значит влиять на
остальные тесты.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "rehearsal.py"
PYTHON = sys.executable


def run(db: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # Инструмент печатает по-русски. Без явной кодировки подпроцесс на Windows
    # выводит текст в локальной кодировке (cp1251), и проверка «видно ли
    # название организации»
    # сравнивала бы кириллицу с «крякозябрами» — тест падал бы от локали
    # машины, а не от поломки инструмента. Кодировку задаём здесь, а не в самом
    # инструменте: человеку в консоли нужна локальная кодировка, тесту — utf-8.
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [PYTHON, str(TOOL), "--db", str(db), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
    )


def test_rehearsal_lifecycle(tmp_path: Path) -> None:
    db = tmp_path / "rehearsal.db"

    fresh = run(db, "fresh")
    assert fresh.returncode == 0, fresh.stderr[-2000:]
    assert "rehearsal" in fresh.stdout
    assert "manager@rehearsal.local" in fresh.stdout
    assert db.exists()

    staff = run(db, "new-staff", "--alias", "7")
    assert staff.returncode == 0, staff.stderr[-2000:]
    assert "staff-7@rehearsal.local" in staff.stdout

    status = run(db, "status")
    assert status.returncode == 0, status.stderr[-2000:]
    assert "Кофейня «Репетиция»" in status.stdout
    assert "owner" in status.stdout
    assert "staff-7@rehearsal.local" in status.stdout

    # Повторный `fresh` пересоздаёт базу: прошлый сотрудник исчезает.
    again = run(db, "fresh")
    assert again.returncode == 0, again.stderr[-2000:]
    after = run(db, "status")
    assert "staff-7@rehearsal.local" not in after.stdout


def test_rerun_returns_a_person_to_the_start(tmp_path: Path) -> None:
    db = tmp_path / "rehearsal.db"
    assert run(db, "fresh").returncode == 0
    assert run(db, "new-staff", "--alias", "3").returncode == 0

    # Профиля ещё нет: `rerun` — это «вернуть в начало», и если начинать
    # нечего, он не падает (идемпотентность важнее строгости).
    noop = run(db, "rerun", "staff-3@rehearsal.local")
    assert noop.returncode == 0

    # А вот поставить состояние профиля, которого нет, — ошибка: иначе
    # проверяющий сидел бы в уверенности, что экран переключён.
    missing_profile = run(db, "onboarding", "staff-3@rehearsal.local", "done")
    assert missing_profile.returncode != 0

    unknown = run(db, "rerun", "nobody@example.com")
    assert unknown.returncode != 0
