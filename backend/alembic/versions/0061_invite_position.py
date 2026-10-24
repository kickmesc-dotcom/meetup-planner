"""Должность и отдел прямо в приглашении.

Роль в приглашении уже была, но первый день всё равно начинался с анкеты:
человеку приходилось самому выбирать отдел и должность, которые руководитель
и так знал. Теперь ссылка несёт оба поля, а применяются они при создании
HR-профиля — раньше профиля может просто не быть (человек ещё не открывал
приложение).

Оба поля необязательные: ссылка «в чат смены» по-прежнему может ничего не
предрешать.

Revision ID: 0061_invite_position
Revises: 0060_hr_presence_privacy
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0061_invite_position"
down_revision: str | None = "0060_hr_presence_privacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "org_invitations",
        sa.Column("position", sa.Text(), nullable=True),
    )
    op.add_column(
        "org_invitations",
        sa.Column("department_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_org_invitations_department",
        "org_invitations",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_org_invitations_department", "org_invitations", type_="foreignkey"
    )
    op.drop_column("org_invitations", "department_id")
    op.drop_column("org_invitations", "position")
