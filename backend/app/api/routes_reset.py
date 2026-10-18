"""Сброс текущей работы: предпросмотр и выполнение (двойное подтверждение).

`GET /preview` показывает, сколько удалится, и выдаёт подписанный токен.
`POST /execute` требует этот токен и слово `СБРОС`. Без предпросмотра вызвать
удаление нельзя: случайный повторный запрос без токена вернёт 400, а не
«удалили второй раз».

Права: `AupDep` — администратор убирает всё, руководитель только свой отдел.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import AupDep, SessionDep
from app.services import hr_access, hr_reset

router = APIRouter(prefix="/reset", tags=["reset"])


class ResetPreviewOut(BaseModel):
    scope: str
    is_admin: bool
    department_id: int | None
    counts: dict[str, int]
    notes: list[str]
    token: str
    expires_in_seconds: int


class ResetExecuteIn(BaseModel):
    """Двойное подтверждение: токен предпросмотра + слово."""

    token: str = Field(min_length=8, max_length=128)
    confirm: str = Field(min_length=1, max_length=32)


@router.get("/preview", response_model=ResetPreviewOut)
async def reset_preview(session: SessionDep, employee: AupDep) -> ResetPreviewOut:
    """Сухой счёт: что исчезнет. Ничего не меняет."""
    preview = await hr_reset.preview(session, employee)
    return ResetPreviewOut(
        scope=preview.scope.description,
        is_admin=preview.scope.is_admin,
        department_id=preview.scope.department_id,
        counts=preview.counts.as_dict(),
        notes=preview.notes,
        token=preview.token,
        expires_in_seconds=preview.expires_in_seconds,
    )


@router.post("/execute", response_model=dict[str, int])
async def reset_execute(
    body: ResetExecuteIn, session: SessionDep, employee: AupDep
) -> dict[str, int]:
    """Удалить показанное. Требует свежий предпросмотр и слово `СБРОС`."""
    try:
        counts = await hr_reset.execute(
            session, employee, token=body.token, confirm=body.confirm
        )
    except hr_access.HrAccessError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return counts.as_dict()


__all__ = ["router"]
