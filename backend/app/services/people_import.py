"""Импорт людей и графика из таблицы (B2B_PLATFORM_PLAN, шаг 6.3).

Зачем это вообще. Завести двадцать человек и неделю графика руками — это
двадцать форм и сто кликов; на живом внедрении так и не делают: руководитель
присылает таблицу, которую уже ведёт. Пока импорта не было, первый день клиента
выглядел как «мы заведём сами, пришлите доступ», то есть ручная работа на нашей
стороне — ровно то, чего B2B-продукт не должен требовать.

Правила, из которых собран этот модуль:

* **Сначала показать, потом записать.** `preview` ничего не пишет и возвращает
  построчный разбор: что создастся, что уже есть, что не разобралось и почему.
  Импорт без предпросмотра — это лотерея: файл из Excel приходит с чужими
  колонками и пустыми строками, и узнать об этом после записи неприятно.
* **Ошибка в строке не отменяет остальные.** Двадцать человек из двадцати
  одного должны завестись, а не «исправьте всё и пришлите заново». Строка с
  ошибкой просто не применяется, и её причина названа по-русски.
* **Существующее не перезаписывается.** Человек уже в пуле — `skip`, а не
  «обновим имя на то, что в файле»: файл мог быть старым, а имя в приложении
  уже поправили руками.
* **CSV, а не xlsx.** Excel сохраняет «CSV UTF-8» одним пунктом меню, а разбор
  xlsx тянет зависимость на 10 МБ и открывает тему формул и объединённых
  ячеек. Обмен с iiko/1С всё равно идёт CSV — тот же формат пригодится в 6.2.
* **Границы названы числом.** 500 строк и 500 КБ на файл: больше — это уже
  перенос базы, а не «завести команду», и для него нужен отдельный разговор.

Колонки узнаются по русским и английским именам (см. `COLUMN_ALIASES`), порядок
не важен, лишние колонки игнорируются. Режим определяется по данным: есть
колонка «дата» — это график, иначе люди.
"""

from __future__ import annotations

import csv
import io
import re
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    ROLE_ADMIN,
    ROLE_AUP,
    ROLE_EMPLOYEE,
    ROLES,
    SHIFT_ABSENT,
    SHIFT_DAYOFF,
    SHIFT_PLANNED,
    SHIFT_SICK,
    SHIFT_STATUSES,
    SHIFT_VACATION,
    SHIFT_WORKED,
    Department,
    Employee,
    HrShift,
)
from app.db.models import User
from app.db.seed import color_for_user

# Границы названы, а не «разумные»: 500 строк — это команда на 50 человек с
# неделей графика. Больше похоже на перенос базы, и там нужен другой разговор.
MAX_ROWS = 500
MAX_TEXT = 500_000
# Имя в `users.display_name` живёт с тем же потолком, что и в остальном пуле.
MAX_NAME = 96

Kind = Literal["people", "shifts"]
KINDS: tuple[str, ...] = ("people", "shifts")


class ImportProblem(Exception):
    """Отказ целиком: файл не разобрать, колонок нет, строк слишком много.

    Построчные проблемы — это не исключение, а `RowResult` с `action="error"`:
    одна плохая строка не должна отменять импорт остальных.
    """


COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("имя", "фио", "сотрудник", "name", "employee", "full_name"),
    "position": ("должность", "профессия", "position", "title"),
    "department": ("подразделение", "отдел", "зал", "department", "division", "hall"),
    # `id` в одиночку не берём: в таблице это чаще номер строки, чем Telegram.
    "telegram": ("telegram_id", "telegram", "tg_id", "tg", "telegramid", "chat_id"),
    "role": ("роль", "role"),
    "day": ("дата", "день", "date", "day"),
    "status": ("статус", "status", "тип", "вид"),
    "start": ("начало", "с", "start", "from", "start_time"),
    "end": ("конец", "по", "end", "to", "end_time"),
}

