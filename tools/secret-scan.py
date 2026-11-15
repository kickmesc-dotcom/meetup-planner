#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Поиск случайно закоммиченных секретов — в файлах и в истории.

Зачем. Секрет, попавший в коммит, не перестаёт быть секретом после удаления
строки: он остаётся в истории, доступной каждому, у кого есть доступ к
репозиторию, и в клонах/форках. Обычное ревью диффа этого не ловит — строка
уже удалена. Поэтому проверка идёт по двум поверхностям:

  * дерево — отслеживаемые файлы (`git ls-files`);
  * история — добавленные строки всех коммитов (`git log -p --all`), только
    с флагом `--history` (в CI нужен `fetch-depth: 0`, иначе истории нет).

Что считается секретом: только то, что можно проверить без ложных тревог на
каждом прогоне. Пароль в `DATABASE_URL` на localhost — не секрет, а тестовая
заглушка, и в список исключений он попадает осознанно, а не «чтобы было тихо».

Код возврата: 0 — чисто, 1 — есть находки. Найденное значение никогда не
печатается целиком: в логе остаются первые символы и длина, этого хватает,
чтобы опознать ключ, и недостаточно, чтобы им воспользоваться.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Шаблоны, у которых почти нет ложных срабатываний: формат задан провайдером.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Токен бота: id, двоеточие и 35 символов. `AA` в начале — привычка, а не
    # гарантия формата: проверяем длину, а не префикс, иначе редкий токен
    # с другим началом пройдёт мимо.
    ("telegram_bot_token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe_secret", re.compile(r"\bsk_live_[A-Za-z0-9]{20,}\b")),
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    ),
    (
        # Пароль в строке подключения: `postgres://user:secret@host`.
        # Локальные адреса и явные заглушки исключены — это тестовые стенды.
        "db_url_with_password",
        # Заглушки тестов маскирования (`pw-live`, `super-secret`) — не секреты,
        # поэтому перечислены явно. Иначе проверка стала бы красной на каждом
        # прогоне, её бы отключили — и вместе с ней настоящие находки.
        re.compile(
            r"\bpostgres(?:ql)?(?:\+\w+)?://[^\s:/@]+:"
            # `***` — уже замаскированное значение: это результат проверки, а не
            # сам секрет.
            r"(?!\$\{|<|\*|changeme|password|pass|pw-|super-secret|secret|test|dummy|example|u:p)"
            r"[^\s@/]{3,}@(?!(?:localhost|127\.0\.0\.1|db|host)\b)[^\s/\"']+"
        ),
    ),
]

# Файлы, где секрет — это описание, а не значение: шаблоны окружения.
ALLOWED_PATHS = re.compile(r"(^|/)(\.env\.(example|sample|template)|.*\.md)$")


def mask(secret: str) -> str:
    """Первые 4 символа и длина: опознать ключ можно, воспользоваться — нет."""
    head = secret[:4] if len(secret) > 4 else ""
    return f"{head}… ({len(secret)} симв.)"


def scan_line(line: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for name, pattern in PATTERNS:
        for match in pattern.finditer(line):
            found.append((name, match.group(0)))
    return found


def _git(args: list[str], root: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout


def scan_tree(root: Path) -> list[str]:
    problems: list[str] = []
    files = _git(["ls-files"], root).splitlines()
    for rel in files:
        if ALLOWED_PATHS.search(rel.replace("\\", "/")):
            continue
        path = root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, secret in scan_line(line):
                problems.append(f"{rel}:{lineno} {name} {mask(secret)}")
    return problems


def scan_history(root: Path) -> list[str]:
    problems: list[str] = []
    commit = "?"
    path = "?"
    diff = _git(
        ["log", "-p", "--all", "--no-color", "--unified=0", "--format=commit %H"],
        root,
    )
    for line in diff.splitlines():
        if line.startswith("commit "):
            commit = line.split(" ", 1)[1][:7]
            continue
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if ALLOWED_PATHS.search(path):
            continue
        for name, secret in scan_line(line[1:]):
            problems.append(f"{commit} {path} {name} {mask(secret)}")
    return problems


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — печать не имеет права ронять проверку
        pass

    parser = argparse.ArgumentParser(prog="secret-scan.py", description=__doc__)
    parser.add_argument("--history", action="store_true", help="проверить и историю коммитов")
    parser.add_argument("--root", default=None, help="каталог репозитория (для тестов)")
    args = parser.parse_args()

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[1]
    if not (root / ".git").exists():
        sys.exit(f"Не git-репозиторий: {root}")

    problems = scan_tree(root)
    if args.history:
        problems += scan_history(root)

    if problems:
        print(f"✗ Найдено похожее на секреты: {len(problems)}")
        for item in problems:
            print(f"  {item}")
        print(
            "Что делать: отозвать ключ у провайдера, заменить значение, очистить "
            "историю (filter-repo) и только потом считать инцидент закрытым.",
        )
        return 1

    scope = "дерево и история" if args.history else "дерево"
    print(f"✓ Секретов не найдено ({scope})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
