"""Подтверждение адреса почты (B2B_PLATFORM_PLAN, шаг 2.1).

Зачем отдельная таблица. Ссылку можно запросить заново (письмо не дошло,
человек открыл его на другом устройстве), она живёт двое суток и обязана
сработать ровно один раз. Флаг в `users` не позволил бы ни повторную выдачу,
ни одноразовость — пришлось бы держать токен в открытом виде.

Глобальная таблица (без `org_id`): подтверждение относится к личности, а
организация на момент перехода по ссылке ещё может быть неизвестна. В базе —
только SHA-256 от токена.

Revision ID: 0059_email_verification
Revises: 0058_push
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0059_email_verification"
down_revision: str | None = "0058_push"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_verifications",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_email_verification_token"),
    )
    op.create_index(
        "ix_email_verifications_user", "email_verifications", ["user_id"]
    )
    op.create_index(
        "ix_email_verifications_expires", "email_verifications", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_email_verifications_expires", table_name="email_verifications")
    op.drop_index("ix_email_verifications_user", table_name="email_verifications")
    op.drop_table("email_verifications")
