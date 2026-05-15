FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install hatchling && pip install .

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

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]