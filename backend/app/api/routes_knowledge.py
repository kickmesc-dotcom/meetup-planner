"""Один поисковый вход по знаниям: стандарты и пункты чек-листов.

Ручка отвечает на вопрос сотрудника («как закрыть смену»), а не заменяет
разделы: каждый результат несёт `kind` и `id`, по которым фронт открывает
нужный экран с уже выбранным элементом. Почему отдельная ручка, а не поиск
внутри `/api/standards`: сотруднику нужно найти пункт чек-листа, о
существовании которого он не знает, — то есть источник должен быть шире
одного раздела.

Доступ — любой сотрудник (это чтение инструкций, которые ему и так видны), но
выдача ограничена его подразделением и только активными материалами —
см. `services/knowledge.search`.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import EmployeeDep, SessionDep
from app.services import knowledge

router = APIRouter(tags=["knowledge"])


class HitOut(BaseModel):
    kind: Literal["standard", "checklist"]
    id: int
    title: str
    snippet: str
    subtitle: str


class SearchOut(BaseModel):
    query: str
    # Слова, по которым реально искали: видно, если запрос был «что делать» и
    # стоп-слова отфильтровались. Это же подсказывает, почему выдача такая.
    words: list[str]
    hits: list[HitOut]
    # Пустой ответ при непустом запросе — не ошибка: в базе может не быть
    # подходящей инструкции. Фронт по этому флагу показывает «спросите
    # руководителя», а не пустой экран.
    empty: bool


@router.get("/knowledge/search", response_model=SearchOut)
async def search_knowledge(
    session: SessionDep,
    employee: EmployeeDep,
    q: str = Query("", max_length=knowledge.MAX_QUERY_LEN),
    limit: int = Query(12, ge=1, le=30),
) -> SearchOut:
    query = knowledge.normalise_query(q)
    words = knowledge.query_words(query)
    hits = await knowledge.search(session, query=query, employee=employee, limit=limit)
    return SearchOut(
        query=query,
        words=words,
        hits=[
            HitOut(
                kind=hit.kind,  # type: ignore[arg-type]  # значения задаёт сервис
                id=hit.id,
                title=hit.title,
                snippet=hit.snippet,
                subtitle=hit.subtitle,
            )
            for hit in hits
        ],
        empty=not hits,
    )
