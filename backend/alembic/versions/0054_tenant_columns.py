"""`org_id` у всех бизнес-таблиц и уникальность внутри тенанта.

Продолжение B2B_PLATFORM_PLAN (фаза 1, шаги 1.1 и 1.4). До этой миграции
организация была только у `employees` и `departments`, а остальные ~70 таблиц
жили «в общем котле»: завести второго клиента означало бы отдать ему чужие
смены, задачи и чек-листы.

Что делает:

1. добавляет `org_id` (FK на `organizations`, индекс, `server_default = 1`)
   всем бизнес-таблицам. Существующие строки автоматически становятся данными
   первой организации, простой при деплое не нужен: PG 11+ добавляет колонку
   с константным дефолтом без перезаписи таблицы;
2. переводит уникальные ключи внутрь тенанта — там, где они были глобальными:
   сотрудник (`org_id`,`user_id` — человек может работать в двух филиалах),
   зал, вопросы обратной связи, праздники, блоб по sha256, недельный чукхан,
   прокси, источники таблиц, ачивки и маркеры опыта.

Чего НЕ делает: не трогает `users` (личность человека глобальна) и
`admin_config` (ключ-значение установки; станет тенантным, когда появится
второй клиент — это единственная строка долга).

Revision ID: 0054_tenant_columns
Revises: 0053_tenancy
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0054_tenant_columns"
down_revision: str | None = "0053_tenancy"
branch_labels = None
depends_on = None

DEFAULT_ORG_ID = 1

# Все таблицы, которым нужен `org_id`, кроме трёх, получивших его в 0053
# (`departments`, `employees`, `organization_members`). Список явный: он же
# проверяется стражем `tests/test_tenant_schema.py`.
TENANT_TABLES: tuple[str, ...] = (
    "achievement_counters",
    "app_access_links",
    "app_notifications",
    "availability_ranges",
    "birthday_notifications",
    "birthdays",
    "bot_pause",
    "chat_activity_daily",
    "chat_messages",
    "checklist_completions",
    "checklist_items",
    "checklist_runs",
    "checklist_templates",
    "employee_achievements",
    "employee_training_days",
    "employee_training_steps",
    "event_log",
    "feedback_answers",
    "feedback_questions",
    "game_holidays",
    "game_journal",
    "game_media_posts",
    "game_nominations",
    "game_profiles",
    "game_prompts",
    "game_voice_submissions",
    "game_voice_tasks",
    "halls",
    "hr_handover_items",
    "hr_handovers",
    "hr_issue_events",
    "hr_issues",
    "hr_roster_snapshots",
    "hr_shift_templates",
    "hr_shifts",
    "hr_simulation_sessions",
    "loser_outbox",
    "loser_rolls",
    "media_blobs",
    "meeting_attendance",
    "meeting_feedback",
    "meeting_reminders",
    "meetings",
    "music_game_rounds",
    "music_selections",
    "music_track_likes",
    "music_tracks",
    "participant_personas",
    "poll_options",
    "poll_votes",
    "polls",
    "proxy_entries",
    "sheet_sources",
    "shift_hall_choices",
    "standard_checks",
    "standard_questions",
    "standards",
    "task_assignments",
    "task_events",
    "task_issues",
    "task_photos",
    "task_reminders",
    "tasks",
    "useful_links",
    "user_achievements",
    "weekly_chukhan",
    "worm_assignments",
    "xp_daily",
    "xp_grants",
)

# (таблица, старое имя, новое имя, колонки). Старые ключи глобальные — с
# появлением второй организации они запретили бы ей завести свой «bar».
UNIQUE_SWAPS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("employees", "uq_employees_user", "uq_employee_org_user", ("org_id", "user_id")),
    ("halls", "uq_hall_slug", "uq_hall_org_slug", ("org_id", "slug")),
    (
        "feedback_questions",
        "uq_feedback_question_code",
        "uq_feedback_question_org_code",
        ("org_id", "code"),
    ),
    (
        "game_holidays",
        "uq_game_holiday_md",
        "uq_game_holiday_org_md",
        ("org_id", "month", "day"),
    ),
    (
        "media_blobs",
        "uq_media_blobs_sha",
        "uq_media_blobs_org_sha",
        ("org_id", "sha256"),
    ),
    (
        "weekly_chukhan",
        "uq_weekly_chukhan_week",
        "uq_weekly_chukhan_org_week",
        ("org_id", "week_start"),
    ),
    (
        "proxy_entries",
        "uq_proxy_server_port",
        "uq_proxy_org_server_port",
        ("org_id", "server", "port"),
    ),
    (
        "sheet_sources",
        "uq_sheet_sources_sheet",
        "uq_sheet_sources_org_sheet",
        ("org_id", "spreadsheet_id", "gid"),
    ),
)

# Уникальные ИНДЕКСЫ (не constraints): пересоздаём с `org_id` впереди.
UNIQUE_INDEX_SWAPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("uq_user_achievement", "user_achievements", ("org_id", "user_id", "code")),
    ("ix_xp_grant_key", "xp_grants", ("org_id", "user_id", "idem_key")),
)


def upgrade() -> None:
    for table in TENANT_TABLES:
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

    for table, old, new, columns in UNIQUE_SWAPS:
        op.drop_constraint(old, table, type_="unique")
        op.create_unique_constraint(new, table, list(columns))

    for name, table, columns in UNIQUE_INDEX_SWAPS:
        op.drop_index(name, table_name=table)
        op.create_index(name, table, list(columns), unique=True)


def downgrade() -> None:
    for name, table, columns in reversed(UNIQUE_INDEX_SWAPS):
        op.drop_index(name, table_name=table)
        old_columns = tuple(c for c in columns if c != "org_id")
        op.create_index(name, table, list(old_columns), unique=True)

    for table, old, new, _columns in reversed(UNIQUE_SWAPS):
        op.drop_constraint(new, table, type_="unique")
        op.create_unique_constraint(old, table, _old_columns(old, table))

    for table in reversed(TENANT_TABLES):
        op.drop_index(f"ix_{table}_org_id", table_name=table)
        op.drop_constraint(f"fk_{table}_org", table, type_="foreignkey")
        op.drop_column(table, "org_id")


# Старые наборы колонок для отката: держим рядом, а не в теле функции, чтобы
# upgrade и downgrade читались как одна таблица решений.
OLD_UNIQUE_COLUMNS: dict[str, tuple[str, ...]] = {
    "uq_employees_user": ("user_id",),
    "uq_hall_slug": ("slug",),
    "uq_feedback_question_code": ("code",),
    "uq_game_holiday_md": ("month", "day"),
    "uq_media_blobs_sha": ("sha256",),
    "uq_weekly_chukhan_week": ("week_start",),
    "uq_proxy_server_port": ("server", "port"),
    "uq_sheet_sources_sheet": ("spreadsheet_id", "gid"),
}


def _old_columns(constraint: str, table: str) -> list[str]:
    try:
        return list(OLD_UNIQUE_COLUMNS[constraint])
    except KeyError:  # pragma: no cover - защита от опечатки в имени
        raise RuntimeError(f"нет старого набора колонок для {constraint} ({table})")
