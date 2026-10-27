"""«Спасибо коллеге»: благодарности с недельным топом.

Зачем таблица, а не поле. Благодарность не привязана к поручению: говорят
спасибо за подмену, за спокойную смену, за помощь с гостем. Плюс из этих же
строк считается недельный топ — если бы счётчик лежал отдельно, он рано или
поздно разошёлся бы с лентой.

Почему ограничения в схеме, а не только в коде:

* `unique(from_employee_id, to_employee_id, day)` — «одно спасибо одному
  человеку в день». Без него топ набивается повторными нажатиями, а два
  одновременных запроса обходят любую проверку «сначала прочитаем, потом
  запишем»;
* `check(from_employee_id <> to_employee_id)` — благодарить себя нельзя, и это
  не должно зависеть от того, поправили ли сервис;
* `day` — дата по часам заведения, а не UTC: смена кончается после полуночи, и
  «спасибо за смену» не должно уезжать во вчерашний день.

Таблица тенантная (`org_id` NOT NULL), как все бизнес-таблицы проекта.

Revision ID: 0062_kudos
Revises: 0061_invite_position
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0062_kudos"
down_revision: str | None = "0061_invite_position"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_kudos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_employee_id",
            sa.BigInteger(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("message", sa.String(length=160), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "from_employee_id",
            "to_employee_id",
            "day",
            name="uq_kudos_pair_day",
        ),
        sa.CheckConstraint(
            "from_employee_id <> to_employee_id", name="ck_kudos_not_self"
        ),
    )
    op.create_index("ix_hr_kudos_to_day", "hr_kudos", ["to_employee_id", "day"])
    op.create_index(
        "ix_hr_kudos_from_day", "hr_kudos", ["from_employee_id", "day"]
    )


def downgrade() -> None:
    op.drop_index("ix_hr_kudos_from_day", table_name="hr_kudos")
    op.drop_index("ix_hr_kudos_to_day", table_name="hr_kudos")
    op.drop_table("hr_kudos")
