"""Материалы смены (Google Sheets): чтение из кеша и ручное обновление."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import AupDep, EmployeeDep, SessionDep
from app.services import hr_materials

router = APIRouter(tags=["materials"])


class MaterialsOut(BaseModel):
    id: int
    title: str
    emoji: str | None
    url: str
    synced_at: datetime | None
    # Ошибка последней попытки: при наличии старых данных они остаются.
    sync_error: str | None
    stale: bool
    rows: list[list[str]]
    columns: int


def _out(source, *, now: datetime | None = None) -> MaterialsOut:  # noqa: ANN001
    rows = hr_materials.decode_rows(source)
    return MaterialsOut(
        id=int(source.id),
        title=source.title,
        emoji=source.emoji,
        url=source.url,
        synced_at=source.synced_at,
        sync_error=source.sync_error,
        stale=hr_materials.is_stale(source, now=now),
        rows=rows,
        columns=max((len(row) for row in rows), default=0),
    )


@router.get("/materials", response_model=list[MaterialsOut])
async def materials(session: SessionDep, employee: EmployeeDep) -> list[MaterialsOut]:
    """График, меню и методичка — из последнего удачного снимка.

    Устаревшие источники обновляются «на лету», но ответ не ждёт сети, если
    обновление уже идёт: показываем то, что есть, и помечаем `stale`.
    """
    sources = await hr_materials.visible_sources(session, employee)
    await hr_materials.refresh_stale(session, sources)
    return [_out(source) for source in sources]


@router.post("/materials/{source_id}/refresh", response_model=MaterialsOut)
async def refresh_material(
    source_id: int, session: SessionDep, _: AupDep
) -> MaterialsOut:
    """Обновить сейчас (руководитель): удобно после правки графика в Google."""
    try:
        source = await hr_materials.refresh_one(session, source_id)
    except hr_materials.MaterialsError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _out(source)
