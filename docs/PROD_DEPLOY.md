# Прод SemiTaskBot: Neon + Cloudflare + Amvera

Итоговая схема (Amvera — только как хостинг контейнера с API; фронт и медиа на
Cloudflare, данные в Neon):

```
Telegram Mini App
      │ initData
      ▼
Cloudflare Pages ── статика (React/Vite) ── https://semitaskbot.pages.dev
      │ HTTPS, /api/*  (VITE_API_BASE вшит в бандл)
      ▼
Amvera, проект meetup-planner ── FastAPI + APScheduler (Docker, порт 7860)
      │ asyncpg + SSL
      ├──► Neon Postgres (eu-central-1)
      └──► Cloudflare R2 (медиа, S3 API)
```

## Что где живёт

| Что | Адрес / проект | Статус |
| --- | --- | --- |
| Фронт | Pages `semitaskbot` → https://semitaskbot.pages.dev | ✅ задеплоен, `VITE_API_BASE` вшит |
| API | Amvera `meetup-planner` → https://meetup-planner-youmakemefry.waw0.amvera.tech | ✅ код на `main`, `/healthz` 200 |
| Бот | @SemiTaskBot | ✅ вебхук перепривязан на Amvera, `pending=0` |
| База | Neon, ветка production | ✅ `alembic head 0031_hr_achievements` |
| Тестовая база | Neon `semitask_test` | ✅ интеграционный прогон зелёный |
| Mini App | BotFather | ⛔ не создан (`has_main_web_app: false`) |

Проект `semitaskbot` на Amvera **не использовать**: контейнер в нём живой (uvicorn
на 7860, миграции и планировщик работают), но публичный домен отдаёт 503 на всех
путях — это состояние на стороне платформы (домен `active=false`, пересоздать его
MCP не даёт: «Default domain already exist!»). Рабочая площадка — `meetup-planner`,
туда и уехал код.

## Грабли, из-за которых был 503

1. **Два имени конфига.** Amvera читает то `amvera.yml`, то `amvera.yaml`
   (MCP-шаблон отдаёт `.yaml`). В репозитории лежат оба, **идентичные**.
2. **`build.useCache`.** В шаблоне MCP он есть, но сборщик проекта ругался
   `Configuration error … unknown fields: useCache` и работал на дефолтах —
   то есть без `run.containerPort`. В итоге сервис доступа слушал 80, а uvicorn
   слушал 7860 → домен 503 при живом контейнере. Поле убрано из обоих файлов.
3. **Порт.** `run.containerPort: 7860` обязан совпадать с `ENV PORT` в
   `backend/Dockerfile`. Если меняете один — меняйте второй.

Проверка после деплоя: `/healthz` → 200, `/openapi.json` содержит `/api/kpi`
(признак, что приехал свежий код, а не прошлый релиз).

## Деплой

Бэкенд (одна команда, значения секретов не печатаются):

```bash
export AMVERA_SLUG=meetup-planner
export AMVERA_GIT=https://git.waw0.amvera.ru/youmakemefry/meetup-planner
python tools/deploy-amvera.py all      # env → mirror → push → build → status
```

`mirror` собирает чистую копию `backend/` (без `.env`, кешей и тестовых артефактов)
и пушит в git проекта Amvera; `env` берёт переменные из `backend/.env`; `build`
пересобирает и ждёт результата; `status` проверяет домен.

Фронт:

```bash
cd frontend
VITE_API_BASE=https://meetup-planner-youmakemefry.waw0.amvera.tech npm run build
rm -f dist/assets/*.map
npx wrangler@4 pages deploy dist --project-name=semitaskbot --branch=main
```

Без `VITE_API_BASE` бандл стучится в `/api` на самом Pages, где API нет: страница
откроется, данных не будет.

## Вебхук бота

```bash
cd backend && python - <<'PY'
import json, urllib.request, pathlib
env = dict(l.split("=", 1) for l in pathlib.Path(".env").read_text(encoding="utf-8").splitlines() if "=" in l and not l.startswith("#"))
base = env["PUBLIC_BASE_URL"].rstrip("/")
body = json.dumps({"url": f"{base}/tg/webhook", "secret_token": env["TG_WEBHOOK_SECRET"],
                   "allowed_updates": ["message", "callback_query", "poll_answer", "message_reaction"],
                   "drop_pending_updates": True}).encode()
print(json.load(urllib.request.urlopen(urllib.request.Request(
    f"https://api.telegram.org/bot{env['BOT_TOKEN']}/setWebhook", data=body,
    headers={"Content-Type": "application/json"}), timeout=30)))
PY
```

`getWebhookInfo` должен показать новый `url`, `pending_update_count: 0` и пустой
`last_error_message`.

## Mini App в BotFather (ещё не создан)

`getMe` у `@SemiTaskBot` отдаёт `has_main_web_app: false`. Порядок:

1. `/newapp` → выбрать `@SemiTaskBot` → название `SemiTaskBot` → описание →
   картинка 640×360 (или `/empty`) → **URL** → короткое имя `semitask`
   (ссылка станет `t.me/SemiTaskBot/semitask`).
2. `/mybots` → `@SemiTaskBot` → **Bot Settings → Configure Mini App → Enable
   Mini App** → тот же URL (кнопка запуска в профиле бота).
3. `/setmenubutton` → `@SemiTaskBot` → URL → текст кнопки, например
   `Открыть смену` (кнопка меню в чате; настраивается независимо от п.2).
4. Поменять ссылку позже: снова `/setmenubutton` или `/myapps` → приложение →
   Edit. Через Bot API — `setChatMenuButton`.

Подставлять нужно **`https://semitaskbot.pages.dev`** (публичный HTTPS фронта).
`*.amvera.tech` — это API, в BotFather его не вставляют: Telegram откроет JSON,
а не мини-апп.

## Почему API не на Cloudflare

FastAPI построен на async SQLAlchemy (нужен `greenlet`) — в Python Workers
(Pyodide) async-ORM не работает, а лимит Free (10 мс CPU) не вмещает
pydantic-валидацию. Containers требуют Workers Paid ($5/мес). Пока выбран
Amvera как рабочая площадка; если понадобится уйти — в репозитории лежит готовый
конфиг контейнера `deploy/cloudflare/` и инструкция в `docs/CLOUDFLARE_DEPLOY.md`.
