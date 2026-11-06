"""Индексы под ленту: сортировка по времени без чтения всей таблицы.

Зачем. Лента собирает шесть источников, и каждый запрос — это
`ORDER BY <время> DESC LIMIT 50`. Индексов на эти колонки не было ни у одного
источника (у `task_events` и `task_photos` есть только `(task_id, …)`, что для
ленты бесполезно): Postgres читал таблицу целиком, сортировал и отдавал верхние
строки. Чем дольше работает заведение, тем дороже открытие ленты, хотя человеку
нужны те же 50 последних записей.

Почему `org_id` первым столбцом. Тенантский фильтр (`app/db/tenancy.py`) сам
добавляет `WHERE org_id = …` в каждую ORM-выборку. Индекс `(org_id, время)`
позволяет пройти только по строкам организации и взять их в нужном порядке —
без сортировки. `DESC` в определении не нужен: btree читается в обе стороны,
и это не привязывает индекс к одному направлению сортировки.

Почему не partial-индекс. Частичный `WHERE completed_at IS NOT NULL` был бы
ещё компактнее, но привязывает индекс к текущей формулировке запроса; обычный
`(org_id, время)` работает и для будущих фильтров по дате.

Revision ID: 0072_feed_indexes
Revises: 0071_api_import_runs
"""

from __future__ import annotations

from alembic import op

revision: str = "0072_feed_indexes"
down_revision: str | None = "0071_api_import_runs"
branch_labels = None
depends_on = None

#: (имя индекса, таблица, колонка времени) — ровно те сортировки, что в
#: `services/hr_feed.collect_items`.
INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_checklist_runs_org_completed", "checklist_runs", "completed_at"),
    ("ix_checklist_completions_org_done", "checklist_completions", "done_at"),
    ("ix_task_events_org_at", "task_events", "at"),
    ("ix_task_photos_org_created", "task_photos", "created_at"),
    ("ix_task_issues_org_created", "task_issues", "created_at"),
    ("ix_hr_kudos_org_created", "hr_kudos", "created_at"),
)


def upgrade() -> None:
    for name, table, column in INDEXES:
        op.create_index(name, table, ["org_id", column])


def downgrade() -> None:
    for name, table, _column in reversed(INDEXES):
        op.drop_index(name, table_name=table)
