"""Тенант-ядро: организации, членство и `org_id` у людей и подразделений.

Первый шаг B2B_PLATFORM_PLAN (фаза 1). До этой миграции в схеме не было
понятия «организация»: один бот, один чат, один набор подразделений.

Что делает:

1. заводит `organizations` и `organization_members` (личность глобальная,
   членство — в организации, чтобы человек мог работать в двух филиалах);
2. создаёт организацию `default` с id=1 и переставляет последовательность —
   иначе первая же новая организация получила бы занятый id;
3. добавляет `org_id` к `employees` и `departments` с `server_default='1'`:
   существующие строки автоматически становятся данными первой организации,
   простой при деплое не нужен (PG 11+ добавляет колонку с дефолтом мгновенно);
4. меняет уникальность подразделения: `slug` теперь уникален внутри
   организации (`org_id`, `slug`), а не глобально.

Чего НЕ делает: не скоупит запросы. Это следующий шаг — пока в коде один
контур, поведение не меняется, но модель данных уже готова. Страж схемы
(`tests/test_tenant_schema.py`) не даст добавить новую таблицу без `org_id`.

Revision ID: 0053_tenancy
Revises: 0052_owner_name_fix
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0053_tenancy"
down_revision: str | None = "0052_owner_name_fix"
branch_labels = None
depends_on = None

DEFAULT_ORG_ID = 1


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "industry",
            sa.String(length=32),
            nullable=False,
            server_default="restaurant",
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("slug", name="uq_organization_slug"),
    )
    op.create_index("ix_organizations_active", "organizations", ["is_active"])

    # Первая организация для уже существующих данных. `ON CONFLICT` — чтобы
    # повторный прогон на базе, где строка уже есть, не падал.
    op.execute(
        sa.text(
            "INSERT INTO organizations (id, slug, name, industry, is_active) "
            "VALUES (:id, 'default', 'Моя организация', 'restaurant', true) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(id=DEFAULT_ORG_ID)
    )
    # Явный id не двигает последовательность: без setval следующая организация
    # получила бы id=1 и упала на уникальности.
    op.execute(
        "SELECT setval("
        "pg_get_serial_sequence('organizations', 'id'), "
        "GREATEST((SELECT COALESCE(MAX(id), 1) FROM organizations), 1)"
        ")"
    )

    op.create_table(
        "organization_members",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role", sa.String(length=16), nullable=False, server_default="staff"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("org_id", "user_id", name="uq_org_member"),
    )
    op.create_index("ix_org_members_user", "organization_members", ["user_id"])

    for table in ("departments", "employees"):
        op.add_column(
            table,
            sa.Column(
                "org_id",
                sa.BigInteger(),
                nullable=False,
                server_default=str(DEFAULT_ORG_ID),
            ),
        )
        op.create_foreign_key(
            f"fk_{table}_org",
            table,
            "organizations",
            ["org_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_{table}_org_id", table, ["org_id"])

    # `slug` подразделения был уникален глобально — теперь внутри организации.
    op.drop_constraint("uq_department_slug", "departments", type_="unique")
    op.create_unique_constraint(
        "uq_department_org_slug", "departments", ["org_id", "slug"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_department_org_slug", "departments", type_="unique")
    op.create_unique_constraint("uq_department_slug", "departments", ["slug"])

    for table in ("employees", "departments"):
        op.drop_index(f"ix_{table}_org_id", table_name=table)
        op.drop_constraint(f"fk_{table}_org", table, type_="foreignkey")
        op.drop_column(table, "org_id")

    op.drop_index("ix_org_members_user", table_name="organization_members")
    op.drop_table("organization_members")
    op.drop_index("ix_organizations_active", table_name="organizations")
    op.drop_table("organizations")
