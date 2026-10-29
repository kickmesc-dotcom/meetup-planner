# База — официальный образ Python из зеркала Docker Hub на AWS ECR Public,
# а не `python:3.12-slim` с Docker Hub напрямую. Причина: сборщик Amvera
# переписывает ссылки на Docker Hub в свой внутренний proxy-реестр
# harbor.waw.amverum.com, и с 28.09.2026 тот отдаёт на blob'ах
# `stream error: stream ID 1; INTERNAL_ERROR; received from peer` — каждая
# сборка падала на «Retrieving image python:3.12-slim». Содержимое образа
# идентично (ECR Public зеркалит Docker Official Images), отличается только
# путь доставки. Если Amvera когда-нибудь начнёт проксировать и этот адрес —
# вернуть прежнюю строку и завести тикет в их поддержку.
FROM public.ecr.aws/docker/library/python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
# `.[mt]` — движок офлайн-перевода (CTranslate2 + токенизаторы, план, 11).
# Самых весов моделей в образе НЕТ: они качаются или монтируются на хосте, где
# хватает памяти. На Amvera (0,5 ГБ) переменные `TRANSLATE_*` пусты, модели не
# поднимаются, и пакеты только лежат на диске.
RUN pip install --upgrade pip && pip install hatchling && pip install ".[mt]"

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# HuggingFace Spaces runs containers as a non-root user (uid 1000).
# Create a writable home for caches and chown the app dir.
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
ENV HOME=/home/appuser

# HuggingFace Spaces requires the app to listen on 7860.
# For other Docker hosts, override PORT env var if needed.
ENV PORT=7860
EXPOSE 7860

# CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
# CMD ["sh", "-c", "alembic upgrade head; python3 -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level debug"]

# Миграции идут через `app.db.migrate`: перед DDL берётся advisory-lock в
# Postgres, чтобы два контейнера (Amvera и HF Space) на одной базе не
# применяли миграции одновременно (аудит 26.10.2026, S-14). Если база не
# Postgres — поведение прежнее.
# `--no-server-header` убирает заголовок `server: uvicorn` из ответов (аудит
# 26.10.2026, S-15). Смысл небольшой, но бесплатный: заголовок сообщает всем
# желающим, что за сервер и на чём написан. Убирается на уровне uvicorn, а не
# middleware — иначе он остался бы на ответах, которые middleware не проходит
# (404 от самого сервера, ответы на ошибки до приложения).
CMD ["sh", "-c", "python -m app.db.migrate && uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-server-header"]