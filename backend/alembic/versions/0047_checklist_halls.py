"""Чек-листы по залам и общий чек-лист закрытия смены.

Официант сначала выбирает зал, и только потом видит свой чек-лист открытия:
шаблоны одного подразделения теперь различаются `hall_id` (NULL — общий).
Выбор зала хранится на смену (`shift_hall_choices`), чтобы после перезагрузки
приложение не спрашивало заново и не путало залы.

Новый вид шаблона `close` — закрытие смены: один на все залы. Последний пункт
(«показать рабочее место») закрывается фотоотчётом.

Revision ID: 0047_checklist_halls
Revises: 0046_materials
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0047_checklist_halls"
down_revision: str | None = "0046_materials"
branch_labels = None
depends_on = None

# (slug, name, sort_order) — залы, которые есть в DOCX владельца.
HALLS = (
    ("first", "Первый зал", 10),
    ("second", "Второй зал", 20),
)


def upgrade() -> None:
    op.create_table(
        "halls",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("slug", name="uq_hall_slug"),
    )
    op.create_index("ix_halls_active_sort", "halls", ["is_active", "sort_order"])

    halls = sa.table(
        "halls",
        sa.column("name", sa.Text()),
        sa.column("slug", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        halls,
        [
            {
                "name": name,
                "slug": slug,
                "is_active": True,
                "sort_order": order,
                "created_at": datetime(2026, 10, 20),
            }
            for slug, name, order in HALLS
        ],
    )

    op.add_column(
        "checklist_templates",
        sa.Column("hall_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_checklist_templates_hall",
        "checklist_templates",
        "halls",
        ["hall_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_checklist_templates_hall",
        "checklist_templates",
        ["hall_id", "kind", "is_active"],
    )

    # Новый вид шаблона: закрытие смены (общий для всех залов).
    op.drop_constraint(
        "ck_checklist_template_kind", "checklist_templates", type_="check"
    )
    op.create_check_constraint(
        "ck_checklist_template_kind",
        "checklist_templates",
        "kind IN ('first_day', 'shift', 'close')",
    )

    op.create_table(
        "shift_hall_choices",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("shift_date", sa.Date(), nullable=False),
        sa.Column(
            "hall_id",
            sa.BigInteger(),
            sa.ForeignKey("halls.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "employee_id", "shift_date", name="uq_shift_hall_choice"
        ),
    )


def downgrade() -> None:
    op.drop_table("shift_hall_choices")

    op.drop_constraint(
        "ck_checklist_template_kind", "checklist_templates", type_="check"
    )
    op.create_check_constraint(
        "ck_checklist_template_kind",
        "checklist_templates",
        "kind IN ('first_day', 'shift')",
    )

    op.drop_index("ix_checklist_templates_hall", table_name="checklist_templates")
    op.drop_constraint(
        "fk_checklist_templates_hall", "checklist_templates", type_="foreignkey"
    )
    op.drop_column("checklist_templates", "hall_id")

    op.drop_index("ix_halls_active_sort", table_name="halls")
    op.drop_table("halls")
