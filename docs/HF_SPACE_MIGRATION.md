# Hugging Face Space: на каком аккаунте живёт и как поднять на новом

Дата проверки: **31.10.2026**. Всё ниже — результат запросов к API HF и Telegram,
а не память.

---

## 1. Что есть сейчас (факты)

| Вопрос | Ответ |
|---|---|
| Аккаунт HF | **`fryesw`** (профиль `eswfry`, e-mail `fry-06@mail.ru`, план бесплатный, `isPro=false`) |
| Пространство | `fryesw/meetup-planner-backend` — публичное, Docker, `cpu-basic`, статус **RUNNING** |
| Адрес | <https://fryesw-meetup-planner-backend.hf.space> (`/healthz` → 200) |
| Что внутри | **тот же код и та же база, что в проде**: fingerprint `8b5d036f0536`, миграции `0063_translation_cache`, `db.host = ep-dry-cherry-….neon.tech` |
| Токен в хранилище машины | запись `HF_TOKEN` (write, имя «mylaptopaccess») — им пользовались `tools/deploy-hf.py` и `tools/hf-logs.py` |
| Владелец Telegram-бота | Telegram **не отдаёт** владельца бота через API. Известно только имя: `@SemiTaskBot` (id `8865471682`) — его токен лежит в `PROMT/semiCREDS.txt` и указывает вебхуком на Amvera |

Отсюда два вывода, которые важны для решения:

1. **HF — не «старый бот», а третья копия боевого кода**, смотрящая в ту же базу.
   Она не получает апдейтов (вебхук @SemiTaskBot смотрит на Amvera), но при
   каждом рестарте пытается поставить вебхук себе — это гонка, которая уже
   случалась. Держать её живой смысла нет.
2. **Какой именно бот прописан в секретах этого Space, снаружи не видно** —
   значения секретов HF не отдаёт даже владельцу через API. Проверить можно
   только в UI: Space → Settings → Variables and secrets.

---

## 2. Что вообще где должно работать (целевая схема)

| Что | Где | Зачем |
|---|---|---|
| API + бот **@SemiTaskBot** | Amvera, проект `meetup-planner` (Warsaw-0) | единственный боевой контур, вебхук смотрит сюда |
| База | Amvera managed PostgreSQL (Warsaw-0) | рядом с API, бэкапы 7–10 дней (`INFRA_CHOICE.md`, §10) |
| Мини-апп | Cloudflare Pages `semitaskbot.pages.dev` | уже работает, бесплатно, не меняем |
| Старый бот **@gunghoguns_bot** | **отдельный** HF Space на **новом** аккаунте | только если действительно нужно поднять его снова |
| `semitask` (старый продукт) | Amvera, заморозить | 290 ₽/мес за контур без трафика |
| `semitaskbot` (дубль) | Amvera, оставить STOPPED | не поднимать |

**Главное правило:** один бот = один хост = один `DATABASE_URL`. Два хоста с
одним токеном воюют за вебхук (кто стартовал последним, тот и получает
апдейты), а два хоста с одной базой дублируют запись. Поэтому «поднять старый
бот рядом» = новый Space **+ своя база + свой домен**, а не переключение
вебхука.

---

## 3. Инструкция: Space на новом аккаунте

Нужен только доступ к новому аккаунту. Порядок такой.

### 3.1 Подготовка (владелец, 5 минут)

1. Зарегистрироваться на <https://huggingface.co/join> (можно через GitHub).
2. <https://huggingface.co/settings/tokens> → **New token** → тип **Write** →
   имя `semitask-deploy`. Скопировать значение **один раз**.
3. Положить токен в локальное хранилище машины, **не в чат и не в git**:
   ```
   powershell -File secrets\Import-Secrets.ps1
   # имя: HF_TOKEN
   ```
   (скрипт кладёт значение в DPAPI-хранилище Windows; `tools/deploy-hf.py`
   читает его оттуда).
4. <https://huggingface.co/new-space> → имя `semitask-ghg` (или любое), SDK
   **Docker**, видимость **Public**, железо **CPU basic (free)**.

### 3.2 Секреты Space (Settings → Variables and secrets)

Их надо завести **до** первого старта, иначе контейнер поднимется и сразу
упадёт на отсутствии `BOT_TOKEN`.

