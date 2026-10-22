"""Имя владельца: «Серж-NEO» → «Сергей» (повторно, уже навсегда).

Почему отдельная миграция после `0050`, где переименование уже было. Сид
`seed_users` перезаписывал `users.display_name` из `WHITELIST_NAMES` на каждом
старте приложения. Миграция `0050` имя меняла, но следующий деплой возвращал
ник из env — в профиле и ленте снова было «Серж-NEO».

Сначала убран сам механизм отката (`app/db/seed.py` больше не трогает имя
существующего человека), теперь данные приводятся к нужному виду один раз.
Условие по Telegram-ID, а не по строке: имя могли успеть поправить вручную,
и затирать чужую правку нельзя. Если имя уже другое (например, владелец выбрал
своё), миграция ничего не делает.

Revision ID: 0052_owner_name_fix
Revises: 0051_app_access_links
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0052_owner_name_fix"
down_revision: str | None = "0051_app_access_links"
branch_labels = None
depends_on = None

OWNER_TG_ID = 306733739
OLD_NAMES = ("Серж-NEO", "Сергей Neo")
NEW_NAME = "Сергей"


def upgrade() -> None:
    # По одному варианту за раз: `text()` с параметрами читается одинаково на
    # Postgres и SQLite, а расширяемый `IN` там ведёт себя по-разному.
    for old_name in OLD_NAMES:
        op.execute(
            sa.text(
                "UPDATE users SET display_name = :new_name "
                "WHERE telegram_id = :tg_id AND display_name = :old_name"
            ).bindparams(
                new_name=NEW_NAME,
                tg_id=OWNER_TG_ID,
                old_name=old_name,
            )
        )


def downgrade() -> None:
    # Обратно в ник не возвращаем: это была не «версия схемы», а исправление
    # данных. Откат миграции не должен снова ломать подпись человека.
    pass
