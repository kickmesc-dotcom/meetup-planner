"""Выложить модель перевода (CTranslate2) на Hugging Face Hub.

Зачем отдельный инструмент, а не «скопировал в Space руками». Бэкенд берёт
модели с Hub по имени репозитория (`TRANSLATE_MODEL_REPO`,
`TRANSLATE_UZ_MODEL_REPO`), и это имя должно указывать на что-то, что реально
существует и скачивается. Веса в git проекта не кладутся: 600 МБ в истории —
это не модель, а проблема.

Почему узбекская модель грузится нами, а не берётся готовой. Готовых
CTranslate2-конверсий ru→uz нет, а конвертировать на сервере нельзя: в образе
нет torch (он весит больше, чем весь бэкенд). Поэтому конверсия делается один
раз на рабочей машине и публикуется сюда; сервер только скачивает.

Лицензии и происхождение. `booba-uz/english-uzbek-translation_v3` —
m2m100-418M, дообученная на узбекский, лицензия apache-2.0 (база — MIT).
Конверсия в int8 ничего не переобучает: меняется только формат весов.

Токен не печатается и не попадает в аргументы командной строки: он читается из
`HF_TOKEN` или из DPAPI-хранилища рабочей машины (`secrets/Get-Secret.ps1`),
как в `deploy-hf.py`.

    ./.venv/Scripts/python.exe ../tools/upload-mt-model.py \\
        --dir C:/tmp/m2m-uz-ct2 --repo <логин>/m2m100-en-uz-ct2-int8
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
SECRETS = WORKSPACE / "secrets"


def _token() -> str:
    token = (os.environ.get("HF_TOKEN") or "").strip()
    if token:
        return token
    script = SECRETS / "Get-Secret.ps1"
    if script.exists():
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-File", str(script), "HF_TOKEN"],
                capture_output=True,
                text=True,
                timeout=90,
                check=True,
            )
            value = (out.stdout or "").strip()
            if value:
                return value
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"хранилище секретов недоступно: {exc}", file=sys.stderr)
    sys.exit("Нет HF_TOKEN: положите его в secrets/ (Get-Secret.ps1) или в окружение.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, help="каталог с моделью CTranslate2")
    parser.add_argument("--repo", required=True, help="репозиторий вида логин/имя")
    parser.add_argument(
        "--private",
        action="store_true",
        help="приватный репозиторий (Space тогда должен иметь доступ к нему)",
    )
    args = parser.parse_args()

    source = Path(args.dir)
    needed = ["model.bin", "config.json", "shared_vocabulary.json"]
    missing = [name for name in needed if not (source / name).exists()]
    if missing:
        sys.exit(f"в {source} нет файлов модели: {', '.join(missing)}")
    # Без токенизатора модель бесполезна: сервер не сможет разбить текст.
    if not any((source / n).exists() for n in ("tokenizer.json", "sentencepiece.bpe.model")):
        sys.exit("нет ни tokenizer.json, ни sentencepiece.bpe.model")

    from huggingface_hub import HfApi

    api = HfApi(token=_token())
    # Имя пользователя не печатаем в виде токена, но без него `--repo` не
    # проверить: показываем только то, что просили выложить.
    api.create_repo(repo_id=args.repo, repo_type="model", private=args.private, exist_ok=True)
    api.upload_folder(
        folder_path=str(source),
        repo_id=args.repo,
        repo_type="model",
        commit_message="int8 CTranslate2 conversion (ru/en -> uz pipeline)",
    )
    print(f"готово: https://huggingface.co/{args.repo}")


if __name__ == "__main__":
    main()