ROLE_ALIASES: dict[str, str] = {
    "employee": ROLE_EMPLOYEE,
    "сотрудник": ROLE_EMPLOYEE,
    "исполнитель": ROLE_EMPLOYEE,
    "staff": ROLE_EMPLOYEE,
    "aup": ROLE_AUP,
    "руководитель": ROLE_AUP,
    "управляющий": ROLE_AUP,
    "менеджер": ROLE_AUP,
    "manager": ROLE_AUP,
    "admin": ROLE_ADMIN,
    "администратор": ROLE_ADMIN,
    "владелец": ROLE_ADMIN,
    "owner": ROLE_ADMIN,
}

STATUS_ALIASES: dict[str, str] = {
    "planned": SHIFT_PLANNED,
    "смена": SHIFT_PLANNED,
    "план": SHIFT_PLANNED,
    "запланирована": SHIFT_PLANNED,
    "работает": SHIFT_PLANNED,
    "worked": SHIFT_WORKED,
    "отработал": SHIFT_WORKED,
    "отработана": SHIFT_WORKED,
    "sick": SHIFT_SICK,
    "больничный": SHIFT_SICK,
    "absent": SHIFT_ABSENT,
    "не пришёл": SHIFT_ABSENT,
    "не пришел": SHIFT_ABSENT,
    "прогул": SHIFT_ABSENT,
    "dayoff": SHIFT_DAYOFF,
    "выходной": SHIFT_DAYOFF,
    "vacation": SHIFT_VACATION,
    "отпуск": SHIFT_VACATION,
}

_DATE_FORMATS: tuple[str, ...] = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y")
_TIME_RE = re.compile(r"^(\d{1,2})[:.](\d{2})$")


@dataclass
class RowResult:
    """Одна строка файла после разбора. `payload` в ответ не уезжает."""

    row: int
    action: str  # create | update | skip | error
    name: str
    detail: str = ""
    errors: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "action": self.action,
            "name": self.name,
            "detail": self.detail,
            "errors": list(self.errors),
        }


@dataclass
class Preview:
    kind: str
    delimiter: str
    total: int
    create: int
    update: int
    skip: int
    errors: int
    departments: list[str]
    rows: list[RowResult]

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "delimiter": self.delimiter,
            "total": self.total,
            "create": self.create,
            "update": self.update,
            "skip": self.skip,
            "error": self.errors,
            "departments": self.departments,
            "rows": [row.as_dict() for row in self.rows],
        }


def _norm(value: str) -> str:
    """Заголовок к сравнимому виду: регистр, «ё», пробелы и точки."""
    text = (value or "").strip().lower().replace("ё", "е")
    return text.replace(" ", "_").replace(".", "_")


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _sniff(text: str) -> tuple[str, list[list[str]]]:
    """Разделитель и строки. Excel в русской локали сохраняет `;`."""
    sample = text[:4096]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t").delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if any(_clean(cell) for cell in row)]
    return delimiter, rows


def _map_columns(header: list[str]) -> dict[str, int]:
    normalized = {_norm(cell): index for index, cell in enumerate(header)}
    mapping: dict[str, int] = {}
    for key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            index = normalized.get(_norm(alias))
            if index is not None:
                mapping[key] = index
                break
    return mapping


def _cell(row: list[str], mapping: dict[str, int], key: str) -> str:
    index = mapping.get(key)
    if index is None or index >= len(row):
        return ""
    return _clean(row[index])


def _parse_day(value: str) -> date | None:
    """`2026-10-21`, `21.10.2026`, `21/10/2026`, `21-10-2026`.

    Excel в русской локали отдаёт точки, ISO — точки-тире: оба варианта живут
    в одном файле, если его склеили из двух источников.
    """
    text = value.strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(value: str) -> time | None:
    text = value.strip()
    if not text:
        return None
    match = _TIME_RE.match(text)
    if not match:
        return None
    hours, minutes = int(match.group(1)), int(match.group(2))
    if hours > 23 or minutes > 59:
        return None
    return time(hour=hours, minute=minutes)


