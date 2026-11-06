"""Филиалы сети: организация может быть филиалом головной.

Зачем. Сеть салонов — это не одна организация с «отделом на районе»: у
филиала свой коллектив, свой график и свои отчёты. Но владелец у сети один, и
заводить ему вторую учётку, чтобы зайти в соседний филиал, — неправильно.

Почему `parent_org_id`, а не таблица `networks`. Сеть — дерево глубины один:
головная организация и её филиалы. Отдельная сущность добавила бы третий
идентификатор, который пришлось бы тащить во все ручки, не давая ничего:
филиал остаётся самостоятельной организацией со своими людьми и тарифом.

Почему `SET NULL`, а не `CASCADE`. Удаление головной не должно уносить данные
филиалов: они остаются рабочими организациями, просто без сети. Каскад здесь
был бы удалением чужих смен и чек-листов без запроса.

Revision ID: 0074_org_branches
Revises: 0073_org_domain
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0074_org_branches"
down_revision: str | None = "0073_org_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("parent_org_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_organizations_parent_org",
        "organizations",
        "organizations",
        ["parent_org_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_organizations_parent_org", "organizations", ["parent_org_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_organizations_parent_org", table_name="organizations")
    op.drop_constraint(
        "fk_organizations_parent_org", "organizations", type_="foreignkey"
    )
    op.drop_column("organizations", "parent_org_id")
