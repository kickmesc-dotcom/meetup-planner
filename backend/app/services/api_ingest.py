"""Входящий обмен по ключу организации (B2B_PLATFORM_PLAN, шаг 6.2).

Критерий шага — «обмен идёт по контракту, ошибки видны в журнале». Контракты
iiko и Yclients ждут подписи вендора, а 1С и Excel не ждут ничего: они умеют
отдать CSV по расписанию. Поэтому первым появился входящий конвейер, а не
исходящий коннектор к чужому SaaS.

Три решения, без которых обмен по ключу был бы опаснее ручного импорта:

* **Право на запись отдельно от чтения.** `people.read` даёт интегратору
  расстановку смен; `people.write` — право создавать людей. Владелец выдаёт его
  осознанно, а не «заодно с ключом».
* **Идемпотентность обязательна.** 1С повторяет запрос при таймауте. Без
  `Idempotency-Key` повтор создал бы второго человека, а с `overwrite` стёр бы
  актуальный график. Повтор с тем же ключом получает сохранённый ответ и не
  трогает данные; тот же ключ с другим файлом — 409, потому что это уже не
  повтор.
* **Журнал прогонов.** Владелец видит числа и имя файла в кабинете, интегратор —
  в `/api/v1/import/runs`. Ошибки строк живут в ответе и не прячутся: «ошибок 2»
  без деталей бесполезно.

Право проверяется ДО записи: сначала план (он ничего не пишет), потом scope по
виду данных, только потом применение. Иначе отказ приходил бы после того, как
данные уже изменились.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.org_models import ApiImportRun, ApiKey
from app.services import api_keys, audit, people_import

# Заголовок приходит от интегратора; длиннее — уже не ключ, а мусор в базе.
MAX_KEY_LEN = 120
MAX_RUNS = 200


class ApiIngestError(Exception):
    """Отказ обмена: нет права на вид данных или ключ идемпотентности занят."""


def _require_scope(key: ApiKey, mode: str) -> None:
    scope = "people.write" if mode == "people" else "schedule.write"
    if not api_keys.has_scope(key, scope):
        raise ApiIngestError(f"scope_required:{scope}")


def _digest(text: str, kind: str | None, overwrite: bool) -> str:
    """Отпечаток запроса: файл + вид + режим перезаписи."""
    payload = f"{kind or ''}|{int(bool(overwrite))}|{text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _plan_mode(
    session: AsyncSession, *, text: str, kind: str | None, overwrite: bool
) -> str:
    mode, _delimiter, _rows, _extra = await people_import.plan(
        session, text=text, kind=kind, overwrite=overwrite
    )
    return mode


async def _find_run(
    session: AsyncSession, key: ApiKey, idem: str
) -> ApiImportRun | None:
    return await session.scalar(
        select(ApiImportRun).where(
            ApiImportRun.org_id == key.org_id,
            ApiImportRun.key_id == key.id,
            ApiImportRun.idempotency_key == idem,
        )
    )


async def preview(
    session: AsyncSession,
    *,
    key: ApiKey,
    text: str,
    kind: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Показать разбор, ничего не записывая (и не требуя идемпотентности)."""
    mode = await _plan_mode(session, text=text, kind=kind, overwrite=overwrite)
    _require_scope(key, mode)
    result = await people_import.preview(session, text=text, kind=mode, overwrite=overwrite)
    return result.as_dict()


async def apply(
    session: AsyncSession,
    *,
    key: ApiKey,
    text: str,
    kind: str | None = None,
    overwrite: bool = False,
    filename: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Применить разбор. Возвращает (ответ, был ли это повтор)."""
    idem = (idempotency_key or "").strip()[:MAX_KEY_LEN] or None
    digest = _digest(text, kind, overwrite)

    if idem is not None:
        existing = await _find_run(session, key, idem)
        if existing is not None:
            if existing.request_hash != digest:
                raise ApiIngestError("idempotency_key_reused")
            return json.loads(existing.response), True

    mode = await _plan_mode(session, text=text, kind=kind, overwrite=overwrite)
    _require_scope(key, mode)

    data = await people_import.apply(
        session, text=text, kind=mode, overwrite=overwrite
    )

    run = ApiImportRun(
        org_id=key.org_id,
        key_id=key.id,
        idempotency_key=idem,
        request_hash=digest,
        kind=data["kind"],
        filename=(filename or "")[:200] or None,
        status="applied",
        created=int(data["created"]),
        updated=int(data["updated"]),
        skipped=int(data["skipped"]),
        errors=int(data["errors"]),
        response=json.dumps(data, ensure_ascii=False),
    )
    session.add(run)
    await audit.record(
        session,
        org_id=key.org_id,
        action="import.api",
        target_type=data["kind"],
        details={
            "api_key_id": key.id,
            "key_name": key.name,
            "created": data["created"],
            "updated": data["updated"],
            "skipped": data["skipped"],
            "errors": data["errors"],
            "filename": filename,
            "idempotency": idem,
        },
    )
    await session.commit()
    return data, False


async def runs(
    session: AsyncSession, org_id: int, *, limit: int = 50
) -> list[ApiImportRun]:
    """Последние прогоны организации, новые сверху."""
    capped = max(1, min(int(limit), MAX_RUNS))
    rows = await session.scalars(
        select(ApiImportRun)
        .where(ApiImportRun.org_id == org_id)
        .order_by(ApiImportRun.created_at.desc(), ApiImportRun.id.desc())
        .limit(capped)
    )
    return list(rows)


__all__ = [
    "MAX_KEY_LEN",
    "MAX_RUNS",
    "ApiIngestError",
    "apply",
    "preview",
    "runs",
]
