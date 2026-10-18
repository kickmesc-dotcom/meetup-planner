"""Отчёты для руководителя: смена, стандарты и выгрузка CSV.

Сводка кабинета (`/api/admin/dashboard`) отвечает «что горит сейчас».
Здесь — срез на выбранную дату и выгрузка, которую можно отправить в чат
владельцу или открыть в Excel.

Права те же, что у сводки: `AupDep`. Руководитель отдела видит только свой
отдел, даже если в query пришёл чужой `department_id` — подмену делает
`hr_reports.resolve_scope`, а не клиент.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import AupDep, SessionDep
from app.services import hr_departments, hr_reports

router = APIRouter(prefix="/reports", tags=["reports"])


async def _check_department(session, department_id: int | None) -> None:  # noqa: ANN001
    """Админ выбирает отдел списком — несуществующий id это 404, а не пустой отчёт."""
    if department_id is None:
        return
    if await hr_departments.get_department(session, department_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="department_not_found")


@router.get("/shift", response_model=hr_reports.ShiftReport)
async def shift_report(
    session: SessionDep,
    employee: AupDep,
    # Без `Query(...)` в дефолте: линтер справедливо ругается на вызов в
    # сигнатуре, а FastAPI и так читает `date | None` из query.
    on: date | None = None,
    department_id: int | None = None,
) -> hr_reports.ShiftReport:
    """Полный срез смены: люди, чек-листы, поручения, проблемы, стандарты."""
    await _check_department(session, department_id)
    return await hr_reports.build_shift_report(
        session, viewer=employee, on=on, department_id=department_id
    )


@router.get("/standards", response_model=list[hr_reports.StandardCoverage])
async def standards_report(
    session: SessionDep,
    employee: AupDep,
    department_id: int | None = None,
    required_only: bool = True,
) -> list[hr_reports.StandardCoverage]:
    """Пробелы по стандартам: кто из отдела ещё не сдал инструкцию."""
    await _check_department(session, department_id)
    return await hr_reports.standards_gaps(
        session,
        viewer=employee,
        department_id=department_id,
        required_only=required_only,
    )


@router.get("/shift.csv")
async def shift_report_csv(
    session: SessionDep,
    employee: AupDep,
    on: date | None = None,
    department_id: int | None = None,
) -> Response:
    """Тот же отчёт файлом. BOM — чтобы Excel не ломал кириллицу."""
    await _check_department(session, department_id)
    report = await hr_reports.build_shift_report(
        session, viewer=employee, on=on, department_id=department_id
    )
    body = "\ufeff" + hr_reports.to_csv(report)
    filename = f"shift-{report.work_date.isoformat()}.csv"
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]
