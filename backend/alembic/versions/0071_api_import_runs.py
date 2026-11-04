"""Журнал входящих импортов по ключу API (B2B_PLATFORM_PLAN, шаг 6.2).

Зачем таблица, если есть `audit_events`. Аудит отвечает «кто и когда», но не
хранит ответ: интегратору при повторе нужно получить **тот же** ответ, а
владельцу — увидеть числа (создано/обновлено/ошибок), не разбирая JSON аудита.
Здесь лежит и ключ идемпотентности, и снимок ответа.

Почему `idempotency_key` nullable, а уникальность по тройке. Прогон без
заголовка `Idempotency-Key` — обычный вызов, таких может быть сколько угодно;
NULL в PostgreSQL и sqlite не участвует в уникальности, поэтому одна и та же
тройка ограничивает только явные ключи.

Почему `request_hash`. Тот же `Idempotency-Key` с другим файлом — это ошибка
интегратора, а не повтор: вернуть сохранённый ответ значило бы сказать
«данные применены», когда применены другие. Хеш отличается — 409.

Revision ID: 0071_api_import_runs
Revises: 0070_notify_prefs
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0071_api_import_runs"
down_revision: str | None = "0070_notify_prefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_import_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Ключ не удаляется, а отзывается, поэтому FK остаётся живым.
        sa.Column(
            "key_id",
            sa.BigInteger(),
            sa.ForeignKey("api_keys.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="applied"),
        sa.Column("created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
        # Снимок ответа целиком: повтор обязан получить то же тело.
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "org_id",
            "key_id",
            "idempotency_key",
            name="uq_api_import_run_idem",
        ),
    )
    op.create_index("ix_api_import_runs_org_id", "api_import_runs", ["org_id"])
    op.create_index(
        "ix_api_import_runs_org_time", "api_import_runs", ["org_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_api_import_runs_org_time", table_name="api_import_runs")
    op.drop_index("ix_api_import_runs_org_id", table_name="api_import_runs")
    op.drop_table("api_import_runs")