| Переменная | Тип | Откуда взять |
|---|---|---|
| `BOT_TOKEN` | **secret** | токен того бота, которого поднимаем (BotFather) |
| `DATABASE_URL` | **secret** | **отдельная** база для этого контура, не боевая |
| `TG_WEBHOOK_SECRET` | **secret** | любая случайная строка; я сгенерирую |
| `PUBLIC_BASE_URL` | переменная | `https://<owner>-<space>.hf.space` |
| `MINI_APP_URL` | переменная | адрес мини-аппа этого бота |
| `CORS_ORIGINS` | переменная | тот же адрес мини-аппа |
| `SCHEDULER_TZ` | переменная | `Europe/Moscow` |
| `SCHEDULER_LEADER_DISABLED` | переменная | `true` — у отдельного контура свой планировщик, лидер-лиз ему не нужен |
| `GROUP_CHAT_ID` | переменная | **не задавать**, если чат не нужен (см. §5) |

Чего **нельзя** делать: копировать в новый Space `BOT_TOKEN` боевого бота или
`DATABASE_URL` боевой базы. Это и есть та ошибка, из-за которой сейчас живы три
копии одного контура.

### 3.3 Заливка кода

Проект берётся из переменной `HF_SPACE_REPO` (по умолчанию — текущий
`fryesw/meetup-planner-backend`), токен — из хранилища под именем `HF_TOKEN`:

```
export HF_SPACE_REPO=<owner>/<space>     # PowerShell: $env:HF_SPACE_REPO="…"
python tools/deploy-hf.py env            # секреты и переменные
python tools/deploy-hf.py mirror         # код
python tools/deploy-hf.py wait           # дождаться сборки
python tools/deploy-hf.py all            # то же одной командой
```

Если токен лежит под другим именем — положить его в окружение как `HF_TOKEN`
(значение не печатать).

### 3.4 Проверка

1. **Контейнер поднялся:**
   `curl https://<owner>-<space>.hf.space/healthz` → `{"status":"ok"}`
2. **Код тот, что ожидали:** `/api/meta` → `code.fingerprint` и
   `db.alembic_version` равны `alembic_head`.
3. **Вебхук смотрит на новый домен — и только он:**
   ```
   curl "https://api.telegram.org/bot<$BOT_TOKEN>/getWebhookInfo"
   ```
   `url` должен быть `https://<owner>-<space>.hf.space/tg/webhook`,
   `pending_update_count = 0`, `last_error_message` пустой.
4. **Боевой бот не пострадал:** та же команда его токеном → `url` всё ещё
   `meetup-planner-youmakemefry.waw0.amvera.tech`.

---

## 4. Что мне нужно от вас для этого

| Что | Формат | Зачем |
|---|---|---|
| HF-токен **нового** аккаунта (тип Write) | в `secrets/` через `Import-Secrets.ps1`, имя `HF_TOKEN` | заливать код и читать логи Space |
| Имя Space | `<owner>/<space>` | адрес для `deploy-hf.py` |
| `BOT_TOKEN` того бота, которого поднимаем | прямо в Space → Secrets (не в чат) | иначе Space не запустится |
| `DATABASE_URL` отдельной базы | прямо в Space → Secrets | свой контур, не боевой |
| Нужен ли этому боту мини-апп | да/нет + адрес | от него зависят `MINI_APP_URL` и кнопка меню |

Больше ничего не требуется: `TG_WEBHOOK_SECRET` я сгенерирую, домен известен
заранее, регион у HF один.

---

## 5. Если Space не нужен вообще (рекомендуемый вариант)

Старый бот не работает не из-за HF, а потому что его вебхук пуст и в очереди
6 апдейтов. Поднимать ради этого третий контур с отдельной базой — дорого
вниманием. Порядок «выключить аккуратно»:

1. Space → Settings → **Pause** (не Delete: данные и секреты останутся).
   Через API это `POST https://huggingface.co/api/spaces/<owner>/<space>/pause`
   с заголовком `Authorization: Bearer <HF_TOKEN>` — отдельной команды в
   `tools/deploy-hf.py` пока нет (добавить — пять строк, если понадобится
   регулярно).
2. Убедиться, что боевой бот работает: `/healthz` 200 и `getWebhookInfo` без
   ошибок.
3. Если через месяц не понадобился — удалить Space и отозвать токен
   <https://huggingface.co/settings/tokens>.

Пока Space просто **остановлен**, он не тратит ни квоту, ни деньги (бесплатный
`cpu-basic`), но и не мешает.

---

## 6. Про групповой чат (с 31.10.2026)

`GROUP_CHAT_ID` больше не обязателен: на старте контур делает один `getChat` и,
если Telegram отвечает `chat not found`, пишет `group_chat.disabled` и работает
без чата (см. `ACCOUNTS_AND_ROLES.md`, §3). Поэтому «пустой» `GROUP_CHAT_ID` —
штатная конфигурация, а не поломка. На боевом контуре именно так и произошло:
чат `-1003588632778` недоступен, приложение живёт.