def _parse_telegram(value: str) -> int | None:
    text = value.strip().lstrip("@")
    if not text:
        return None
    digits = re.sub(r"[\s_-]", "", text)
    if not digits.isdigit():
        return None
    number = int(digits)
    return number if number > 0 else None


def _prepare(
    text: str, kind: str | None
) -> tuple[str, str, dict[str, int], list[list[str]]]:
    """Общие проверки файла: не пустой, не гигантский, колонки на месте."""
    content = (text or "").lstrip("\ufeff")
    if not content.strip():
        raise ImportProblem("empty_file")
    if len(content) > MAX_TEXT:
        raise ImportProblem("file_too_large")
    delimiter, rows = _sniff(content)
    if len(rows) < 2:
        raise ImportProblem("no_rows")
    header, data = rows[0], rows[1:]
    if len(data) > MAX_ROWS:
        raise ImportProblem("too_many_rows")
    mapping = _map_columns(header)
    detected: str = "shifts" if "day" in mapping else "people"
    mode = (kind or detected).strip()
    if mode not in KINDS:
        raise ImportProblem("bad_kind")
    if mode == "people" and "name" not in mapping:
        raise ImportProblem("no_name_column")
    if mode == "shifts":
        if "day" not in mapping:
            raise ImportProblem("no_date_column")
        if "name" not in mapping and "telegram" not in mapping:
            raise ImportProblem("no_person_column")
    return mode, delimiter, mapping, data


async def _people_index(session: AsyncSession) -> tuple[dict[int, int], dict[str, int]]:
    """Существующие сотрудники: по Telegram-id и по имени (в нижнем регистре)."""
    rows = await session.execute(
        select(Employee.id, Employee.user_id, User.telegram_id, User.display_name).join(
            User, User.id == Employee.user_id
        )
    )
    by_telegram: dict[int, int] = {}
    by_name: dict[str, int] = {}
    for employee_id, _user_id, telegram_id, display_name in rows.all():
        if telegram_id is not None:
            by_telegram[int(telegram_id)] = int(employee_id)
        if display_name:
            by_name[str(display_name).strip().lower()] = int(employee_id)
    return by_telegram, by_name


async def _department_index(session: AsyncSession) -> tuple[dict[str, int], list[str]]:
    rows = (
        await session.scalars(select(Department).where(Department.is_active.is_(True)))
    ).all()
    by_key: dict[str, int] = {}
    names: list[str] = []
    for department in rows:
        names.append(str(department.name))
        by_key[str(department.name).strip().lower()] = int(department.id)
        by_key[str(department.slug).strip().lower()] = int(department.id)
    names.sort()
    return by_key, names


def _plan_people(
    data: list[list[str]],
    mapping: dict[str, int],
    by_telegram: dict[int, int],
    by_name: dict[str, int],
    departments: dict[str, int],
) -> list[RowResult]:
    results: list[RowResult] = []
    seen_telegram: set[int] = set()
    seen_name: set[str] = set()

    for offset, raw in enumerate(data, start=2):
        name = _cell(raw, mapping, "name")[:MAX_NAME]
        telegram = _parse_telegram(_cell(raw, mapping, "telegram"))
        department_raw = _cell(raw, mapping, "department")
        position = _cell(raw, mapping, "position")[:64] or None
        role_raw = _cell(raw, mapping, "role").strip().lower()

        problems: list[str] = []
        if not name:
            problems.append("Пустое имя")
        elif name.lower() in seen_name:
            problems.append("Такой человек уже есть в файле")
        role = ROLE_EMPLOYEE
        if role_raw:
            role = ROLE_ALIASES.get(role_raw, "")
            if role not in ROLES:
                problems.append(f"Неизвестная роль: {role_raw}")
        department_id: int | None = None
        if department_raw:
            department_id = departments.get(department_raw.lower())
            if department_id is None:
                problems.append(f"Нет подразделения «{department_raw}»")
        if telegram is not None and telegram in seen_telegram:
            problems.append("Такой Telegram-id уже есть в файле")

        result = RowResult(row=offset, action="error", name=name or "—")
        if problems:
            result.errors = problems
            result.detail = problems[0]
            results.append(result)
            continue

        if name:
            seen_name.add(name.lower())
        if telegram is not None:
            seen_telegram.add(telegram)

        existing_id = None
        if telegram is not None:
            existing_id = by_telegram.get(telegram)
        if existing_id is None and name:
            existing_id = by_name.get(name.lower())
        if existing_id is not None:
            result.action = "skip"
            result.detail = "Уже в пуле сотрудников"
            results.append(result)
            continue

        result.action = "create"
        result.payload = {
            "name": name,
            "telegram_id": telegram,
            "department_id": department_id,
            "position": position,
            "role": role,
        }
        results.append(result)
    return results


