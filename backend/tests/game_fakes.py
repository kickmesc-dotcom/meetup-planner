"""Общие помощники для фейковых сессий игровых тестов.

Зачем отдельный модуль. Игровой код ищет маркер окна идемпотентности в
`xp_grants` обычным `select` по уникальному индексу `(user_id, idem_key)`. Если
фейк умеет отвечать на этот запрос только из очереди заранее подготовленных
значений, то ЛЮБОЕ изменение формы запроса (или его отсутствие) тесты не ловит:
они продолжают проходить, отвечая «не найдено» из очереди.

Так и случилось: код звал `session.get(XpGrant, (user_id, key))`, хотя у
`XpGrant` суррогатный PK `id`. Настоящая база падала с «Incorrect number of
values in identifier to formulate primary key for session.get()», а фейк —
нет. Ошибку поймали только в бою (500 на сохранении календаря и полная потеря
начисления опыта за разметку).

Поэтому фейк должен уметь отвечать на этот запрос по своему store — ровно так,
как это сделала бы база по уникальному индексу.
"""
from __future__ import annotations

from typing import Any


class FakeResult:
    """Мини-результат `execute`: коду нужны только `rowcount` и `first()`."""

    def __init__(self, row: Any = None, *, rowcount: int = 0) -> None:
        self._row = row
        self.rowcount = rowcount

    def first(self) -> Any:
        return self._row


def column_count(stmt: Any) -> int:
    """Сколько колонок в SELECT (0 — если это не SELECT)."""
    return len(getattr(stmt, "column_descriptions", None) or [])


def scalar_answer(stmt: Any, row: Any) -> Any:
    """Что вернул бы настоящий `session.scalar(stmt)` для такой очереди ответов.

    Главное правило, ради которого это здесь: **`scalar` отдаёт первую КОЛОНКУ
    первой строки, а не строку-кортеж**. На двухколоночном select
    (`select(User.id, User.display_name)`) настоящая сессия возвращает `int`, и
    код, читающий `row[0]`, падает в бою с «'int' object is not subscriptable».

    Так уже случилось в `events.try_answer`: ни один ответ на случайное событие
    не засчитался, а тест проходил, потому что фейк отдавал кортеж — добрее
    реальности. Фейк обязан быть таким же строгим, как база.
    """
    if row is None:
        return None
    if column_count(stmt) > 1 and isinstance(row, tuple | list):
        return row[0]
    return row


def grant_lookup(stmt: Any, store: dict[tuple, object]) -> tuple[bool, Any]:
    """Ответ на «есть ли маркер окна?» — по store, а не из очереди.

    Возвращает `(перехвачено, значение)`. Первый элемент говорит фейку, отвечать
    ли самому: `False` — запрос не про `xp_grants`, пусть работает прежняя логика
    с очередью. Второй — что вернуть: `1` если маркер есть, иначе `None`
    (значение истинно/ложно важно, а конкретный id — нет: вызывающий код только
    проверяет «нашёл или нет»).
    """
    descriptions = getattr(stmt, "column_descriptions", None) or []
    if not descriptions:
        return False, None
    entity = descriptions[0].get("entity")
    if getattr(entity, "__name__", None) != "XpGrant":
        return False, None
    try:
        params = stmt.compile().params
    except Exception:  # noqa: BLE001 — стенд не должен падать на экзотике
        return False, None
    user_id = next((v for k, v in params.items() if k.startswith("user_id")), None)
    key = next((v for k, v in params.items() if k.startswith("idem_key")), None)
    return True, (1 if store.get(("XpGrant", (user_id, key))) is not None else None)


def assert_single_column_pk_get(model: Any, key: Any) -> None:
    """Проверка, что `session.get` зовут с настоящим PK модели.

    Настоящая сессия сама собирает PK по метаданным и падает, если значений не
    столько, сколько колонок. Фейк обязан вести себя так же — иначе он прощает
    код, который в бою даёт 500.
    """
    from sqlalchemy import inspect as sa_inspect

    pk = [column.key for column in sa_inspect(model).mapper.primary_key]
    if len(pk) == 1 and isinstance(key, tuple):
        raise AssertionError(
            f"session.get({model.__name__}, tuple) — но PK модели это {pk}. "
            "Настоящая сессия упала бы с «Incorrect number of values in "
            "identifier to formulate primary key»."
        )
    if len(pk) > 1 and (not isinstance(key, tuple) or len(key) != len(pk)):
        raise AssertionError(
            f"session.get({model.__name__}, {key!r}) — ожидался кортеж из {len(pk)} "
            f"значений, как в PK {pk}."
        )
