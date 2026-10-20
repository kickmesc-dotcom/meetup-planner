"""GHG6 K5: тесты каталога команд и рендера /help.

Live-handler не дёргаем — тестируем чистые функции (`visible_for`,
`render_help`). Поведение whitelist/group уже покрыто в основном handler-е
filter'ом и проверкой in `_whitelist_set`; вызов рендера через aiogram-моки
дал бы хрупкие тесты ради 3 строк проверки чата.
"""
from __future__ import annotations

from app.bot.commands_catalog import (
    COMMANDS,
    CommandSpec,
    bot_commands_for_scope,
    visible_for,
)
from app.bot.handlers.help import render_help


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


def test_group_help_hides_private_commands():
    """SemiTaskBot: в группе видны только команды со scope='both'.

    Наследная витрина (лох/чухан/мемы) снята, поэтому проверяем уже сам
    механизм скоупа, а не конкретные шуточные команды.
    """
    out_admin = visible_for("group", is_admin=True)
    out_user = visible_for("group", is_admin=False)
    assert not any(c.admin_only for c in out_admin), "admin_only утекли в group"
    assert not any(c.admin_only for c in out_user)
    cmds = {c.cmd for c in out_user}
    assert "help" in cmds
    # private-only команды в группу не утекают.
    assert "whoami" not in cmds
    assert "start" not in cmds
    assert "menu" not in cmds


def test_private_help_has_no_admin_block():
    """После ребрендинга admin_only-команд в витрине нет — блока «🔧 Админ» быть
    не должно ни у админа, ни у обычного сотрудника."""
    out_admin = visible_for("private", is_admin=True)
    out_user = visible_for("private", is_admin=False)
    assert not any(c.admin_only for c in out_admin)
    assert not any(c.admin_only for c in out_user)

    assert "🔧" not in render_help(scope="private", is_admin=True)
    assert "🔧" not in render_help(scope="private", is_admin=False)


def test_admin_only_mechanism_still_works(monkeypatch):
    """Сам механизм admin_only жив и нужен на будущее — проверяем его на
    синтетическом каталоге, чтобы покрытие не зависело от текущей витрины."""
    from app.bot import commands_catalog

    fake = CommandSpec(
        "__fake_admin", "тестовая админ-команда", scope="both", admin_only=True
    )
    monkeypatch.setattr(
        commands_catalog, "COMMANDS", commands_catalog.COMMANDS + (fake,)
    )

    admin_cmds = {c.cmd for c in visible_for("private", is_admin=True) if c.admin_only}
    user_cmds = {c.cmd for c in visible_for("private", is_admin=False)}
    group_cmds = {c.cmd for c in visible_for("group", is_admin=True)}
    assert "__fake_admin" in admin_cmds
    assert "__fake_admin" not in user_cmds
    # В группе admin_only не показываем даже админу.
    assert "__fake_admin" not in group_cmds

    text_admin = render_help(scope="private", is_admin=True)
    text_user = render_help(scope="private", is_admin=False)
    assert "🔧" in text_admin and "/__fake_admin" in text_admin
    assert "🔧" not in text_user


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


def test_bot_commands_for_scope_follows_scopes():
    """`bot.set_my_commands` отдаёт ровно то, что помечено нужным scope."""
    private = {c.cmd for c in bot_commands_for_scope("private")}
    group = {c.cmd for c in bot_commands_for_scope("group")}
    # HR-команды — только личка.
    for cmd in ("start", "menu", "whoami"):
        assert cmd in private, f"{cmd} должен быть в private"
        assert cmd not in group, f"{cmd} не должен светиться в группе"
    assert "help" in private and "help" in group
    # В каталоге нет admin_only — значит и в menu их не будет.
    assert not any(c.admin_only for c in COMMANDS)
    assert "__fake_admin" not in private


def test_private_user_help_contains_expected_public_commands():
    text = render_help(scope="private", is_admin=False)
    for cmd in ("/start", "/menu", "/whoami", "/help"):
        assert cmd in text, f"в private /help нет {cmd}"
    # Наследные шуточные команды сняты с витрины (обработчики при этом живы).
    for legacy in ("/loser", "/phrase", "/chukhan", "/top"):
        assert legacy not in text, f"{legacy} не должен светиться в витрине"