async def _plan_shifts(
    session: AsyncSession,
    data: list[list[str]],
    mapping: dict[str, int],
    overwrite: bool,
) -> list[RowResult]:
    by_telegram, by_name = await _people_index(session)
    results: list[RowResult] = []
    seen: set[tuple[int, date]] = set()
    existing: set[tuple[int, date]] = set()
    employee_ids: set[int] = set()
    days: set[date] = set()

    for offset, raw in enumerate(data, start=2):
        name = _cell(raw, mapping, "name")
        telegram = _parse_telegram(_cell(raw, mapping, "telegram"))
        day_raw = _cell(raw, mapping, "day")
        status_raw = _cell(raw, mapping, "status").strip().lower()
        start_raw = _cell(raw, mapping, "start")
        end_raw = _cell(raw, mapping, "end")

        problems: list[str] = []
        employee_id = by_telegram.get(telegram) if telegram is not None else None
        if employee_id is None and name:
            employee_id = by_name.get(name.lower())
        if employee_id is None:
            problems.append(
                "Сотрудник не найден — сначала импортируйте людей"
                if name or telegram
                else "Не указан сотрудник"
            )
        day = _parse_day(day_raw)
        if day is None:
            problems.append(f"Дата не разобрана: {day_raw or '—'}")
        status = SHIFT_PLANNED
        if status_raw:
            status = STATUS_ALIASES.get(status_raw, "")
            if status not in SHIFT_STATUSES:
                problems.append(f"Неизвестный статус: {status_raw}")
        starts_at = _parse_time(start_raw) if start_raw else None
        if start_raw and starts_at is None:
            problems.append(f"Время начала не разобрано: {start_raw}")
        ends_at = _parse_time(end_raw) if end_raw else None
        if end_raw and ends_at is None:
            problems.append(f"Время конца не разобрано: {end_raw}")

        result = RowResult(row=offset, action="error", name=name or "—")
        if problems:
            result.errors = problems
            result.detail = problems[0]
            results.append(result)
            continue
        assert employee_id is not None and day is not None  # для mypy
        if (employee_id, day) in seen:
            result.errors = ["Эта смена уже есть в файле"]
            result.detail = result.errors[0]
            results.append(result)
            continue
        seen.add((employee_id, day))
        employee_ids.add(employee_id)
        days.add(day)
        # `pending` — «строка разобралась, судьбу решим после запроса о
        # существующих сменах». Без отдельного значения второй проход ниже
        # принимал бы её за ошибку: по умолчанию у строки как раз `error`.
        result.action = "pending"
        result.payload = {
            "employee_id": employee_id,
            "day": day,
            "status": status,
            "starts_at": starts_at,
            "ends_at": ends_at,
        }
        results.append(result)

    # Один запрос на все пары: файл на 500 строк не должен ходить в базу 500 раз.
    if employee_ids and days:
        rows = await session.scalars(
            select(HrShift).where(
                HrShift.employee_id.in_(employee_ids), HrShift.day.in_(days)
            )
        )
        existing = {(int(row.employee_id), row.day) for row in rows.all()}

    for result in results:
        if result.action != "error":
            key = (int(result.payload["employee_id"]), result.payload["day"])
            if key in existing:
                result.action = "update" if overwrite else "skip"
                result.detail = (
                    "Смена будет перезаписана" if overwrite else "Смена уже стоит"
                )
            else:
                result.action = "create"
    return results


