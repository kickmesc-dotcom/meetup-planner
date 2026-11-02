"""Тарифы организаций: лимиты и триал (B2B_PLATFORM_PLAN, шаг 4.1).

Зачем колонки, а не отдельная таблица подписок. Подписка с платежами придёт на
шаге 4.2, и её история будет нужна отдельно. Здесь только два факта, которые
читаются на каждом запросе: по какому тарифу живёт организация и до какого
срока у неё триал. Выносить их в связанную таблицу значило бы платить join'ом
за каждое «можно ли завести человека».

Почему server_default='business'. До этого шага организаций с тарифом не было
вовсе, и ограничивать действующего клиента по дате в календаре — поломка, а не
нововведение. Существующие строки получают «Бизнес» без срока; новые
организации ставят `trial` явно в `orgs.create_org`.

Revision ID: 0065_org_plans
Revises: 0064_menu_items
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0065_org_plans"
down_revision: str | None = "0064_menu_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "plan",
            sa.String(length=16),
            nullable=False,
            server_default="business",
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "trial_ends_at")
    op.drop_column("organizations", "plan")
