"""Тесты `tools/switch-db.py` — переключателя базы и вебхука.

Покрываем три места, которые уже один раз ломались или могли сломаться тихо:

1. **Сверка хоста из `/api/meta`** (`_mask_like_meta` + `meta_host_matches`).
   Раньше совпадением считался любой `*.neon.tech`, из-за чего в отчёте о
   резервах ОБЕ базы выглядели боевыми, а подтверждение переключения ничего не
   доказывало.
2. **Разбор кандидатов** (`dsn_candidates`, `dsn_label`, `resolve_target`): DSN
   собираются из хранилища и из ВСЕХ `leltokens*.txt` (включая старый дамп, где
   остался второй Neon), имена даются по endpoint, работает однозначный префикс.
3. **Отказ переводить вебхук на неотвечающий хост** и проверка ответа Telegram
   (`cmd_webhook`): без `--force` должен быть ненулевой выход, с `--force` —
   перевод, а расхождение записанного url с ожидаемым — код 1.

Запуск из корня монорепо:

    backend/.venv/Scripts/python.exe -m pytest tools/tests -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

LIVE_HOST = "ep-cool-union-aszq9p4u.c-4.eu-central-1.aws.neon.tech"
DEAD_HOST = "ep-rapid-butterfly-al1rllsg-pooler.c-3.eu-central-1.aws.neon.tech"
LIVE_DSN = f"postgresql://neondb_owner:pw-live@{LIVE_HOST}/neondb?ssl=require"
DEAD_DSN = f"postgresql+asyncpg://neondb_owner:pw-dead@{DEAD_HOST}/neondb?ssl=require"


# --------------------------------------------------------------------------
# вспомогательное
# --------------------------------------------------------------------------
def _fake_workspace(tmp_path: Path, switch_db, secrets: dict[str, str], tokens: dict[str, str]):
    """Подменяет рабочую папку, хранилище секретов и файлы токенов.

    Тесты не должны читать настоящие `secrets/` и `leltokens*.txt`: там боевые
    токены и DSN.
    """
    (tmp_path / "secrets").mkdir(exist_ok=True)
    (tmp_path / "secrets" / "Get-Secret.ps1").write_text("# fake\n", encoding="utf-8")
    for name, text in tokens.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    switch_db.WORKSPACE = str(tmp_path)
    switch_db.SECRET_SCRIPT = str(tmp_path / "secrets" / "Get-Secret.ps1")
    switch_db._STORE = dict(secrets)
    switch_db.secret = lambda key: secrets.get(key)
    switch_db._store = lambda: dict(secrets)


class _FakeResponse:
    """Минимальный контекст-менеджер вместо ответа `urlopen`."""

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


# --------------------------------------------------------------------------
# 1. Маска и сверка хоста из /api/meta
# --------------------------------------------------------------------------
def test_mask_like_meta_repeats_backend_mask(switch_db):
    """Та же маска, что в `app/api/routes_meta.py::_mask_host`."""
    assert switch_db._mask_like_meta(LIVE_HOST) == "ep-cool-union-….neon.tech"
    assert switch_db._mask_like_meta(DEAD_HOST) == "ep-rapid-butte….neon.tech"
    assert switch_db._mask_like_meta("localhost") == "localhost"
    assert switch_db._mask_like_meta("") == ""


def test_meta_host_matches_only_its_own_database(switch_db):
    masked = "ep-cool-union-….neon.tech"
    assert switch_db.meta_host_matches(masked, LIVE_DSN) is True
    # Регресс: раньше здесь было True — сверялось по домену `neon.tech`,
    # поэтому любой Neon-хост «совпадал» с любым.
    assert switch_db.meta_host_matches(masked, DEAD_DSN) is False


def test_meta_host_matches_handles_empty_and_short(switch_db):
    assert switch_db.meta_host_matches(None, LIVE_DSN) is False
    assert switch_db.meta_host_matches("", LIVE_DSN) is False
    assert switch_db.meta_host_matches("ep-rapid-butte….neon.tech", DEAD_DSN) is True


# --------------------------------------------------------------------------
# 2. Кандидаты и имена
# --------------------------------------------------------------------------
def test_dsn_label_uses_neon_endpoint(switch_db):
    assert switch_db.dsn_label(LIVE_DSN) == "cool-union"
    assert switch_db.dsn_label(DEAD_DSN) == "rapid-butterfly"
    assert switch_db.dsn_label("postgresql://user:pw@db.example.com:5432/x") == "db"
    assert switch_db.dsn_label("не-dsn") is None


def test_dsn_candidates_reads_store_and_every_token_file(tmp_path, switch_db):
    """`current` — из хранилища; второй Neon находится даже в СТАРОМ дампе.

    Именно из-за чтения только актуального `leltokens2.txt` «резерв №1» исчезал
    из списка, и состояние резервов выглядело неактуальным.
    """
    _fake_workspace(
        tmp_path,
        switch_db,
        secrets={"DATABASE_URL": LIVE_DSN},
        tokens={
            "leltokens2.txt": f"# актуальный\nDATABASE_URL: {LIVE_DSN}\n",
            "leltokens2.backup-2026-09-29.txt": f"# старый дамп\nDATABASE_URL: {DEAD_DSN}\n",
        },
    )
    cands = switch_db.dsn_candidates()
    assert cands["current"] == LIVE_DSN
    assert cands["cool-union"] == LIVE_DSN
    assert cands["rapid-butterfly"] == DEAD_DSN
    # позиционные имена остались для совместимости со старыми записями
    assert cands["dsn1"] == DEAD_DSN
    assert cands["dsn2"] == LIVE_DSN


def test_dsn_candidates_reads_reserve_keys(tmp_path, switch_db):
    _fake_workspace(
        tmp_path,
        switch_db,
        secrets={"DATABASE_URL": LIVE_DSN, "DATABASE_URL_RESERVE1": DEAD_DSN},
        tokens={},
    )
    cands = switch_db.dsn_candidates()
    assert cands["reserve1"] == DEAD_DSN
    assert cands["rapid-butterfly"] == DEAD_DSN


def test_check_list_prints_mask_without_password(tmp_path, switch_db, capsys):
    _fake_workspace(tmp_path, switch_db, secrets={"DATABASE_URL": LIVE_DSN}, tokens={})
    assert switch_db.cmd_check(switch_db.argparse.Namespace(target="--list", list=True)) == 0
    out = capsys.readouterr().out
    assert "ep-cool-union" in out
    assert "pw-live" not in out  # пароль не печатаем
    assert "neondb_owner:***@" in out


def test_resolve_target_accepts_name_prefix_and_full_dsn(tmp_path, switch_db):
    _fake_workspace(
        tmp_path,
        switch_db,
        secrets={"DATABASE_URL": LIVE_DSN},
        tokens={"leltokens2.backup-2026-09-29.txt": f"{DEAD_DSN}\n"},
    )
    assert switch_db.resolve_target("current") == LIVE_DSN
    assert switch_db.resolve_target("cool-union") == LIVE_DSN
    # однозначный префикс
    assert switch_db.resolve_target("rapid") == DEAD_DSN
    # полный DSN принимается как есть
    assert switch_db.resolve_target("postgresql://u:p@h/db") == "postgresql://u:p@h/db"


def test_resolve_target_errors_are_explicit(tmp_path, switch_db):
    _fake_workspace(tmp_path, switch_db, secrets={"DATABASE_URL": LIVE_DSN}, tokens={})
    with pytest.raises(SystemExit) as exc:
        switch_db.resolve_target("такой-базы-нет")
    assert "Не знаю базу" in str(exc.value)


def test_posix_hints_where_secrets_live(switch_db):
    hint = switch_db.secrets_hint("BOT_TOKEN")
    assert "BOT_TOKEN" in hint
    assert "Get-Secret.ps1" in hint
    assert "secrets/README.md" in hint


# --------------------------------------------------------------------------
# 3. Вебхук: отказ на мёртвом хосте и проверка ответа Telegram
# --------------------------------------------------------------------------
def test_webhook_refuses_when_host_is_down(tmp_path, switch_db, monkeypatch):
    _fake_workspace(
        tmp_path,
        switch_db,
        secrets={"BOT_TOKEN": "123:fake", "TG_WEBHOOK_SECRET": "s3cret"},
        tokens={},
    )
    monkeypatch.setattr(switch_db, "fetch_meta", lambda base, timeout=20.0: None)
    with pytest.raises(SystemExit) as exc:
        switch_db.cmd_webhook(switch_db.argparse.Namespace(target="amvera", force=False))
    assert "не отвечает" in str(exc.value)
    assert "status" in str(exc.value)  # подсказка, чем проверить хосты


def test_webhook_force_switches_and_reports_queue(tmp_path, switch_db, monkeypatch, capsys):
    _fake_workspace(
        tmp_path,
        switch_db,
        secrets={"BOT_TOKEN": "123:fake", "TG_WEBHOOK_SECRET": "s3cret"},
        tokens={},
    )
    expected = f"{switch_db.HOSTS['amvera']}/tg/webhook"
    calls: list[str] = []

    def fake_urlopen(url, timeout=30):
        calls.append(url)
        if "setWebhook" in url:
            return _FakeResponse({"ok": True, "result": True, "description": "Webhook was set"})
        return _FakeResponse(
            {"ok": True, "result": {"url": expected, "pending_update_count": 3}}
        )

    monkeypatch.setattr(switch_db, "fetch_meta", lambda base, timeout=20.0: None)
    monkeypatch.setattr(switch_db.urllib.request, "urlopen", fake_urlopen)

    rc = switch_db.cmd_webhook(switch_db.argparse.Namespace(target="amvera", force=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "3 апдейт(ов)" in out
    assert "✅" in out
    # ссылку собирает urlencode: secret_token и drop_pending_updates на месте
    assert "secret_token=s3cret" in calls[0]
    assert "drop_pending_updates=false" in calls[0]


def test_webhook_returns_error_when_telegram_stored_other_url(
    tmp_path, switch_db, monkeypatch, capsys
):
    _fake_workspace(
        tmp_path,
        switch_db,
        secrets={"BOT_TOKEN": "123:fake", "TG_WEBHOOK_SECRET": "s3cret"},
        tokens={},
    )

    def fake_urlopen(url, timeout=30):
        if "setWebhook" in url:
            return _FakeResponse({"ok": True, "result": True})
        # Telegram записал чужой адрес — это ошибка, а не успех
        return _FakeResponse(
            {
                "ok": True,
                "result": {
                    "url": f"{switch_db.HOSTS['hf']}/tg/webhook",
                    "pending_update_count": 0,
                },
            }
        )

    monkeypatch.setattr(switch_db, "fetch_meta", lambda base, timeout=20.0: {"status": "ok"})
    monkeypatch.setattr(switch_db.urllib.request, "urlopen", fake_urlopen)

    rc = switch_db.cmd_webhook(switch_db.argparse.Namespace(target="amvera", force=False))
    assert rc == 1
    assert "другой адрес" in capsys.readouterr().out
