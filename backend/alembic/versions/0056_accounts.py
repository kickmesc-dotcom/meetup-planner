"""Вход по почте и паролю: аккаунт, сессии, сброс (шаг 2.1).

До этой миграции единственным входом был Telegram: `users.telegram_id` был
NOT NULL, пароля не существовало вовсе. Для B2B это стоп-фактор — часть
клиентов не хочет ставить Telegram сотрудникам.

Что делает:

1. `users.telegram_id` становится nullable: Telegram — один из провайдеров
   входа, а не обязательное поле личности;
2. появляются `users.email` (уникальный, хранится в нижнем регистре) и
   `users.password_hash` (PBKDF2, соль на пользователя). Плюс
   `email_verified_at` — задел под подтверждение адреса;
3. `auth_sessions` — входы по устройствам. В базе только SHA-256 от токена,
   срок, отзыв и организация, в которой выдан вход;
4. `password_resets` — одноразовые ссылки сброса со сроком час.

Почему отдельные таблицы, а не поля в `users`: сессий несколько, каждую нужно
отзывать отдельно, а ссылка сброса обязана быть одноразовой. Токены нигде не
хранятся в открытом виде — только хеш, поэтому дамп базы не даёт войти.

Revision ID: 0056_accounts
Revises: 0055_org_bot
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0056_accounts"
down_revision: str | None = "0055_org_bot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users", "telegram_id", existing_type=sa.BigInteger(), nullable=True
    )
    op.add_column("users", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Уникальность почты: два аккаунта на один адрес — это два пароля и вечный
    # вопрос «какой из них мой». NULL (аккаунты только с Telegram) не мешает.
    op.create_index("uq_users_email", "users", ["email"], unique=True)

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auth_sessions_user", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires", "auth_sessions", ["expires_at"])

    op.create_table(
        "password_resets",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_password_resets_user", "password_resets", ["user_id"])
    op.create_index("ix_password_resets_expires", "password_resets", ["expires_at"])

    # Членство — задним числом. До этой миграции организация сотрудника была
    # только в `employees.org_id`, а `organization_members` заполнялась лишь
    # вручную. Почтовый вход проверяет членство (без него человек не должен
    # попасть в данные клиента), поэтому старые аккаунты нужно перенести —
    # иначе после выкладки они получили бы 403.
    # Роль в членстве — уровень доступа к организации, а не HR-роль:
    # admin → owner, aup → manager, остальные → staff.
    op.execute(
        """
        INSERT INTO organization_members (org_id, user_id, role)
        SELECT e.org_id,
               e.user_id,
               CASE e.role
                   WHEN 'admin' THEN 'owner'
                   WHEN 'aup' THEN 'manager'
                   ELSE 'staff'
               END
        FROM employees e
        WHERE e.org_id IS NOT NULL
        ON CONFLICT (org_id, user_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_password_resets_expires", table_name="password_resets")
    op.drop_index("ix_password_resets_user", table_name="password_resets")
    op.drop_table("password_resets")

    op.drop_index("ix_auth_sessions_expires", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_index("uq_users_email", table_name="users")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")
    # Откат вернёт NOT NULL: если к этому моменту есть аккаунты без Telegram,
    # миграция упадёт. Это честнее, чем молча удалить их или придумать им
    # telegram_id — откат фазы 2 на базе с почтовыми входами требует решения.
    op.alter_column(
        "users", "telegram_id", existing_type=sa.BigInteger(), nullable=False
    )
