"""GHG6 K5: тесты каталога команд и рендера /help.

Live-handler не дёргаем — тестируем чистые функции (`visible_for`,
`render_help`). Поведение whitelist/group уже покрыто в основном handler-е
filter'ом и проверкой in `_whitelist_set`; вызов рендера через aiogram-моки
дал бы хрупкие тесты ради 3 строк проверки чата.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.bot.commands_catalog import (
    COMMANDS,
    CommandSpec,
    bot_commands_for_scope,
    visible_for,
)
from app.bot.handlers.help import _format_remaining, render_help


def test_catalog_not_empty():
    assert len(COMMANDS) > 0
    # /help сам должен присутствовать (иначе пользователь не узнает о /help из /help)
    assert any(c.cmd == "help" for c in COMMANDS)


def test_catalog_all_specs_well_formed():
    for c in COMMANDS:
        assert c.cmd, "cmd пустой"
        assert c.cmd == c.cmd.lower(), f"{c.cmd}: должен быть lowercase"
        assert "/" not in c.cmd, f"{c.cmd}: без слэша"
        assert c.desc_ru, f"{c.cmd}: desc_ru пустой"
        assert c.scope in {"private", "group", "both"}


def test_group_help_hides_admin_only():
    """В групповом /help admin_only-команды не показываются — даже если автор админ."""
    out_admin = visible_for("group", is_admin=True)
    out_user = visible_for("group", is_admin=False)
    assert not any(c.admin_only for c in out_admin), "admin_only утекли в group"
    assert not any(c.admin_only for c in out_user)
    # При этом обычные «both»/«group» команды на месте.
    cmds = {c.cmd for c in out_user}
    assert "loser" in cmds
    assert "meetings" in cmds
    # `whoami` — scope='private', в группе не показываем.
    assert "whoami" not in cmds


def test_private_help_admin_sees_admin_block():
    """В личке у админа admin_only-команды отдаются и попадают в раздел «🔧 Админ»."""
    out_admin = visible_for("private", is_admin=True)
    out_user = visible_for("private", is_admin=False)

    admin_cmds = {c.cmd for c in out_admin if c.admin_only}
    assert "forcechukhan" in admin_cmds
    assert "zaebal_undo" in admin_cmds

    user_cmds = {c.cmd for c in out_user}
    assert "forcechukhan" not in user_cmds
    assert "zaebal_undo" not in user_cmds

    # Текст рендера — у админа есть блок «🔧 Админ», у обычного нет.
    text_admin = render_help(scope="private", is_admin=True)
    text_user = render_help(scope="private", is_admin=False)
    assert "🔧" in text_admin
    assert "🔧" not in text_user
    assert "/forcechukhan" in text_admin
    assert "/forcechukhan" not in text_user


def test_render_html_uses_b_tags_and_slash_prefix():
    text = render_help(scope="private", is_admin=False)
    # Подсказка — команда обязана быть со слэшем и в <b>.
    assert "<b>/help</b>" in text
    assert "📖 <b>Доступные команды</b>" in text


def test_hidden_never_shows():
    """Если в каталоге появится `hidden=True` элемент — он не должен попадать ни
    в /help (ни в любой scope), ни в Telegram-menu."""
    fake = CommandSpec("__nonexistent_hidden", "не должно отображаться", scope="both", hidden=True)
    # Локальная проверка visible_for / bot_commands_for_scope симулируется через
    # фильтр: убеждаемся, что код фильтрует именно по флагу `hidden`.
    from app.bot import commands_catalog

    original = commands_catalog.COMMANDS
    try:
        commands_catalog.COMMANDS = original + (fake,)
        assert all(c.cmd != fake.cmd for c in visible_for("private", is_admin=True))
        assert all(c.cmd != fake.cmd for c in visible_for("group", is_admin=False))
        assert all(c.cmd != fake.cmd for c in bot_commands_for_scope("private"))
        assert all(c.cmd != fake.cmd for c in bot_commands_for_scope("group"))
    finally:
        commands_catalog.COMMANDS = original


def test_bot_commands_for_scope_excludes_admin_only():
    """`bot.set_my_commands` не должен светить admin_only-команды в menu — даже
    если у Telegram API нет понятия "admin scope". Видны они только через /help в личке."""
    private = {c.cmd for c in bot_commands_for_scope("private")}
    group = {c.cmd for c in bot_commands_for_scope("group")}
    assert "forcechukhan" not in private
    assert "forcechukhan" not in group
    assert "zaebal_undo" not in private
    # /start — только private.
    assert "start" in private
    assert "start" not in group
    # /whoami — только private.
    assert "whoami" in private
    assert "whoami" not in group


def test_private_user_help_contains_expected_public_commands():
    text = render_help(scope="private", is_admin=False)
    for cmd in ("/start", "/meetings", "/loser", "/phrase", "/whoami", "/help"):
        assert cmd in text, f"в private /help нет {cmd}"


# --- GHG7 P1.4: индикация активной zaebal-паузы в /help ---


def test_format_remaining_days_hours_minutes():
    now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    ends = now + timedelta(days=2, hours=4, minutes=15)
    assert _format_remaining(ends, now=now) == "2д 4ч 15м"


def test_format_remaining_only_hours_and_minutes():
    now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    ends = now + timedelta(hours=3, minutes=20)
    assert _format_remaining(ends, now=now) == "3ч 20м"


def test_format_remaining_only_minutes():
    now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    ends = now + timedelta(minutes=43)
    assert _format_remaining(ends, now=now) == "43м"


def test_format_remaining_under_a_minute_clamps_to_lt_1m():
    """Race: pause.ends_at чуть в прошлом или вот-вот закончится →
    показываем «<1м», а не «-2м» или «0м». Handler покажет «активна»,
    автореставрация скоро её снимет.
    """
    now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    assert _format_remaining(now + timedelta(seconds=30), now=now) == "<1м"
    assert _format_remaining(now - timedelta(minutes=5), now=now) == "<1м"


def test_render_help_no_pause_no_badge():
    text = render_help(scope="group", is_admin=False)
    assert "/zaebal" in text
    assert "⏸️" not in text
    assert "пауза" not in text


def test_render_help_with_pause_adds_badge_to_zaebal():
    now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
    ends = now + timedelta(hours=5, minutes=30)
    text = render_help(scope="group", is_admin=False, paused_until=ends, now=now)
    # Badge только на /zaebal — не на /zaebal_vote.
    lines = text.split("\n")
    zaebal_line = next(line for line in lines if "<b>/zaebal</b>" in line)
    assert "⏸️ пауза 5ч 30м" in zaebal_line
    # /zaebal_vote — без badge (это запуск голосования, не сама пауза).
    vote_line = next(line for line in lines if "<b>/zaebal_vote</b>" in line)
    assert "⏸️" not in vote_line
