"""Ручки фото: загрузка из мини-аппа и публичная выдача байтов.

Публичная выдача нужна потому, что `<img>` не умеет отправлять заголовок с
подписью Telegram. Вместо этого в URL лежит HMAC от id: подделать ссылку на
чужое фото нельзя, а токен бота наружу не попадает.

Порядок маршрутов важен: конкретные пути (`/media/tg/...`,
`/media/checklist/...`) объявлены ДО `/media/{blob_id}`, иначе FastAPI попытался
бы разобрать слово «tg» как число и вернул бы 422.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel

from app.api.deps import EmployeeDep, SessionDep
from app.db.hr_models import TaskPhoto
from app.services import hr_media

router = APIRouter(tags=["media"])


class MediaOut(BaseModel):
    id: int
    url: str
    mime: str
    width: int | None
    height: int | None
    size: int


def media_out(blob) -> MediaOut:  # noqa: ANN001 - ORM-объект без публичного типа
    return MediaOut(
        id=int(blob.id),
        url=hr_media.url_for(int(blob.id)),
        mime=blob.mime,
        width=blob.width,
        height=blob.height,
        size=blob.size,
    )


@router.post("/media", response_model=MediaOut)
async def upload_media(
    session: SessionDep,
    employee: EmployeeDep,
    file: Annotated[UploadFile, File(description="Снимок с камеры или из галереи")],
) -> MediaOut:
    """Принять снимок из приложения.

    `employee` здесь не для прав, а для единого входа: в режиме проверки
    загрузка идёт от теневого профиля, поэтому и отчёт привяжется к нему.
    """
    del employee
    try:
        blob = await hr_media.store_upload(session, file)
    except hr_media.MediaError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return media_out(blob)


@router.get("/media/tg/{photo_id}")
async def get_telegram_photo(photo_id: int, s: str | None = None) -> Response:
    """Фото из чата: лениво скачиваем из Telegram и кешируем в блоб.

    Так старые отчёты (когда приложение ещё не умело загружать снимки) тоже
    становятся видимыми, причём повторный показ уже не ходит в Telegram.
    """
    if not hr_media.verify("tgphoto", photo_id, s):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="bad_signature")
    from app.db.base import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as session:
        photo = await session.get(TaskPhoto, photo_id)
        if photo is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="photo_not_found")
        blob = await hr_media.ensure_task_photo_blob(session, photo)
        if blob is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="media_unavailable")
        data, mime = blob.data, blob.mime
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/media/checklist/{completion_id}")
async def get_checklist_photo(completion_id: int, s: str | None = None) -> Response:
    """Фото пункта чек-листа: загруженное в приложении или кеш из чата."""
    if not hr_media.verify("checklist_photo", completion_id, s):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="bad_signature")
    from app.db.base import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as session:
        blob = await hr_media.ensure_checklist_photo_blob(session, completion_id)
        if blob is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="media_unavailable")
        data, mime = blob.data, blob.mime
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/media/{blob_id}")
async def get_media(blob_id: int, s: str | None = None) -> Response:
    """Байты фото по подписанной ссылке (без авторизации — её не умеет `<img>`)."""
    from app.db.base import get_sessionmaker

    if not hr_media.verify("blob", blob_id, s):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="bad_signature")
    sm = get_sessionmaker()
    async with sm() as session:
        blob = await hr_media.blob_or_404(session, blob_id)
        return Response(
            content=blob.data,
            media_type=blob.mime,
            headers={"Cache-Control": "private, max-age=86400"},
        )
