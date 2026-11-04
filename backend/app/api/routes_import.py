"""Импорт людей и графика из CSV (B2B_PLATFORM_PLAN, шаг 6.3).

Права — `aup`: это работа руководителя, а не сотрудника. Владелец платформы
тоже проходит (он `admin` в своей организации).

Почему отдельный роутер, а не две ручки в `routes_hr`: у импорта своя тема и
свой тест на адрес. Урок 04.11.2026 — фронт звал `/api/hr/notify-prefs`, а
ручка жила на `/api/notify-prefs`; здесь путь объявлен в одном месте и
закреплён тестом `tests/people_import_paths.test.py`.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import AupDep, SessionDep
from app.db.models import User
from app.services import audit, people_import

router = APIRouter(tags=["import"])

# Коды отказа целиком → человеческий текст на клиенте. Сервер не пишет фразы
# интерфейса: их место в словаре фронта, иначе английский экран показывал бы
# русскую ошибку.
PROBLEM_TEXT: dict[str, str] = {
    "empty_file": "файл пустой",
    "file_too_large": "файл больше 500 КБ",
    "no_rows": "в файле нет строк данных",
    "too_many_rows": "в файле больше 500 строк",
    "bad_kind": "неизвестный тип импорта",
    "no_name_column": "нет колонки с именем",
    "no_date_column": "нет колонки с датой",
    "no_person_column": "нет колонки с сотрудником",
}


class ImportIn(BaseModel):
    """Файл приходит текстом: CSV — это текст, а разбор на сервере один.

    `filename` необязателен и нужен только журналу: по нему видно, что
    загружали. `overwrite` по умолчанию `False` — существующую смену нельзя
    стереть случайным импортом.
    """

    text: str = Field(min_length=1, max_length=people_import.MAX_TEXT)
    filename: str | None = Field(None, max_length=200)
    kind: Literal["people", "shifts"] | None = None
    overwrite: bool = False


class ImportRowOut(BaseModel):
    row: int
    action: str
    name: str
    detail: str
    errors: list[str]


class ImportPreviewOut(BaseModel):
    kind: str
    delimiter: str
    total: int
    create: int
    update: int
    skip: int
    error: int
    departments: list[str]
    rows: list[ImportRowOut]


class ImportResultOut(BaseModel):
    kind: str
    created: int
    updated: int
    skipped: int
    errors: int
    rows: list[ImportRowOut]


def _problem(exc: people_import.ImportProblem) -> HTTPException:
    code = str(exc)
    return HTTPException(
        status.HTTP_400_BAD_REQUEST,
        detail=code if code in PROBLEM_TEXT else "import_failed",
    )


@router.post("/import/preview", response_model=ImportPreviewOut)
async def preview_import(
    body: ImportIn, session: SessionDep, employee: AupDep
) -> ImportPreviewOut:
    """Показать, что произойдёт, ничего не записывая."""
    try:
        result = await people_import.preview(
            session, text=body.text, kind=body.kind, overwrite=body.overwrite
        )
    except people_import.ImportProblem as exc:
        raise _problem(exc) from exc
    return ImportPreviewOut(**result.as_dict())


@router.post("/import/apply", response_model=ImportResultOut)
async def apply_import(
    body: ImportIn, session: SessionDep, employee: AupDep
) -> ImportResultOut:
    """Применить разбор. Строки с ошибками не применяются, остальные — да."""
    try:
        data = await people_import.apply(
            session, text=body.text, kind=body.kind, overwrite=body.overwrite
        )
    except people_import.ImportProblem as exc:
        raise _problem(exc) from exc

    actor = await session.get(User, int(employee.user_id))
    await audit.record(
        session,
        org_id=int(employee.org_id),
        action="import.people" if data["kind"] == "people" else "import.shifts",
        user=actor,
        target_type=data["kind"],
        details={
            "created": data["created"],
            "updated": data["updated"],
            "skipped": data["skipped"],
            "errors": data["errors"],
            "filename": body.filename,
        },
    )
    await session.commit()
    return ImportResultOut(**data)
