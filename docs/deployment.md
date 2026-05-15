# Деплой Meetup Planner — без банковской карты, из РФ

**Стек хостинга:** Hugging Face Spaces (бэк) + Neon (Postgres) + Cloudflare Pages (фронт).

Все три сервиса:
- регистрируются по email,
- **карту не просят**,
- работают из РФ (HF + Neon — напрямую; Pages — через VPN на момент регистрации, потом сам Pages работает без VPN).

Время на полный деплой: ~40-60 минут, если всё делать первый раз.

---

## 0. Что должно быть готово до старта

- [ ] Установлен **git** (`git --version` в терминале должно работать).
- [ ] Аккаунт на **GitHub** (бесплатный).
- [ ] Бот в **@BotFather**, есть `BOT_TOKEN`.
- [ ] Папка `C:\Users\fa1nt\meetup-planner\` со всем кодом (она уже создана).

Если бота ещё нет:
1. В Telegram открой [@BotFather](https://t.me/BotFather).
2. `/newbot` → введи имя (например `Meetup Planner`) → введи username (например `meetup_sixers_bot`).
3. Скопируй `BOT_TOKEN` (выглядит как `7123456789:AAH...`). Сохрани его в блокнот — понадобится дальше.

---

## 1. Залить код на GitHub

> **Зачем:** HF Spaces и Cloudflare Pages умеют автодеплой из GitHub. Без этого пришлось бы загружать файлы вручную каждый раз.

1. Открой <https://github.com/new>, создай **приватный** репозиторий с именем `meetup-planner`.
2. **Не** ставь галочки «Add README», «Add .gitignore» — у нас уже свои.
3. Открой PowerShell в папке проекта и выполни:

```powershell
cd C:\Users\fa1nt\meetup-planner
git init
git add .
git commit -m "initial: meetup planner skeleton"
git branch -M main
git remote add origin https://github.com/<твой_username>/meetup-planner.git
git push -u origin main
```

> Если git попросит логин-пароль и не пускает: на github.com → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token (galочка `repo`). Используй этот токен вместо пароля.

---

## 2. Создать БД на Neon

> **Зачем:** Neon — managed Postgres. Бесплатный тариф 0.5 GB, без карты, не спит навсегда (только cold-start ~1 сек). Регион Frankfurt — оптимально для бэка.

1. Зайди на <https://neon.tech>, **Sign up with GitHub**.
2. После регистрации создаётся первый проект — назови его `meetup-planner`, регион **Frankfurt (eu-central-1)**, Postgres 16.
3. Когда проект создан, на главной странице видна вкладка **Connection Details**.
4. В выпадающем списке выбери **Pooled connection** (это важно — обычное соединение быстро упрётся в лимит).
5. Скопируй строку — выглядит как:
   ```
   postgresql://meetup_owner:abc123XYZ@ep-cool-name-pooler.eu-central-1.aws.neon.tech/meetup?sslmode=require
   ```
6. Сохрани в блокнот как `DATABASE_URL`.

---

## 3. Создать Hugging Face Space (бэк)

> **Зачем:** HF Spaces — бесплатный Docker-хостинг, без карты, выдаёт HTTPS-домен `*.hf.space`, работает из РФ. Telegram нормально шлёт вебхуки на HF.

### 3.1. Регистрация

1. <https://huggingface.co/join> → регистрация по email (можно тоже через GitHub).
2. Подтверди email.

### 3.2. Создать Space

1. <https://huggingface.co/new-space>
2. **Owner:** твой ник.
3. **Space name:** `meetup-planner-backend` (это станет URL: `https://<ник>-meetup-planner-backend.hf.space`).
4. **License:** MIT.
5. **Space SDK:** выбери **Docker** → **Blank**.
6. **Hardware:** CPU basic (free).
7. **Visibility:** **Public** (на бесплатном — только public).
   > Безопасность: код публичный, секреты живут в Space Secrets — они **не** видны.
8. **Create Space.**

### 3.3. Положить код в Space

HF Space — это git-репозиторий. У нас бэк лежит во вложенной папке `backend/`, а HF ждёт Dockerfile в корне Space-репо. Поэтому **толкаем только содержимое `backend/`**:

