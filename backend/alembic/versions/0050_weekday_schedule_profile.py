"""Расписание по дням недели, видимость профиля и переименование владельца.

Три вещи одним заходом (раунд 5).

1. `checklist_items.weekdays` / `tasks.weekdays` — дни недели, в которые пункт
   или поручение действует. Пусто (NULL) — каждый день, как раньше. Храним CSV
   из номеров ISO (1 = понедельник … 7 = воскресенье): это переносимо между
   Postgres и SQLite (в тестах схема поднимается на обоих) и читается глазами в
   psql. Пункт «по четвергам» виден в списке всегда, но в остальные дни стоит
   серым и не участвует в прогрессе — иначе «Выполнено 3 из 10» врало бы.

2. `employees.profile_public` — «профиль открыт». По умолчанию открыт: коллеги
   видят активность человека в ленте и могут открыть его карточку. Закрытый
   профиль прячет прогресс и историю от соседей, но не от руководителя и
   администратора — им он нужен для работы.

3. Владелец проекта больше не «Серж-NEO»: правим имя в базе, чтобы
   переименование не зависело от того, сработает ли сид (он не перезаписывает
   существующие строки).

Revision ID: 0050_weekday_schedule_profile
Revises: 0049_roster_snapshots
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0050_weekday_schedule_profile"
down_revision: str | None = "0049_roster_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "checklist_items",
        sa.Column("weekdays", sa.String(32), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("weekdays", sa.String(32), nullable=True),
    )
    op.add_column(
        "employees",
        sa.Column(
            "profile_public",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )
    # Переименование владельца: старое имя осталось и в подписях, и в профиле.
    op.execute(
        sa.text(
            "UPDATE users SET display_name = 'Сергей' "
            "WHERE display_name = 'Серж-NEO'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users SET display_name = 'Серж-NEO' "
            "WHERE display_name = 'Сергей'"
        )
    )
    op.drop_column("employees", "profile_public")
    op.drop_column("tasks", "weekdays")
    op.drop_column("checklist_items", "weekdays")
