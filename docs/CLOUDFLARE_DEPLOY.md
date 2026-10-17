# Прод на Neon + Cloudflare (Amvera не используется)

Целевая схема:

```
Telegram Mini App
      │ initData
      ▼
Cloudflare Pages  ── статика фронта (React/Vite) ── semitaskbot.pages.dev
      │ HTTPS, /api/*
      ▼
Cloudflare Worker (semitask-api) ── прокси ──► Container (FastAPI + APScheduler)
                                                      │ asyncpg + SSL
                                                      ▼
                                            Neon Postgres (eu-central-1)
```

Медиа (аватары/фото) уже живут в Cloudflare R2 (`R2_*` в `backend/.env`).

## Что уже сделано

| Шаг | Статус |
| --- | --- |
| Neon Postgres | ✅ боевая база на `alembic head 0031_hr_achievements`, 2 пользователя |
| Тестовая база Neon `semitask_test` | ✅ есть, миграции накатаны, интеграционный тест зелёный |
| Фронтенд на Cloudflare Pages | ✅ проект `semitaskbot`, прод: https://semitaskbot.pages.dev |
| Бэкенд на Cloudflare | ⛔ заблокировано тарифом — см. ниже |
| Вебхук бота | ⚠️ всё ещё указывает на Amvera: `https://semitaskbot-youmakemefry.waw0.amvera.tech/tg/webhook` |
| Mini App в BotFather | ⛔ не создан (`has_main_web_app: false`) |

Деплой фронта (проверено, работает):

```bash
cd frontend
npm run build
rm -f dist/assets/*.map          # source maps наружу не отдаём
CLOUDFLARE_API_TOKEN=… CLOUDFLARE_ACCOUNT_ID=… \
  npx wrangler@4 pages deploy dist --project-name=semitaskbot --branch=main
```

## Почему бэкенд не на бесплатном Cloudflare

FastAPI-приложение — 47k строк, 272 ручки, **async SQLAlchemy + asyncpg**. Варианты Cloudflare:

1. **Python Workers (Pyodide).** FastAPI там работает, но async-ORM — нет:
   в Pyodide нет `greenlet`, а на нём держится весь async-SQLAlchemy.
   Плюс лимит Free — 10 мс CPU на запрос: pydantic-валидация и сериализация
   ответа в него не укладываются даже без базы.
2. **Pages Functions.** Это тот же Workers runtime, только в JS/TS: Python ASGI
   туда не ставится вообще.
3. **Containers.** Запускают существующий `backend/Dockerfile` без переписывания
   кода. Требуют **Workers Paid, $5/мес** — на текущем аккаунте API отвечает
   `401 … requires the Workers Paid plan`.

Поэтому в репозитории лежит готовый конфиг контейнера (`deploy/cloudflare/`), а
не полурабочая портация. После включения плана деплой — одна команда.

## Деплой бэкенда (после включения Workers Paid)

```bash
cd meetup-planner-main/backend
npx wrangler@4 login          # либо экспортировать CLOUDFLARE_API_TOKEN

# 1) секреты — по одному, значения берутся из backend/.env (в git его нет)
npx wrangler@4 secret put BOT_TOKEN       -c ../deploy/cloudflare/wrangler.jsonc
npx wrangler@4 secret put DATABASE_URL    -c ../deploy/cloudflare/wrangler.jsonc
npx wrangler@4 secret put TG_WEBHOOK_SECRET -c ../deploy/cloudflare/wrangler.jsonc
npx wrangler@4 secret put ADMIN_TG_IDS    -c ../deploy/cloudflare/wrangler.jsonc
npx wrangler@4 secret put GROUP_CHAT_ID   -c ../deploy/cloudflare/wrangler.jsonc

# 2) сборка образа и деплой
npx wrangler@4 deploy -c ../deploy/cloudflare/wrangler.jsonc
```

`wrangler` печатает выданный адрес `https://semitask-api.<account>.workers.dev`.
Его нужно прописать в трёх местах:

