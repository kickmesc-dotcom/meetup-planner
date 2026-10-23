"""Приглашения в организацию: ссылка, роль и срок (шаг 2.2).

Почему отдельная таблица, а не «ожидающий сотрудник». Приглашённый может ещё
не иметь аккаунта, поэтому заранее заводить `users` значит плодить дубли:
человек зарегистрируется другой почтой или войдёт из Telegram. Приглашение —
это право присоединиться, а учётка появляется по факту принятия.

Что в таблице:

* `org_id` — организация, в которую приглашают (не «первая по id» — именно
  та, из которой выписали ссылку);
* `role` — уровень доступа внутри организации (`owner`/`manager`/`staff`);
* `email` — необязательный адрес: пусто значит «ссылка для всех, у кого она
  есть», заполнено — принять сможет только владелец почты;
* `token_hash` (SHA-256) — сам токен не хранится: ссылка живёт неделю и
  пересылается в мессенджере;
* `expires_at`, `accepted_at`/`accepted_by_user_id`, `revoked_at` — срок,
  одноразовость и отзыв.

Индекс по `(org_id, created_at)` — для списка в админке; уникальный
`token_hash` — потому что поиск по токену идёт до того, как организация
известна.

Revision ID: 0057_invitations
Revises: 0056_accounts
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0057_invitations"
down_revision: str | None = "0056_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "org_invitations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column(
            "role", sa.String(length=16), nullable=False, server_default="staff"
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
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
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "accepted_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_org_invitation_token"),
    )
    op.create_index("ix_org_invitations_org_id", "org_invitations", ["org_id"])
    op.create_index(
        "ix_org_invitations_org", "org_invitations", ["org_id", "created_at"]
    )
    # Срок и состояние ищутся списком «что ещё живо» — отдельный индекс по
    # `expires_at` не нужен: выборка всегда внутри организации.


def downgrade() -> None:
    op.drop_index("ix_org_invitations_org", table_name="org_invitations")
    op.drop_index("ix_org_invitations_org_id", table_name="org_invitations")
    op.drop_table("org_invitations")
