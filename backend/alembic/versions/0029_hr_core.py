"""SemiTaskBot Этап 1 — HR-ядро: подразделения, сотрудники, чек-листы,
поручения, фотоотчёты, полезные ссылки и обратная связь по смене.

Первая миграция нового продукта поверх переиспользованного движка
meetup-planner. Наследные таблицы (`users`, `meetings`, …) не трогаем —
`employees` ссылается на `users.id` с ON DELETE CASCADE, остальное новое.

Revision ID: 0029_hr_core
Revises: 0028_media_feed_profile
Create Date: 2026-10-16
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0029_hr_core"
down_revision: str | Sequence[str] | None = "0028_media_feed_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("slug", name="uq_department_slug"),
    )
    op.create_index(
        "ix_departments_active_sort", "departments", ["is_active", "sort_order"]
    )

    op.create_table(
        "employees",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("department_id", sa.BigInteger(), nullable=True),
        sa.Column("position", sa.Text(), nullable=True),
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'employee'"),
        ),
        sa.Column("experience", sa.String(length=16), nullable=True),
        sa.Column(
            "onboarding_state",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'new'"),
        ),
        sa.Column("hire_date", sa.Date(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_employees_user", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name="fk_employees_department",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("user_id", name="uq_employees_user"),
        sa.CheckConstraint(
            "role IN ('employee', 'aup', 'admin')", name="ck_employee_role"
        ),
        sa.CheckConstraint(
            "onboarding_state IN ('new', 'department', 'experience', 'done')",
            name="ck_employee_onboarding_state",
        ),
        sa.CheckConstraint(
            "experience IS NULL OR experience IN ('new', 'experienced')",
            name="ck_employee_experience",
        ),
    )
    op.create_index(
        "ix_employees_department", "employees", ["department_id", "is_active"]
    )

    op.create_table(
        "checklist_templates",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("department_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'shift'"),
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name="fk_checklist_templates_department",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "kind IN ('first_day', 'shift')", name="ck_checklist_template_kind"
        ),
    )
    op.create_index(
        "ix_checklist_templates_dept",
        "checklist_templates",
        ["department_id", "is_active", "kind"],
    )

    op.create_table(
        "checklist_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("template_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "requires_photo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_mandatory", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("condition_position", sa.Text(), nullable=True),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["checklist_templates.id"],
            name="fk_checklist_items_template",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_checklist_items_template", "checklist_items", ["template_id", "sort_order"]
    )

    op.create_table(
        "checklist_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("template_id", sa.BigInteger(), nullable=False),
        sa.Column("shift_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'in_progress'"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name="fk_checklist_runs_employee",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["checklist_templates.id"],
            name="fk_checklist_runs_template",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "employee_id", "template_id", "shift_date", name="uq_checklist_run_shift"
        ),
        sa.CheckConstraint(
            "status IN ('in_progress', 'done')", name="ck_checklist_run_status"
        ),
    )
    op.create_index(
        "ix_checklist_runs_employee_date",
        "checklist_runs",
        ["employee_id", "shift_date"],
    )

    op.create_table(
        "checklist_completions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("done_by_employee_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "done_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("photo_file_id", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["checklist_runs.id"],
            name="fk_checklist_completions_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["checklist_items.id"],
            name="fk_checklist_completions_item",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["done_by_employee_id"],
            ["employees.id"],
            name="fk_checklist_completions_employee",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("run_id", "item_id", name="uq_checklist_completion_item"),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expected_result", sa.Text(), nullable=True),
        sa.Column(
            "scope",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'employee'"),
        ),
        sa.Column("department_id", sa.BigInteger(), nullable=True),
        sa.Column("assignee_employee_id", sa.BigInteger(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "priority",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'normal'"),
        ),
        sa.Column(
            "requires_photo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'new'"),
        ),
        sa.Column("created_by_employee_id", sa.BigInteger(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name="fk_tasks_department",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_employee_id"],
            ["employees.id"],
            name="fk_tasks_assignee",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_employee_id"],
            ["employees.id"],
            name="fk_tasks_created_by",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("scope IN ('department', 'employee')", name="ck_task_scope"),
        sa.CheckConstraint(
            "status IN ('new', 'accepted', 'in_progress', 'done', 'overdue', 'failed')",
            name="ck_task_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high')", name="ck_task_priority"
        ),
    )
    op.create_index(
        "ix_tasks_assignee_open", "tasks", ["assignee_employee_id", "status"]
    )
    op.create_index("ix_tasks_department_open", "tasks", ["department_id", "status"])
    op.create_index("ix_tasks_due", "tasks", ["status", "due_at"])

    op.create_table(
        "task_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("by_employee_id", sa.BigInteger(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_task_events_task", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["by_employee_id"],
            ["employees.id"],
            name="fk_task_events_employee",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_task_events_task", "task_events", ["task_id", "at"])

    op.create_table(
        "task_issues",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("employee_id", sa.BigInteger(), nullable=True),
        sa.Column("reason_code", sa.String(length=32), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("eta_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_task_issues_task", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name="fk_task_issues_employee",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_task_issues_task", "task_issues", ["task_id", "created_at"])

    op.create_table(
        "task_photos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("employee_id", sa.BigInteger(), nullable=True),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_task_photos_task", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name="fk_task_photos_employee",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_task_photos_task", "task_photos", ["task_id", "created_at"])

    op.create_table(
        "useful_links",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=True),
        sa.Column("department_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name="fk_useful_links_department",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_useful_links_active_sort", "useful_links", ["is_active", "sort_order"]
    )

    op.create_table(
        "feedback_questions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'scale'"),
        ),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("code", name="uq_feedback_question_code"),
        sa.CheckConstraint(
            "kind IN ('scale', 'choice', 'text')", name="ck_feedback_question_kind"
        ),
    )
    op.create_index(
        "ix_feedback_questions_active_sort",
        "feedback_questions",
        ["is_active", "sort_order"],
    )

    op.create_table(
        "feedback_answers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("shift_date", sa.Date(), nullable=False),
        sa.Column("question_id", sa.BigInteger(), nullable=False),
        sa.Column("value_scale", sa.SmallInteger(), nullable=True),
        sa.Column("value_choice", sa.Text(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name="fk_feedback_answers_employee",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["feedback_questions.id"],
            name="fk_feedback_answers_question",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "employee_id", "shift_date", "question_id", name="uq_feedback_answer"
        ),
    )
    op.create_index("ix_feedback_answers_date", "feedback_answers", ["shift_date"])


def downgrade() -> None:
    op.drop_index("ix_feedback_answers_date", table_name="feedback_answers")
    op.drop_table("feedback_answers")
    op.drop_index(
        "ix_feedback_questions_active_sort", table_name="feedback_questions"
    )
    op.drop_table("feedback_questions")
    op.drop_index("ix_useful_links_active_sort", table_name="useful_links")
    op.drop_table("useful_links")
    op.drop_index("ix_task_photos_task", table_name="task_photos")
    op.drop_table("task_photos")
    op.drop_index("ix_task_issues_task", table_name="task_issues")
    op.drop_table("task_issues")
    op.drop_index("ix_task_events_task", table_name="task_events")
    op.drop_table("task_events")
    op.drop_index("ix_tasks_due", table_name="tasks")
    op.drop_index("ix_tasks_department_open", table_name="tasks")
    op.drop_index("ix_tasks_assignee_open", table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("checklist_completions")
    op.drop_index("ix_checklist_runs_employee_date", table_name="checklist_runs")
    op.drop_table("checklist_runs")
    op.drop_index("ix_checklist_items_template", table_name="checklist_items")
    op.drop_table("checklist_items")
    op.drop_index("ix_checklist_templates_dept", table_name="checklist_templates")
    op.drop_table("checklist_templates")
    op.drop_index("ix_employees_department", table_name="employees")
    op.drop_table("employees")
    op.drop_index("ix_departments_active_sort", table_name="departments")
    op.drop_table("departments")
