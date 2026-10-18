"""SemiTaskBot: проверяем, что миграции HR-ядра и ORM-модели не разъезжаются.

Зачем. Миграцию нельзя прогнать в CI: в проекте нет Postgres-стенда (см.
`tests/test_game_core.py` — везде лёгкие фейки вместо живой БД). Но именно
рассинхрон «модель добавили, колонку в миграцию забыли» ловится только на
проде и очень больно (`UndefinedColumn` в рантайме).

Здесь мы делаем это дёшево и без БД: перехватываем `op.create_table(...)` и
`op.add_column(...)` из файлов миграций и сверяем множество таблиц/колонок с
`Base.metadata`. Тест не знает про SQL-типы и констрейнты — только про «такая
таблица и такие колонки объявлены в обоих местах», чего достаточно, чтобы
поймать опечатку.

Миграции применяются накопительно, в порядке из `HR_MIGRATIONS`: новая
миграция HR-ядра должна быть добавлена туда же, иначе её колонки не попадут в
сверку (и рассинхрон снова пролезет на прод).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import sqlalchemy as sa

import app.db.models  # noqa: F401  — регистрирует таблицы, включая hr_models
from app.db.base import Base

MIGRATION_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"

# Порядок важен: 0029 создаёт таблицы, 0030 добавляет к ним колонки,
# 0031 заводит таблицу скрытых ачивок.
HR_MIGRATIONS: tuple[str, ...] = (
    "0029_hr_core.py",
    "0030_hr_badges_demo.py",
    "0031_hr_achievements.py",
    "0032_hr_training_roles.py",
    "0033_hr_issue_journal.py",
    "0034_hr_handovers.py",
    "0035_task_modes_assignments.py",
)

# Таблицы, которые заводит именно эта миграция (HR-ядро Этапа 1).
HR_TABLES = {
    "departments",
    "employees",
    "checklist_templates",
    "checklist_items",
    "checklist_runs",
    "checklist_completions",
    "tasks",
    "task_events",
    "task_issues",
    "task_photos",
    "useful_links",
    "feedback_questions",
    "feedback_answers",
    "employee_achievements",
    "employee_training_steps",
    "hr_issues",
    "hr_issue_events",
    "hr_handovers",
    "hr_handover_items",
    "task_assignments",
}


class _CapturingOp:
    """Минимальная замена `alembic.op`, собирающая вызовы create_table."""

    def __init__(self) -> None:
        self.tables: dict[str, set[str]] = {}

    def create_table(self, name: str, *args: Any, **_kw: Any) -> None:
        columns: set[str] = set()
        for arg in args:
            if isinstance(arg, sa.Column):
                columns.add(arg.name)
        self.tables[name] = columns

    def create_index(self, *_a: Any, **_kw: Any) -> None:
        return None

    def drop_index(self, *_a: Any, **_kw: Any) -> None:
        return None

    def drop_constraint(self, *_a: Any, **_kw: Any) -> None:
        return None

    def create_check_constraint(self, *_a: Any, **_kw: Any) -> None:
        return None

    def drop_table(self, *_a: Any, **_kw: Any) -> None:
        return None

    def drop_column(self, *_a: Any, **_kw: Any) -> None:
        return None

    def add_column(self, table: str, column: sa.Column, *_a: Any, **_kw: Any) -> None:
        self.tables.setdefault(table, set()).add(column.name)


def _apply_migration(path: Path, captured: _CapturingOp) -> None:
    """Прогнать `upgrade()` из файла миграции с подменённым `alembic.op`.

    В миграции стоит `from alembic import op` — этот импорт резолвится по
    атрибуту `op` пакета `alembic` (и по `sys.modules['alembic.op']`). Поэтому
    подменяем ОБА до импорта файла, а потом возвращаем как было.
    """
    import alembic

    saved_attr = alembic.op
    saved_module = sys.modules.get("alembic.op")
    alembic.op = captured  # type: ignore[assignment]
    sys.modules["alembic.op"] = captured  # type: ignore[assignment]
    try:
        spec = importlib.util.spec_from_file_location(
            f"_hr_migration_{path.stem}", path
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.upgrade()
    finally:
        alembic.op = saved_attr  # type: ignore[assignment]
        if saved_module is not None:
            sys.modules["alembic.op"] = saved_module
        else:
            sys.modules.pop("alembic.op", None)


def _run_migration_upgrade() -> dict[str, set[str]]:
    """Схема после ВСЕХ HR-миграций — то, что реально получит база."""
    captured = _CapturingOp()
    for name in HR_MIGRATIONS:
        _apply_migration(MIGRATION_DIR / name, captured)
    return captured.tables


def test_migration_creates_exactly_the_hr_tables():
    created = _run_migration_upgrade()
    assert set(created) == HR_TABLES


def test_migration_columns_match_orm_models():
    """Каждая таблица миграции существует в metadata и совпадает по колонкам."""
    created = _run_migration_upgrade()
    mismatches: list[str] = []
    for table, migration_columns in sorted(created.items()):
        orm = Base.metadata.tables.get(table)
        if orm is None:
            mismatches.append(f"{table}: нет в Base.metadata (забыт импорт?)")
            continue
        orm_columns = set(orm.columns.keys())
        only_migration = migration_columns - orm_columns
        only_model = orm_columns - migration_columns
        if only_migration:
            mismatches.append(f"{table}: только в миграции {sorted(only_migration)}")
        if only_model:
            mismatches.append(f"{table}: только в модели {sorted(only_model)}")
    assert not mismatches, "Рассинхрон моделей и миграции:\n" + "\n".join(mismatches)


def test_hr_models_are_registered_in_metadata():
    """Прямая проверка: импорт `app.db.models` подтягивает hr_models."""
    missing = HR_TABLES - set(Base.metadata.tables)
    assert not missing, f"не зарегистрированы в метаданных: {sorted(missing)}"
