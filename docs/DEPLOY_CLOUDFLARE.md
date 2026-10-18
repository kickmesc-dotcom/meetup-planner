# Деплой: Cloudflare + Neon (Amvera больше не используется)

Целевая схема — вся инфраструктура Cloudflare, база в Neon:

```
Telegram Mini App
      │ initData
      ▼
Cloudflare Pages ── статика React/Vite ── https://semitaskbot.pages.dev
      │ HTTPS, VITE_API_BASE
      ▼
Cloudflare Worker (semitask-api) ──► Container: FastAPI + APScheduler
      │ asyncpg + SSL
      ├──► Neon Postgres
      └──► R2 (медиа)
```

Amvera из проекта убрана: конфиги `backend/amvera.y*ml` и диагностика удалены,
`docs/PROD_DEPLOY.md` заменён этим файлом.

## 1. Доступ к Cloudflare

Нужен один из двух вариантов:

```bash
cd meetup-planner-main
npx wrangler@4 login          # OAuth, браузер
# или
export CLOUDFLARE_API_TOKEN=…  # PAT
```

Минимальные права PAT: `Pages:Edit`, `Workers Scripts:Edit`, `Workers R2
Storage:Edit` (если нужны бакеты), `Account Settings:Read`, `User Details:Read`.
Токен из `PROMT/semiCREDS.txt` от 2026-10-18 отвечает `Invalid API Token` —
его надо пересоздать.

## 2. Фронт (Pages)

```bash
cd frontend
npm run build
rm -f dist/assets/*.map
npx wrangler@4 pages deploy dist --project-name=semitaskbot --branch=main
```

`VITE_API_BASE` вшивается в бандл из `frontend/.env.production`. Значение
обязательно: без него фронт стучится в `/api` на самом Pages, где API нет.

## 3. API: важное ограничение

FastAPI-приложение — async SQLAlchemy + asyncpg + APScheduler + aiogram.

* **Python Workers (Pyodide)** — FastAPI работает, но `greenlet` (на нём стоит
  async SQLAlchemy) недоступен; DB-слой не поедет. Переписать 47k строк ради
  смены рантайма — не тот обмен.
* **Pages Functions** — только JS/TS, Python ASGI туда не ставится.
* **Containers** — запускают существующий `backend/Dockerfile` без правок, но
  требуют план **Workers Paid ($5/мес)**. На Free API отвечает `401 … requires
  the Workers Paid plan`.

Поэтому в репозитории лежит готовый контейнерный конфиг
(`deploy/cloudflare/wrangler.jsonc` + `worker.js`), а не полурабочая портация.

### Если план Workers Paid есть

```bash
cd deploy/cloudflare
npm install
npx wrangler@4 deploy -c wrangler.jsonc

# секреты (значения — из backend/.env, в git их нет)
npx wrangler@4 secret put BOT_TOKEN       -c wrangler.jsonc
npx wrangler@4 secret put DATABASE_URL    -c wrangler.jsonc
npx wrangler@4 secret put TG_WEBHOOK_SECRET -c wrangler.jsonc
npx wrangler@4 secret put MINI_APP_URL    -c wrangler.jsonc
npx wrangler@4 secret put GROUP_CHAT_ID   -c wrangler.jsonc
```

После первого деплоя подставить выданный `*.workers.dev` в:

* `deploy/cloudflare/wrangler.jsonc` → `vars.PUBLIC_BASE_URL`;
* `frontend/.env.production` → `VITE_API_BASE`;
* вебхук бота (`/tg/webhook`, см. ниже).

### Если плана нет

Честный выбор один из двух:

1. подключить Workers Paid — тогда деплой занимает минуты и ничего не надо
   переписывать;
2. портировать API на Worker (TypeScript + `@neondatabase/serverless` по HTTP).
   Это не «переезд», а новый слой: Mini App дергает ~170 путей, бот и
   планировщик живут отдельно. Делать это надо поэтапно и с тестами на каждый
   перенесённый путь, а не одним коммитом.

## 4. База

```bash
cd backend
python -m alembic upgrade head     # DSN из backend/.env (DATABASE_URL)
```

Миграции аддитивные; head в коде и на Neon сверяет тест
`tests/test_db_alembic_head.py`.

## 5. Вебхук бота

```bash
cd backend && python - <<'PY'
import json, urllib.request, pathlib
env = dict(l.split("=", 1) for l in pathlib.Path(".env").read_text(encoding="utf-8").splitlines() if "=" in l and not l.startswith("#"))
body = json.dumps({"url": f"{env['PUBLIC_BASE_URL'].rstrip('/')}/tg/webhook",
                   "secret_token": env["TG_WEBHOOK_SECRET"],
                   "allowed_updates": ["message", "callback_query", "poll_answer", "message_reaction"],
                   "drop_pending_updates": True}).encode()
print(json.load(urllib.request.urlopen(urllib.request.Request(
    f"https://api.telegram.org/bot{env['BOT_TOKEN']}/setWebhook", data=body,
    headers={"Content-Type": "application/json"}), timeout=30)))
PY
```

`getWebhookInfo`: `pending_update_count: 0`, `last_error_message` пустой.

## 6. Проверка после деплоя

* `/healthz` → 200;
* `/openapi.json` содержит `/api/admin/dashboard` (признак свежего кода);
* Mini App: вход новым Telegram-аккаунтом (не из шестёрки) открывает задачи;
* `/api/admin/dashboard` без прав → 403;
* в бандле Pages ровно один `VITE_API_BASE`, карта исходников наружу не отдаётся.