1. `vars.PUBLIC_BASE_URL` в `deploy/cloudflare/wrangler.jsonc` → повторный деплой;
2. `PUBLIC_BASE_URL` и `MINI_APP_URL` в `backend/.env`;
3. `VITE_API_BASE` при сборке фронта (иначе мини-апп стучится в `/api` на
   Pages, где API нет):

```bash
cd frontend
VITE_API_BASE=https://semitask-api.<account>.workers.dev npm run build
npx wrangler@4 pages deploy dist --project-name=semitaskbot --branch=main
```

Миграции контейнер выполняет сам при старте: `CMD` в `backend/Dockerfile` —
`alembic upgrade head && uvicorn …`. Секреты в образ не попадают: они приходят
переменными окружения контейнера.

Проверка после деплоя:

```bash
curl -s https://semitask-api.<account>.workers.dev/healthz
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST https://semitask-api.<account>.workers.dev/tg/webhook   # 403/401, не 404
```

## Вебхук бота

Старый вебхук смотрит на Amvera. Перепривязать (значения — из `backend/.env`):

```bash
python - <<'PY'
import json, os, urllib.request
token = os.environ["BOT_TOKEN"]
secret = os.environ["TG_WEBHOOK_SECRET"]
base = os.environ["PUBLIC_BASE_URL"].rstrip("/")
url = f"https://api.telegram.org/bot{token}/setWebhook"
body = json.dumps({
    "url": f"{base}/tg/webhook",
    "secret_token": secret,
    "allowed_updates": ["message", "callback_query", "poll_answer", "message_reaction"],
    "drop_pending_updates": True,
}).encode()
req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(req, timeout=30)))
PY
```

`getWebhookInfo` после этого должен показать новый `url`, а
`pending_update_count` — 0.

## Mini App в BotFather (с нуля)

`getMe` у `@SemiTaskBot` отдаёт `has_main_web_app: false` — приложение ещё не
создано. Порядок:

1. **Создать приложение.** В чате с `@BotFather` отправить `/newapp` → выбрать
   `@SemiTaskBot` → название (`SemiTaskBot`) → описание (короткое, для профиля
   бота) → картинку 640×360 (или `/empty`, если картинки пока нет) → **URL** →
   короткое имя (`semitask`, оно станет адресом `t.me/SemiTaskBot/semitask`).
2. **Включить кнопку в профиле бота.** `/mybots` → `@SemiTaskBot` →
   **Bot Settings → Configure Mini App → Enable Mini App** → тот же URL.
3. **Кнопка меню в чате.** `/setmenubutton` → `@SemiTaskBot` → URL → текст
   кнопки, например `Открыть смену`. Это отдельная настройка от п.2; можно
   сделать и только её.
4. **Поменять ссылку позже.** Снова `/setmenubutton` (или `/myapps` →
   приложение → Edit). Через Bot API — `setChatMenuButton`.

Какой URL подставлять: **только `https://semitaskbot.pages.dev`** — публичный
HTTPS-адрес фронта. `*.workers.dev` — это API, его в BotFather не вставляем.
Пока `VITE_API_BASE` не проставлен и бэкенд не поднят, приложение откроется, но
данные не загрузятся: это ожидаемо для промежуточного состояния.

Требования Telegram, о которых легко забыть:

- HTTPS с валидным сертификатом (pages.dev подходит), никакого basic-auth;
- проверять `initData` **на сервере** (у нас это `app/auth/initdata.py`), не
  доверять `initDataUnsafe`;
- `auth_date` не старше суток — иначе отклонять.

## Откат

- Фронт: `wrangler pages deployment list --project-name semitaskbot`, затем
  `wrangler pages deployment rollback <id> --project-name semitaskbot`.
- Бэкенд: `wrangler rollback` в каталоге с конфигом.
- База: миграции аддитивные; откат — `alembic downgrade -1` на конкретной ревизии,
  но перед этим снять дамп (`python tools/backup-db.py dump`).
