#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Читает run-логи Hugging Face Space и фильтрует их по регулярке.

Зачем: `/changelog` молчит, а на руках только «не отвечает». Логи контейнера —
единственное место, где видно причину: таймаут отправки, отказ разметки или
403 на вебхуке. HF отдаёт логи потоком (SSE), поэтому читаем ограниченное
время и печатаем хвост, а не «всё с начала времён».

    python tools/hf-logs.py                       # последние строки как есть
    python tools/hf-logs.py -p "changelog|telegram" -n 60
    python tools/hf-logs.py -p "Update id=.*Duration" -n 30

Токен — в хранилище рабочей машины (`secrets/Get-Secret.ps1 HF_TOKEN`) или в
переменной окружения `HF_TOKEN`. Сам токен не печатается.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("deploy_hf", HERE / "deploy-hf.py")
deploy_hf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy_hf)

LOG_URL = (
    "https://huggingface.co/api/spaces/"
    "fryesw/meetup-planner-backend/logs/run"
)


def _payload(raw: str) -> str:
    """Строка SSE → текст записи (внутри бывает JSON с полями data/timestamp)."""
    text = raw[6:] if raw.startswith("data: ") else raw
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return text
    if isinstance(parsed, dict):
        inner = parsed.get("data")
        if isinstance(inner, str):
            return _payload(inner)
        return json.dumps(parsed, ensure_ascii=False)
    return text


def fetch_lines(seconds: float, max_lines: int) -> list[str]:
    import requests

    token = deploy_hf.hf_token()
    if not token:
        raise SystemExit("нет HF_TOKEN: secrets/Get-Secret.ps1 HF_TOKEN")
    lines: list[str] = []
    started = time.time()
    try:
        with requests.get(
            LOG_URL,
            headers={"Authorization": f"Bearer {token}"},
            stream=True,
            timeout=(15, seconds + 5),
        ) as response:
            response.raise_for_status()
            for raw in response.iter_lines(decode_unicode=True):
                if raw:
                    lines.append(_payload(raw))
                if time.time() - started > seconds or len(lines) >= max_lines:
                    break
    except requests.RequestException as exc:
        # Поток не закрывается никогда: обрыв чтения — штатный конец выборки,
        # а не повод терять уже прочитанное.
        if not lines:
            print(f"лог недоступен: {exc.__class__.__name__}", file=sys.stderr)
    return lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-p", "--pattern", default="", help="регулярка отбора")
    parser.add_argument("-n", "--lines", type=int, default=40, help="сколько строк")
    parser.add_argument(
        "-s", "--seconds", type=float, default=12.0, help="сколько секунд читать"
    )
    parser.add_argument("--raw", action="store_true", help="печатать целиком")
    args = parser.parse_args(argv)

    lines = fetch_lines(args.seconds, 20000)
    if args.pattern:
        rx = re.compile(args.pattern, re.IGNORECASE)
        lines = [line for line in lines if rx.search(line)]
    tail = lines[-args.lines :]
    print(f"прочитано строк: {len(lines)} (показаны последние {len(tail)})")
    for line in tail:
        print(line[:1000] if not args.raw else line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
