"""Приватность: удаление по запросу и журнал доступа (B2B_PLATFORM_PLAN, 5.5).

Зачем у организации две новые даты. «Удалить нас» — обещание, у которого должен
быть срок исполнения. `deleted_at` фиксирует момент запроса, `purge_after` —
когда данные исчезнут физически. Между ними клиент может передумать: удаление
необратимо, и кнопка, которая срабатывает мгновенно, — это ловушка, а не сервис.

Почему не `is_active = false`. Блокировка за неоплату и запрос удаления — разные
вещи: заблокированный клиент ждёт оплаты, удаляющийся — уходит. Владелец должен
видеть состояние и иметь возможность отменить, поэтому доступ закрываем по
`deleted_at`, а не по флагу блокировки.

Почему журнал отдельной таблицей, а не полем. Журнал — это список событий,
он растёт и обрезается по сроку. Колонка в организации хранила бы одно
последнее действие и не отвечала бы на вопрос «кто выгружал данные в марте».

Revision ID: 0068_org_privacy
Revises: 0067_org_brand
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0068_org_privacy"
down_revision: str | None = "0067_org_brand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Человека можно удалить, а событие остаётся: `SET NULL` обнуляет
        # ссылку, а имя хранится снимком в `actor_name`.
        sa.Column(
            "actor_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_name", sa.String(length=120), nullable=True),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        # JSON текстом: журнал не фильтруют по деталям, а sqlite в тестах
        # JSONB не знает.
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_events_org_id", "audit_events", ["org_id"])
    op.create_index(
        "ix_audit_events_org_time", "audit_events", ["org_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_org_time", table_name="audit_events")
    op.drop_index("ix_audit_events_org_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_column("organizations", "purge_after")
    op.drop_column("organizations", "deleted_at")
