# Деплой: Cloudflare + Neon (Amvera больше не используется)

Действующая схема — как у оригинального meetup-planner: Cloudflare на краю,
бесплатный docker-хост для FastAPI, база в Neon.

```
Telegram Mini App
      │ initData
      ▼
Cloudflare Pages ── статика React/Vite ── https://semitaskbot.pages.dev
      │ HTTPS, VITE_API_BASE
      ▼
Hugging Face Space (docker, cpu-basic, бесплатно) ── FastAPI + APScheduler
      │ asyncpg + SSL
      ├──► Neon Postgres
      └──► R2 (медиа)
```

Почему API не на Cloudflare: Containers доступны только на плане Workers Paid,
а Python Workers (Pyodide) не тянут async SQLAlchemy — там нет `greenlet`, на
котором стоит вся ORM. Поэтому Python-хост остаётся внешним и бесплатным, ровно
как в оригинале; Cloudflare отвечает за фронт, медиа и (при необходимости)
прокси до `api.telegram.org`.

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

## 3. API на Hugging Face Space

Space: `fryesw/meetup-planner-backend` → https://fryesw-meetup-planner-backend.hf.space
(cpu-basic, бесплатно; в `backend/README.md` уже есть HF-frontmatter, а
`backend/Dockerfile` слушает `$PORT=7860` и сам гоняет `alembic upgrade head`).

Всё делает один скрипт:

```bash
cd meetup-planner-main
backend/.venv/Scripts/python.exe tools/deploy-hf.py env      # секреты из backend/.env + DPAPI
backend/.venv/Scripts/python.exe tools/deploy-hf.py mirror   # код → репозиторий Space
backend/.venv/Scripts/python.exe tools/deploy-hf.py wait     # дождаться RUNNING и свежего кода
backend/.venv/Scripts/python.exe tools/deploy-hf.py status   # что на хосте сейчас
# или одной командой: all
```

`env` берёт `BOT_TOKEN`, `TG_WEBHOOK_SECRET`, `DATABASE_URL`, `MINI_APP_URL`,
`ADMIN_TG_IDS`, `GROUP_CHAT_ID`, `WHITELIST_*`, `CORS_ORIGINS`, `SCHEDULER_TZ`.
Значения никогда не печатаются. `PUBLIC_BASE_URL` всегда проставляется равным
адресу Space — от него зависят CORS и вебхук.

Если HF недоступен из Telegram-сети, хост можно переключить на другой
бесплатный docker-хостинг: код уезжает тем же `mirror` (Dockerfile уже
портативный), меняется только адрес в `frontend/.env.production` и вебхук.

### Альтернатива: всё-таки Cloudflare

* **Workers Paid ($5/мес)** — `deploy/cloudflare/wrangler.jsonc` + `worker.js`
  запускают тот же `backend/Dockerfile` в Container без переписывания кода.
* **Порт API на Worker (TS + `@neondatabase/serverless`)** — бесплатно и без
  внешних хостов, но это новый слой: Mini App дергает ~170 путей, плюс бот и
  планировщик. Делать поэтапно и с тестами на каждый путь.

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