```powershell
# создай отдельную папку рядом, чтобы не путаться
cd C:\Users\fa1nt
git clone https://huggingface.co/spaces/<твой_ник>/meetup-planner-backend hf-space
cd hf-space

# скопируй содержимое backend/ в корень hf-space
xcopy /E /I /Y C:\Users\fa1nt\meetup-planner\backend\* .

git add .
git commit -m "initial backend"
git push
```

> Если `git push` просит логин — username это твой HF-ник, password это **HF Access Token**: <https://huggingface.co/settings/tokens> → New token → Type **Write**.

После push HF начнёт собирать Docker — открой свой Space на сайте, вкладка **Logs** → жди пока появится `Build successful`. Первый раз — 5-10 минут.

### 3.4. Прописать секреты

На странице Space → **Settings** → раздел **Variables and secrets** → **New secret**.

Создай по одному (нажимай **Save** после каждого):

| Имя | Значение |
|---|---|
| `BOT_TOKEN` | токен из BotFather |
| `TG_WEBHOOK_SECRET` | сгенерируй случайную строку: в PowerShell `[guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")` |
| `DATABASE_URL` | строка от Neon из шага 2 |
| `WHITELIST_TG_IDS` | пока поставь свой ID (узнаешь его на шаге 6); временно `0` |
| `WHITELIST_NAMES` | `Дмитрий Menar,Сергей Neo,Дмитрий Повар,Никита,Дмитрий-JDM,Русланище` |
| `MINI_APP_URL` | заполнишь на шаге 5 — пока поставь `https://example.com` |
| `PUBLIC_BASE_URL` | `https://<твой_ник>-meetup-planner-backend.hf.space` (точно с `https://` и без `/` в конце) |
| `CORS_ORIGINS` | заполнишь на шаге 5 — пока `*` |

После каждого изменения секрета **Space перезапускается автоматически** (~30 сек).

### 3.5. Проверка

В браузере открой:
```
https://<твой_ник>-meetup-planner-backend.hf.space/healthz
```
Должно отдаться `{"status":"ok"}`.

В **Logs** Space-а должна быть строка `webhook.set`. Если её нет, и есть `webhook.set_failed` — проверь `PUBLIC_BASE_URL` (без `/` в конце!).

---

## 4. Узнать свой Telegram ID

1. В Telegram открой созданного бота, нажми **Start**.
2. Отправь ему `/whoami`.
3. Бот ответит `Твой Telegram ID: 123456789`.
4. Возвращайся в HF Settings → Variables and secrets → отредактируй `WHITELIST_TG_IDS`, поставь свой ID на первом месте: `123456789,0,0,0,0,0` (нули заменишь когда друзья пришлют свои).
5. Space перезапустится. После перезапуска ты появишься в БД (seed подцепит новый ID).

---

## 5. Развернуть фронт на Cloudflare Pages

### 5.1. Регистрация

1. <https://dash.cloudflare.com/sign-up> — может потребоваться VPN на момент регистрации (после регистрации сам Pages-домен `*.pages.dev` доступен из РФ без VPN, его не блокируют).
2. После входа: **Workers & Pages** в левом меню.

### 5.2. Создать Pages проект

1. **Create application** → вкладка **Pages** → **Connect to Git** → авторизуйся в GitHub → выбери репо `meetup-planner`.
2. **Production branch:** `main`.
3. **Framework preset:** `Vite`.
4. **Build command:** `npm install && npm run build`
5. **Build output directory:** `dist`
6. **Root directory (advanced):** `frontend`
7. **Environment variables (build):**
   - `VITE_API_BASE` = `https://<твой_ник>-meetup-planner-backend.hf.space`
8. **Save and Deploy.**

Жди ~2 минуты. Получишь домен типа `https://meetup-planner.pages.dev`.

### 5.3. Связать фронт и бэк

Возвращайся в HF Space → Settings → Variables and secrets:
- `MINI_APP_URL` = `https://meetup-planner.pages.dev`
- `CORS_ORIGINS` = `https://meetup-planner.pages.dev`

