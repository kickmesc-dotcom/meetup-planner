"""Счета организации и срок оплаченной подписки (B2B_PLATFORM_PLAN, 4.2).

Зачем счёт, а не сразу платёж. Платёжного провайдера подключает владелец: до
этого кнопка «Оплатить» обещала бы действие, которого нет. Счёт существует
независимо от провайдера — номер, тариф, период, сумма, срок — и когда
провайдер появится, он будет закрывать те же счета, а история не переедет.

Почему `plan_ends_at` в организациях, а не в счёте. Срок — это факт «до какого
числа клиент оплачен», он читается на каждом «можно ли завести человека».
В счёте лежит история: сколько и когда заплатили. Пусто у триала и у
существующих организаций («Бизнес» без срока) — и это не «истекло вчера».

Почему `expired` не хранится. Просроченный счёт — это `pending` с прошедшим
`expires_at`; отдельный статус потребовал бы фоновой задачи, которая переводит
строки, и расхождения между задачей и реальностью.

Revision ID: 0066_org_billing
Revises: 0065_org_plans
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0066_org_billing"
down_revision: str | None = "0065_org_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("plan_ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "org_invoices",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("plan", sa.String(length=16), nullable=False),
        sa.Column("period", sa.String(length=8), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="RUB"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.UniqueConstraint("number", name="uq_org_invoice_number"),
    )
    op.create_index("ix_org_invoices_org", "org_invoices", ["org_id", "created_at"])
    # Идемпотентность кнопки «выставить счёт»: поиск открытого счёта на тот же
    # тариф и период идёт по этому индексу.
    op.create_index(
        "ix_org_invoices_open", "org_invoices", ["org_id", "plan", "period", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_org_invoices_open", table_name="org_invoices")
    op.drop_index("ix_org_invoices_org", table_name="org_invoices")
    op.drop_table("org_invoices")
    op.drop_column("organizations", "plan_ends_at")
