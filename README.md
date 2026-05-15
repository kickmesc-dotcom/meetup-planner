# Meetup Planner

Telegram Mini App для координации встреч в группе на 6 человек.

## Стек
- **Backend:** Python 3.12, FastAPI + aiogram 3, SQLAlchemy 2.0 async, PostgreSQL (Neon), Alembic.
- **Frontend:** React 18 + TypeScript + Vite, Telegram WebApp SDK, Tailwind, TanStack Query, Zustand.
- **Хостинг:** Fly.io (backend, регион `fra`) + Neon (DB) + Cloudflare Pages (frontend).

## Структура

```
backend/   FastAPI + aiogram бот в одном процессе (вебхук на /tg/webhook)
frontend/  Vite React TS Mini App
docs/      deployment.md, заметки
```

## Локальный запуск (dev)

См. `backend/README.md` и `frontend/README.md`.

## Деплой

См. `docs/deployment.md`.