Space перезапускается, бот теперь зовёт правильный URL.

### 5.4. Подключить Mini App к боту

1. В Telegram открой [@BotFather](https://t.me/BotFather).
2. `/mybots` → выбери своего → **Bot Settings** → **Configure Mini App** → **Enable Mini App**.
3. **Edit Mini App URL** → вставь `https://meetup-planner.pages.dev`.
4. Возвращайся к боту в Telegram.

---

## 6. Сбор Telegram ID шестёрки

1. Скинь друзьям ссылку на бота.
2. Пусть каждый напишет `/start` и затем `/whoami` — пришлют тебе скрин с ID.
3. Собери все 6 ID **в том же порядке**, что имена в `WHITELIST_NAMES`.
4. На HF Space → Settings → Variables and secrets → отредактируй `WHITELIST_TG_IDS`:
   ```
   123456789,234567890,345678901,456789012,567890123,678901234
   ```
5. Space перезапустится, seed добавит/обновит всех в БД.

---

## 7. Smoke-test (финальная проверка)

1. В Telegram → бот → `/start`.
2. Видишь сообщение «Привет! Это планер встреч…» с кнопкой **📅 Открыть планер**.
3. Жми кнопку — открывается Mini App.
4. На экране: «Привет, {твоё имя}» + 14-дневная лента + 6 строк с аватарками.
5. Тапни на пустую ячейку в **своей** строке (это где твой цвет) → появилась зелёная «пилюля» (свободен).
6. Тапни на пилюлю → снизу выезжает редактор → нажми **Занят** → пилюля стала красной.
7. Закрой Mini App, открой заново → состояние сохранилось.

Если всё работает — **деплой успешен**.

---

## 8. Что если что-то не работает

### Бот не отвечает на `/start`
- Открой HF Space → **Logs** → ищи строку `webhook.set` или `webhook.set_failed`.
- Если `set_failed` — `PUBLIC_BASE_URL` неправильный. Проверь, что в нём есть `https://` и нет `/` в конце.
- Если `webhook.set` есть, но бот молчит — проверь, что `BOT_TOKEN` верный.

### Mini App открылась, но пишет «Тебя нет в списке шестёрки»
- Твой Telegram ID не попал в `WHITELIST_TG_IDS`. Проверь его через `/whoami` боту, добавь в HF Secrets, дождись перезапуска Space.

### Mini App открылась, но «Загрузка…» висит вечно
- Открой DevTools в Telegram Desktop (правый клик в Mini App → Inspect) → вкладка Network → смотри ошибки.
- Скорее всего CORS — проверь `CORS_ORIGINS` в HF, должен совпадать с доменом Pages.

### `webhook.set_failed` с ошибкой 400/404
- В Telegram это значит, что URL вебхука недостижим. Открой `https://<...>.hf.space/healthz` в браузере — должен вернуть `{"status":"ok"}`. Если 404 — Space ещё не собрался; смотри Logs.

### HF Space «Sleeping»
- Бесплатные Spaces засыпают **только если 48 часов не было трафика**. Telegram-вебхук считается трафиком — пока кто-то пишет боту, Space живой. Если все ушли в отпуск на 2+ дня, при следующем запросе будет ~30 сек cold-start, после чего работает нормально.

### Изменился код — как редеплоить?
- **Бэк:** `cd C:\Users\fa1nt\hf-space`, скопировать новый `backend/*` поверх, `git add . && git commit -m "..." && git push`. HF сам пересоберёт.
- **Фронт:** `git push` в основной `meetup-planner` репо на GitHub. Cloudflare Pages сам пересоберёт.

---

## 9. Что дальше (итерация 2)

Когда базовый сценарий обкатан:
- Drag-resize пилюль (растягивать на несколько дней мышью).
- Pinch-zoom (день → неделя → месяц → год).
- Авто-подбор лучшего времени встречи.
- «Лох дня» с кулдауном 12 ч + статистика.
- Поллы с предложенными датами в групповой чат.
- Синхронизация фоток профиля.

Все таблицы в БД для этого уже созданы — миграций «всё сломали» не будет.
