---
title: Meetup Planner Backend
emoji: 📅
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# Backend (Meetup Planner)

FastAPI + aiogram 3 в одном процессе. Webhook на `/tg/webhook`, REST API на `/api/*`.

> Этот файл нужен Hugging Face Spaces — frontmatter сверху обязателен.
> Если хостишь не на HF, frontmatter просто игнорируется.

## Локальная разработка

```bash
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                                  # отредактируй
alembic upgrade head
uvicorn app.main:app --reload --port 7860
```

Для локального dev-варианта без Postgres можно поставить SQLite:
```
DATABASE_URL=sqlite+aiosqlite:///./dev.db
```

## Тесты

```bash
pytest
```

## Миграции

```bash
alembic revision -m "description" --autogenerate
alembic upgrade head
```

## Переменные окружения

Смотри `.env.example`. Ключевые:

- `BOT_TOKEN` — из @BotFather
- `TG_WEBHOOK_SECRET` — `openssl rand -hex 32`
- `MINI_APP_URL` — куда вести с кнопки `/start`
- `PUBLIC_BASE_URL` — публичный HTTPS URL бэка для авторегистрации webhook
- `DATABASE_URL` — Neon connection string
- `WHITELIST_TG_IDS` / `WHITELIST_NAMES` — 6 пар через запятую, в одинаковом порядке
- `CORS_ORIGINS` — домен фронта (Cloudflare Pages)