async def plan(
    session: AsyncSession,
    *,
    text: str,
    kind: str | None = None,
    overwrite: bool = False,
) -> tuple[str, str, list[RowResult], dict[str, int]]:
    """Разобрать файл и решить судьбу каждой строки, ничего не записывая."""
    mode, delimiter, mapping, data = _prepare(text, kind)
    if mode == "people":
        by_telegram, by_name = await _people_index(session)
        departments, names = await _department_index(session)
        rows = _plan_people(data, mapping, by_telegram, by_name, departments)
        return mode, delimiter, rows, {"departments": names}  # type: ignore[dict-item]
    rows = await _plan_shifts(session, data, mapping, overwrite)
    return mode, delimiter, rows, {}


def _counts(rows: list[RowResult]) -> dict[str, int]:
    return {
        "create": sum(1 for row in rows if row.action == "create"),
        "update": sum(1 for row in rows if row.action == "update"),
        "skip": sum(1 for row in rows if row.action == "skip"),
        "error": sum(1 for row in rows if row.action == "error"),
    }


async def preview(
    session: AsyncSession,
    *,
    text: str,
    kind: str | None = None,
    overwrite: bool = False,
) -> Preview:
    mode, delimiter, rows, extra = await plan(
        session, text=text, kind=kind, overwrite=overwrite
    )
    counts = _counts(rows)
    return Preview(
        kind=mode,
        delimiter=delimiter,
        total=len(rows),
        create=counts["create"],
        update=counts["update"],
        skip=counts["skip"],
        errors=counts["error"],
        departments=list(extra.get("departments", [])),
        rows=rows,
    )


async def apply(
    session: AsyncSession,
    *,
    text: str,
    kind: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Создать всё, что прошло проверку. Ошибочные строки просто пропускаются."""
    mode, _delimiter, rows, _extra = await plan(
        session, text=text, kind=kind, overwrite=overwrite
    )
    created = 0
    updated = 0

    if mode == "people":
        for row in rows:
            if row.action != "create":
                continue
            data = row.payload
            telegram_id = data.get("telegram_id")
            user = (
                await session.scalar(select(User).where(User.telegram_id == telegram_id))
                if telegram_id is not None
                else None
            )
            if user is None:
                name = str(data["name"])
                user = User(
                    telegram_id=telegram_id,
                    display_name=name,
                    # Цвет — косметика, но стабильная: crc32 от имени, а не hash()
                    # (у hash() значение меняется между процессами).
                    color_hex=color_for_user(zlib.crc32(name.encode("utf-8")) % 1000),
                )
                session.add(user)
                await session.flush()
            session.add(
                Employee(
                    user_id=int(user.id),
                    role=str(data.get("role") or ROLE_EMPLOYEE),
                    department_id=data.get("department_id"),
                    position=data.get("position"),
                )
            )
            await session.flush()
            created += 1
    else:
        for row in rows:
            if row.action not in {"create", "update"}:
                continue
            data = row.payload
            shift = await session.scalar(
                select(HrShift).where(
                    HrShift.employee_id == data["employee_id"],
                    HrShift.day == data["day"],
                )
            )
            if shift is None:
                session.add(
                    HrShift(
                        employee_id=int(data["employee_id"]),
                        day=data["day"],
                        status=str(data["status"]),
                        starts_at=data.get("starts_at"),
                        ends_at=data.get("ends_at"),
                    )
                )
                created += 1
            else:
                shift.status = str(data["status"])
                shift.starts_at = data.get("starts_at")
                shift.ends_at = data.get("ends_at")
                updated += 1
            await session.flush()

    counts = _counts(rows)
    return {
        "kind": mode,
        "created": created,
        "updated": updated,
        "skipped": counts["skip"],
        "errors": counts["error"],
        "rows": [row.as_dict() for row in rows],
    }


__all__ = [
    "ImportProblem",
    "KINDS",
    "MAX_ROWS",
    "MAX_TEXT",
    "Preview",
    "RowResult",
    "apply",
    "plan",
    "preview",
]
