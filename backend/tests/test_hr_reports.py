"""SemiTaskBot: правила отчёта смены и пробелов по стандартам.

Проверяем то, что решает «ходит ли руководитель по отчёту»: кто попадает в
срез, что считается пробелом, как цифры превращаются в CSV и в текст бота.
Запросы к БД здесь не подменяются фейками — их закрывает интеграционный
`test_hr_flow_pg` на живом Postgres.

Env выставляем ДО импорта `app.main` — `Settings` требует BOT_TOKEN и т.п.
"""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("TG_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("MINI_APP_URL", "https://example.com")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")

from datetime import date  # noqa: E402

from app.db.hr_models import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_AUP,
    ROLE_EMPLOYEE,
    TASK_DONE,
    TASK_FAILED,
    TASK_NEW,
    TASK_ON_REVIEW,
    TASK_OVERDUE,
    Employee,
)
from app.services import hr_reports  # noqa: E402


def _employee(
    employee_id: int = 1,
    role: str = ROLE_AUP,
    department_id: int | None = 7,
) -> Employee:
    return Employee(id=employee_id, user_id=employee_id, role=role, department_id=department_id)


def _standard(**overrides) -> hr_reports.StandardCoverage:
    base = dict(
        standard_id=1,
        title="Гигиена рук",
        emoji="🧼",
        department_id=None,
        department_name=None,
        required=True,
        passed=2,
        total=3,
        missing=[hr_reports.PersonRef(employee_id=9, display_name="Пётр")],
    )
    base.update(overrides)
    return hr_reports.StandardCoverage(**base)


def _report(**overrides) -> hr_reports.ShiftReport:
    base = dict(
        work_date=date(2026, 10, 18),
        scope=hr_reports.SCOPE_DEPARTMENT,
        department_id=7,
        departments=[
            hr_reports.DepartmentRow(
                department_id=7,
                name="Кухня",
                emoji="🍳",
                employees=3,
                shifts_started=2,
                shifts_done=1,
                tasks_shift=4,
                tasks_done=2,
                tasks_on_review=1,
                tasks_overdue=1,
                issues_open=2,
                required_gaps=1,
            )
        ],
        employees_total=3,
        shifts_started=2,
        shifts_done=1,
        tasks_shift=4,
        tasks_done=2,
        tasks_on_review=1,
        tasks_overdue=1,
        tasks_open=3,
        issues_open=2,
        issues_new=1,
        standards=[_standard()],
        required_gaps=1,
    )
    base.update(overrides)
    return hr_reports.ShiftReport(**base)


# --------------------------------------------------------------------------
# Права и зона среза
# --------------------------------------------------------------------------


def test_manager_is_locked_to_own_department():
    """Чужой `department_id` в query не расширяет права руководителя."""
    viewer = _employee(role=ROLE_AUP, department_id=7)
    assert hr_reports.resolve_scope(viewer, 99) == (hr_reports.SCOPE_DEPARTMENT, 7)


def test_admin_may_pick_any_department_or_all():
    viewer = _employee(role=ROLE_ADMIN, department_id=None)
    assert hr_reports.resolve_scope(viewer) == (hr_reports.SCOPE_ALL, None)
    assert hr_reports.resolve_scope(viewer, 5) == (hr_reports.SCOPE_ALL, 5)


def test_employee_scope_does_not_widen_for_plain_employee():
    """Страховка от вызова сервиса в обход `AupDep`: отдел остаётся свой."""
    viewer = _employee(role=ROLE_EMPLOYEE, department_id=3)
    assert hr_reports.resolve_scope(viewer, 99) == (hr_reports.SCOPE_DEPARTMENT, 3)


# --------------------------------------------------------------------------
# Цифры
# --------------------------------------------------------------------------


def test_coverage_percent_never_divides_by_zero():
    assert hr_reports.coverage_percent(0, 0) == 0
    assert hr_reports.coverage_percent(2, 3) == 67
    assert hr_reports.coverage_percent(3, 3) == 100


def test_required_gap_only_for_required_and_incomplete():
    assert hr_reports.required_gap(_standard()) is True
    assert hr_reports.required_gap(_standard(passed=3)) is False
    # Необязательный стандарт — справочник, в пробелы не идёт.
    assert hr_reports.required_gap(_standard(required=False)) is False


def test_task_counts_splits_review_from_done():
    counts = hr_reports.task_counts(
        [TASK_DONE, TASK_ON_REVIEW, TASK_OVERDUE, TASK_NEW, TASK_FAILED, TASK_NEW]
    )
    assert counts[TASK_DONE] == 1
    assert counts[TASK_ON_REVIEW] == 1
    assert counts[TASK_OVERDUE] == 1
    assert counts[TASK_FAILED] == 1
    # `new` — не «провал» и не «готово», но в общем числе смены учитывается.
    assert counts["other"] == 2
    assert counts["total"] == 6


# --------------------------------------------------------------------------
# Выгрузка
# --------------------------------------------------------------------------


def test_csv_cell_escapes_separator_and_quotes():
    assert hr_reports.csv_cell("Кухня") == "Кухня"
    assert hr_reports.csv_cell('Пётр "Повар"') == '"Пётр ""Повар"""'
    assert hr_reports.csv_cell("первая;вторая") == '"первая;вторая"'
    # Перевод строки не должен рвать строку файла.
    assert "\n" not in hr_reports.csv_cell("a\nb")


def test_csv_contains_numbers_and_missing_names():
    text = hr_reports.to_csv(_report())
    assert "Отчёт смены;2026-10-18" in text
    assert "Смен закрыто;1" in text
    assert "Поручений на проверке;1" in text
    assert "Кухня;3;2;1;4;2;1;1;2;1" in text
    assert "Гигиена рук;да;2;3;67;Пётр" in text
    # Разделитель — `;`, строки — CRLF: так Excel открывает без «всё в одной колонке».
    assert "\r\n" in text


def test_telegram_text_lists_gaps_and_caps_them():
    gaps = [
        _standard(standard_id=index, title=f"Стандарт {index}")
        for index in range(1, 6)
    ]
    text = hr_reports.format_telegram(_report(standards=gaps), limit=2)
    assert "Смена 18.10.2026" in text
    assert "пробелов 5" in text
    assert "Стандарт 1" in text and "Стандарт 3" not in text
    assert "и ещё 3" in text


def test_telegram_text_without_gaps_says_all_passed():
    text = hr_reports.format_telegram(_report(standards=[_standard(passed=3)]))
    assert "сданы ✅" in text
