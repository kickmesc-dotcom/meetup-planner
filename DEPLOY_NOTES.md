# 🔑 Пуш монорепо в GitHub (обновлено 2026-09-29)

**Статус: работает.** Свежий PAT со scope `repo` действует **до 2026-12-28**
(лежит в `leltokens2.txt` и в DPAPI-хранилище `secrets/` как `GITHUB_PAT`).

## Как пушить (основной путь)

```bash
cd /c/Users/fa1nt/meetup-planner/meetup-planner-main
export GITHUB_PAT=$(powershell -File ../secrets/Get-Secret.ps1 GITHUB_PAT)
GIT_TERMINAL_PROMPT=0 git -c credential.helper= \
    -c credential.helper='!f() { echo username=x-access-token; echo password=$GITHUB_PAT; }; f' \
    push origin main
unset GITHUB_PAT
```

Ключевая деталь — **`-c credential.helper=`** (пустое значение сбрасывает
список helper'ов). Без него Git Credential Manager подставит свой сохранённый
аккаунт — и если это `youmakemefry-cmd` (без прав на репозиторий), пуш упадёт
с `403 Permission denied`, хотя аутентификация пройдёт. Проверить, кто там
лежит: `git credential-manager github list`.

## Запасной путь — без токена

В хранилище GCM лежит рабочий OAuth-credential аккаунта `kickmesc-dotcom`
с правами **admin** на репозиторий. Им можно пушить так:

```bash
creds=$(printf 'protocol=https\nhost=github.com\nusername=kickmesc-dotcom\n\n' \
        | GIT_TERMINAL_PROMPT=0 git credential fill 2>/dev/null)
export GH_U=$(echo "$creds" | sed -n 's/^username=//p')
export GH_P=$(echo "$creds" | sed -n 's/^password=//p')
GIT_TERMINAL_PROMPT=0 git -c credential.helper= \
    -c credential.helper='!f() { echo username=$GH_U; echo password=$GH_P; }; f' \
    push origin main
unset GH_U GH_P
```

Пуш — **fast-forward**, история не переписывается. Перед пушем фронт проверен
локально: `npm run typecheck` чист, `npm run build` проходит (остаются только
предзаписанные warnings про минификацию CSS и размер чанка >500 kB).

Предыстория: 29.09.2026 пуш сначала падал с 403 (GCM отдавал аккаунт без прав),
а PAT от 01.07.26 к тому моменту истёк и отвечал `Invalid username or token`.
Оба фактора устранены: новый PAT выпущен, рецепт с обходом GCM — выше.

## Проверка, что фронт доехал (CF собирает ~1–2 мин)

```bash
JS=$(curl -s https://meetup-planner1.pages.dev/ | grep -oE '/assets/index-[A-Za-z0-9_-]+\.js' | head -1)
curl -s "https://meetup-planner1.pages.dev$JS" | grep -c 'Себе дарить опыт'   # было 0 → должно стать 1
```

Актуальный маркер последней сборки (2026-09-29): бандл **`index-CeiO31Yj.js`**,
в нём есть `game.donate` (проверка возможностей сервера), «Сервер ещё не
обновился» и `/api/meta`.

Было закрыто в тот же день: фронт уехал вперёд бэкенда, и кнопка доната у
тортика получала 404. Теперь мини-апп сам спрашивает у бэкенда `/api/meta`,
какие ручки тот умеет, и вместо кнопки показывает строку «донат включится,
когда бэкенд пересоберётся»; админский экран игры на 404 отвечает «Сервер ещё
не обновился». То есть рассинхрон фронта и бэкенда больше не выглядит поломкой.

> Токен/PAT нужен только для github.com. HF Space ходит со своим `hf_`-токеном,
а git Amvera — по логину Amvera; один и тот же секрет нигде не переиспользуется.

### Amvera: сборка падала на базовом образе (2026-09-29, закрыто)

Гипотеза «конвейер не реагирует» была неверной: реагировал как часы, а падал
первый шаг Docker. Внутренний proxy Amvera `harbor.waw.amverum.com` отдавал
`stream error … INTERNAL_ERROR` на blob'ах `python:3.12-slim`. Лечение —
`FROM public.ecr.aws/docker/library/python:3.12-slim`, после чего сборка прошла.
Подробности и логи — в `docs/AMVERA_BUILD_DIAGNOSTIC.md` (шапка документа).

Если это повторится с другой библиотекой — смотреть не код, а `getBuildLogs`
через MCP: падение почти всегда видно в первых трёх строках.

## 🛠 Управление хостами из терминала (2026-09-29)

Всё лежит в `../tools/` (рядом с `meetup-planner-main`, не внутри монорепо —
эти скрипты про инфраструктуру, а не про приложение):

| Скрипт | Что делает |
|---|---|
| `tools/amvera-mcp.py` | CLI к MCP-серверу Amvera: `tools`, `call <tool> '<json>'`, `raw '<json>'`. 28 инструментов: сборка, логи, переменные, домены, файлы |
| `tools/switch-db.py` | `status` / `check <dsn>` / `switch <dsn>` / `webhook amvera\|hf` — переключатель базы, который реально работает |

Токен берётся из `secrets/Get-Secret.ps1 AMVERA_MCP_TOKEN` (или env
`AMVERA_MCP_TOKEN`). Типовые команды:

```bash
python tools/amvera-mcp.py call listProjects '{}'
python tools/amvera-mcp.py call getBuildLogs '{"serviceName":"meetup-planner","query":"*","start":"2026-09-29T00:00:00Z","end":"2026-09-29T23:59:59Z"}'
python tools/amvera-mcp.py call rebuildProject '{"slug":"meetup-planner"}'
```

⚠ Мелочь, о которой стоит знать: сервер Amvera требует присутствия всех
полей из схемы, даже объявленных необязательными (`isSecret`, `query`, `start`,
`end`). Клиент сам дозаполняет недостающие `null` и повторяет вызов.

`tools/switch-db.py` делает то, что не могли `meetup-switch/*.bat`: те меняли
URL вебхука (какой бэкенд обслуживает бота), а база живёт в `DATABASE_URL`
контейнера. Скрипт проверяет кандидата до переключения, меняет переменную
**у обоих хостов** (Amvera — через MCP, HF — через API секретов), перезапускает
их и подтверждает результат по `/api/meta`:

```bash
python tools/switch-db.py status          # что сейчас у обоих
python tools/switch-db.py check --list    # какие DSN вообще известны
python tools/switch-db.py check current   # проверка кандидата
python tools/switch-db.py switch dsn2     # переключить и подтвердить
python tools/switch-db.py webhook amvera  # то, что делали .bat
```

---

# ⚠️ Уточнение топологии фронта (2026-09-28): фронт — Cloudflare Pages, НЕ GitHub Pages

В инструкциях ниже встречается «GitHub Pages соберёт» — это **устаревшая
формулировка**. Реальный фронтенд живёт на **Cloudflare Pages**, проект
`meetup-planner1`, домен <https://meetup-planner1.pages.dev>; CF подключён к
репо `kickmesc-dotcom/meetup-planner` и пересобирает сам на push в `main`
(как и описано в `docs/deployment.md`). В самом репо GitHub Pages не создан
(`GET /repos/.../pages` → 404) и `.github/workflows` отсутствует.

Практическое следствие: пуш в `origin/main` из `meetup-planner-main` деплоит и
бэкенд-независимую часть — фронт пересоберётся CF в течение ~1–2 мин. Проверка,
что доехало: в живом бандле должен быть код последней итерации (например, для
GHG10 — строки `rank_required` и «🔒 Откроется с N ранга»), а base-URL API в
бандле = `https://meetup-planner-youmakemefry.waw0.amvera.tech` (CF подставляет
его на сборке, поэтому локальная сборка даёт другой хеш файла — это нормально).

---

# ⚠️ GHG8 P14 (2026-06-08): новый env-секрет `HF_TOKEN`

Рестарт HF Space из админки («🔄 Рестарт Space» в секции Прокси) работает
через HF Hub API: `POST huggingface.co/api/spaces/fryesw/meetup-planner-backend/restart`.

**Что сделать руками в Space (Settings → Variables and secrets):**
- `HF_TOKEN` — **write**-токен HF (huggingface.co → Settings → Access Tokens →
  New token, role: write). Без него эндпоинт отвечает 503, кнопка в админке
  дизейблится с подсказкой — ничего не ломается.
- `SPACE_ID` HF проставляет в контейнер сам; фолбэк в коде —
  `fryesw/meetup-planner-backend`.

Настройки расписания — в `admin_config` (`space_restart.schedule`,
`space_restart.last_restart_at`), миграций нет. Анти-луп: не чаще раза в
30 мин (первые ~7 мин после рестарта исходящие к TG деградированы — P14-INV).

---

# Инструкция по выкладке GHG6 (2026-05-27)

Итерация GHG6 (старт 2026-05-18, закрытие основной массы — 2026-05-26..27).
Закрыты разделы: P0, P1, P2, P2.5, P3 CL1–CL9/CL12/CL13/CL8 (включая частичную
заливку таймлайн-ячейки), D, E1–E11, F, G1, G2, G3, H, I, J, K. Открытые на
момент релиза: L (режимы сбора фраз), M (очередь задач: ручное управление),
N (история опросов и встреч + 5★ feedback) — см. `CHECKLIST_GHG6.md`.

## Миграции БД (Alembic) — 0008 → 0012

После пуша backend в HF Space контейнер сам делает `alembic upgrade head` при
старте. Все пять миграций безопасны (только `op.create_table` / `op.add_column`
без backfill, который мог бы блокировать таблицы). Порядок:

- **0008_worm_assignments** (E8) — таблица `worm_assignments` для номинации
  «Червь-пидор». Partial unique index `WHERE ended_at IS NULL` гарантирует ≤1
  активного червя.
- **0009_bot_pause** (E11) — таблица `bot_pause` (snapshot всех master-toggles
  в JSONB + auto-restore по `ends_at`). Partial unique index на одну активную
  строку.
- **0010_games_nominations** (E6) — `game_nominations` (10 активных, soft-delete
  через `removed_at`) + `polls.kind` + `polls.game_nomination_id` + `meetings.tag`.
- **0011_poll_is_closed** (G3) — `polls.is_closed BOOLEAN NOT NULL DEFAULT false`.
  Защита от двойного `bot.stop_poll` при auto-close по кворуму.
- **0012_loser_source** (H1) — `loser_rolls.source VARCHAR(8) NOT NULL DEFAULT
  'manual'` + индекс `ix_loser_source_rolled_at(source, rolled_at)`. Старые
  строки помечаются как `'manual'` (для текущего cooldown'а нерелевантно — он
  считается от ПОСЛЕДНЕЙ строки соответствующего источника).

Откат: `alembic downgrade -1` по каждой миграции в обратном порядке. Все имеют
рабочие `downgrade()` (drop_table / drop_column).

## Новые admin-ручки (REST)

Все требуют admin-tg-id из `ADMIN_TG_IDS`. Источник — `app/api/routes_admin.py`.

- **Календарь (CL0):** `GET/PUT /admin/calendar/timeline {enabled: bool}`. ⚠️
  **Default = `false`** (см. ниже про откат и `admin_config.py:450-461`).
- **Пауза бота (E11):** `GET /admin/bot-pause/current`,
  `POST /admin/bot-pause/start {duration_days?: int, reason?: str}`,
  `POST /admin/bot-pause/stop`. snapshot/restore master-toggles делается
  внутри сервиса.
- **/zaebal настройки (E11):** `GET/PUT /admin/zaebal-settings` —
  `threshold`, `duration_days`, `poll_hours`, `auto_enabled`, `auto_max_per_month`.
- **Дефолты опросов (G2/G3):** `GET/PUT /admin/polls/defaults` — четыре ключа в
  одном эндпойнте: `pin_default`, `quorum_auto_close`, `live_participants_count`,
  `pin_result`.
- **Игровые номинации (E6):** `GET /admin/games`, `DELETE /admin/games/{id}`,
  `POST /admin/games/poll-create {kind, pin?, ...}`.
- **Червь-пидор (E8):** `GET/PUT /admin/worm` — `worm.chance` (default 0.01).
- **Реакции бота (F):** `GET/PUT /admin/bot-reactions`.
- **Аватары (D):** `POST /admin/avatars/sync-now`,
  `GET/POST/DELETE /admin/avatars/schedule-once`.
- **Прокси (расширено над GHG5 P2):** селф-тест и пинги — `POST /admin/proxy/selftest`,
  `POST /admin/proxy/{id}/ping`, `POST /admin/proxy/ping-all`,
  `POST /admin/proxy/delete-dead`, `POST /admin/proxy/parse`,
  `GET/DELETE /admin/proxy/add-errors`, `POST /admin/proxy/bootstrap-fetch`,
  `GET /admin/proxy/status`, `DELETE /admin/proxy/status/last-error`,
  `GET/PUT /admin/proxy/alerts`.

## Флаг `calendar.timeline_enabled` — как откатить на legacy-вид

Новый таймлайн-вид календаря (CL1–CL9) сидит за master-toggle
`admin_config["calendar.timeline_enabled"]`. **Default = `false`** (так
было заложено на старте CL0; код в `app/services/admin_config.py:450-461`
оставляет дефолт `false` до тех пор, пока не появится явное желание раздать
новый вид всем — см. docstring там же).

- **Включить новый вид руками** (для проверки на проде после пуша):
  `PUT /admin/calendar/timeline {"enabled": true}`. Применяется без перезапуска
  — frontend читает значение при следующем рендере календаря.
- **Откат на legacy:** `PUT /admin/calendar/timeline {"enabled": false}`.
  Никакие миграции не откатываются, состояние календаря не теряется.

Frontend сам выбирает между `TimelineView` и `StripView`/`MonthView` по этому
флагу. Если хочется поднять дефолт до `true` — поправить третий аргумент
`_get_bool(...)` в `get_calendar_timeline_enabled` на `True` и пересобрать
backend (миграции не требуются).

## Новые env-секреты HF Space

В разделе **Settings → Variables and secrets** HF Space
`fryesw/meetup-planner-backend` должны существовать (имена сохранены из
`project_meetup_planner_deployed.md`):

- `ADMIN_TG_IDS` — список tg-id админов через запятую (личка для уведомлений о
  паузе/zaebal/snapshot).
- `GROUP_CHAT_ID` — chat_id основной группы (нужен publishers/announce-точкам).

Если этих переменных ещё нет — добавить **до** пуша GHG6, иначе `/zaebal`,
auto-zaebal и announce-точки опросов будут логировать warning «no admin/group
chat configured» и тихо пропускать действия.

## Шаги пуша GHG6

Backend синхронизирован: `meetup-planner-main/backend/` →
`meetup-planner-backend/` (последний mass-sync — 2026-05-26, см. логи
D-E11 / D-G2 / D-G3 / D-H1 / D-K в `CHECKLIST_GHG6.md`).

```
cd C:\Users\fa1nt\meetup-planner-backend
git status                # должны быть только файлы из mass-sync'а GHG6
git add app/ alembic/ tests/
git commit -m "feat(GHG6): worm, bot_pause, games_nominations, polls auto-close/pin, loser source, /help, timeline calendar"
git push                  # HF Space сам пересоберёт Docker
```

Frontend — отдельным коммитом из `meetup-planner-main/frontend/` в
`kickmesc-dotcom/meetup-planner` (GitHub Pages соберёт).

## Проверка после деплоя

1. HF логи на старте: `alembic upgrade head` доезжает до `0012_loser_source`
   без ошибок. `scheduler.started`, потом `webhook.set url=...`.
2. В админке появились новые экраны: `🎮 Игры`, `⏸ Пауза бота` (через
   `BotPauseBar` сверху AdminScreen), `📌 Дефолты опросов`, `⏱ Интервалы`,
   `🐛 Червь-пидор`.
3. `/help` в группе отвечает списком команд без admin-only; в личке у админа —
   с блоком «🔧 Админ».
4. Ручная рулетка лоха работает даже если автолох сегодня уже крутился —
   cooldown manual независим от auto (H1).
5. Новый календарь: включить `PUT /admin/calendar/timeline {"enabled":true}`,
   обновить Mini App → видны рендер таймлайн-ячеек, частичная заливка по часам
   (CL9), 👑×N короны в один день (J).
6. Auto-close опроса по кворуму: 5 голосов в один опрос → poll закрывается,
   `polls.is_closed=true` (G3).

## Откат всей итерации

Если что-то взорвётся фатально:

1. `git revert <commit-range> && git push` в `meetup-planner-backend` — HF
   откатит образ. Миграции 0008–0012 НЕ снимаются автоматически: новые таблицы
   останутся пустыми и не помешают legacy-коду (он их не читает).
2. Если нужно жёстко откатить и схему — на Neon вручную:
   `alembic downgrade 0007_proxies` (требует подключения с
   `DATABASE_URL` локально, HF Space сам downgrade не делает).
3. `PUT /admin/calendar/timeline {"enabled":false}` — на случай, если новый
   таймлайн надо погасить без отката backend'а.

---

# Инструкция по выкладке GHG5 (2026-05-17)

## P0 — критичные баги

### Backend (HF Space)
- `app/api/routes_meetings.py` — `loser_roll_endpoint` обёрнут в `asyncio.wait_for(send_message, 15s)`, отдельные обработчики `TelegramRetryAfter/Forbidden/Network/TimeoutError/APIError` с человечными `detail`.
- `app/api/routes_birthdays.py` (новый) — `GET /api/birthdays/calendar?from=&to=` для отрисовки 🎂 в календаре. Подключён в `main.py`.
- `app/services/admin_config.py` — `POLL_TIME_PRESETS_KEY` + `get/set_poll_time_presets` + `DEFAULT_POLL_TIME_PRESETS = 12-15/15-18/18-20/20-23`.
- `app/services/auto_pick.py::find_best_slots` принимает `presets`, строит candidates как `день × preset` вместо sliding window.
- `app/schemas/meetings.py` — `use_presets: bool = True`.
- `app/api/routes_admin.py` — `GET/PUT /api/admin/poll-presets` (admin) + `GET /api/poll-presets` (whitelist) в `routes_birthdays`.

### Frontend
- `api/client.ts::humanizeApiError` — переводит `detail` в русский текст.
- `tg/webapp.ts::showAlert` — Promise-обёртка `WebApp.showAlert`.
- `features/actions/LoserSheet.tsx` — `humanizeApiError + showAlert` на onError.
- `features/calendar/ParticipantRow.tsx` — `overflow-hidden [contain:layout_paint]` + вертикальные клетки.
- `features/calendar/views/MonthView.tsx`, `StripView.tsx` — рендер 🎂.
- `features/admin/PollPresetsScreen.tsx` (новый) + chip-кнопки в `PollSheet`/`AutoPickSheet`.

Миграций БД нет — пресеты живут в `admin_config`.

## P1 — UI/UX (контраст + Optimistic UI + Haptic)

### Frontend
- `styles.css` — снят глобальный `input { color:#000 !important; bg:#fff !important }`. Заменён на `var(--tg-theme-*)`. Добавлены классы `.chk-tg`, `.tgl-tg` (общий стиль чекбокса и toggle-slider, контраст AA в обеих темах).
- `components/Checkbox.tsx` (новый) — экспорты `<Checkbox>` и `<Toggle>`. Оба тригерят `haptic("selection")` внутри.
- `components/Spinner.tsx` (новый) — pending-индикатор для action-кнопок.
- Применено в `AutoLoserScreen`, `BirthdaysScreen`, `RandomPhrasesScheduleScreen`, `RandomPhrasesGeneratorScreen`, `PollPresetsScreen`, `ChukhanLoserScreen`, `ScheduledPublicationsScreen` — optimistic `onMutate/onError revert` где это давало эффект (single-toggle), `showAlert(humanizeApiError(e))` на onError всех мутаций, `haptic("success/error/selection/medium")` по семантике.

Миграций нет.

## P2 — Smart Proxy

### Backend
- **Миграция**: `alembic upgrade head` на Neon должен прокатать `0007_proxies`. Делает таблицу `proxy_entries` (server/port/type/secret/enabled/fail_count/last_*/dead_until + uq на server+port).
- `app/services/proxies.py` (новый) — `ProxyMode` enum (default `AUTO_FALLBACK`), `_state` синглтон (TTL 30s), CRUD-функции `list_proxies/upsert_proxy/update_proxy/delete_proxy`, `bootstrap_from_env()` для `PROXIES_BOOTSTRAP_JSON`. Hot-reload через `invalidate()`.
- `app/bot/dispatcher.py::_IPv4AiohttpSession` — переопределён `make_request`: 3 попытки, ≥5 с между переключениями, SOCKS5/HTTP через `aiohttp-socks`. На ошибке мёртвый прокси отдыхает `PROXY_DEAD_COOLDOWN_MIN` (10 мин).
- `app/api/routes_admin.py` — `GET/PUT /api/admin/proxy/mode`, `GET/POST /api/admin/proxy`, `PUT/DELETE /api/admin/proxy/{id}`.
- `app/main.py` — `bootstrap_from_env(session)` в lifespan.

### Frontend
- `api/admin.ts` — `fetchProxyMode/updateProxyMode/fetchProxies/createProxy/updateProxyEnabled/deleteProxy` + типы `ProxyMode/ProxyEntry/ProxyType`.
- `features/admin/ProxyScreen.tsx` (новый) — селектор режима, форма «+ добавить», список с Toggle/Delete.
- Карточка 🌐 «Прокси» в `AdminScreen.tsx`.

### Новая зависимость
`pyproject.toml` → `aiohttp-socks==0.10.1`. На HF Spaces после `git push` Docker сам пересоберёт образ с новой либой.

### Опциональные env-переменные
- `SMART_PROXY_ENABLED` (default `true`) — глобальный выключатель smart-proxy слоя.
- `PROXIES_BOOTSTRAP_JSON` — JSON-массив `[{"server":"1.2.3.4","port":1080,"type":"socks5","secret":"pwd"}]`. Заливается в пул при старте (upsert по server+port).
- `PROXY_DEAD_COOLDOWN_MIN` (default `10`) — сколько минут «отдыхает» помеченный мёртвым прокси.
- `PROXY_MAX_ATTEMPTS` (default `3`).
- `PROXY_MIN_SWITCH_INTERVAL_SEC` (default `5`).

### Проверка после деплоя
1. В админке появилась карточка «🌐 Прокси». Внутри — выбор режима, форма добавления, пустой список (если bootstrap не задан).
2. В логах HF при старте: `proxy.pool_loaded mode=... count=...`.
3. Тест AUTO_FALLBACK: отключил `BOT_FORCE_IPV4`, добавил мёртвый SOCKS5 → запрос идёт direct, при ошибке direct пробует прокси (в логах `proxy.request_failed`).
4. MTProto-прокси добавляется через UI, но в `make_request` пропускается (только сохраняется в пуле).

### Что НЕ сделано (P3, отложено)
- Парсер @ProxyMTProto-каналов через user-API (Telethon/Pyrogram). MVP — ручное наполнение + env-bootstrap.

---

# Инструкция по выкладке P0+P1+P2 (2026-05-14)

## P2 — реорганизация админки (этот блок)

### Backend (HF Space `fryesw/meetup-planner-backend`)
- `services/admin_config.py` — новые ключи: `loser_reasons.list`, `reminders.tick_minutes`, `random_phrases.schedule_mode/_param/_count_min/_count_max/_lookback_days/_collective_chance/_user_chance`, `autoloser.enabled/_window_start_hour/_window_end_hour/_interval_hours`. Lazy-import `LOSER_REASONS` для разрыва цикла. Legacy `random_phrases.count` пишется в sync с новым `_count_max`.
- `services/loser.py` — `roll_loser` тянет фразы из `get_loser_reasons(session)` с fallback на in-code `LOSER_REASONS`.
- `services/random_phrases.py` — `compose_random_phrase(lookback_days, collective_chance)`, `run_random_phrases_job` читает всё из admin_config (range, lookback, chances, user_chance skip).
- `bot/scheduler.py` — добавлены `_autoloser_job`, `_build_random_phrases_trigger` (4 режима), `_build_autoloser_trigger` (interval/date), `reload_dynamic_jobs(bot)` (пересборка reminders/random_phrases/autoloser). `start_scheduler` после `sched.start()` запускает `asyncio.create_task(reload_dynamic_jobs(bot))`.
- `api/routes_admin.py` — P2 endpoints: `GET/PUT /admin/loser-reasons`, `GET/PUT /admin/reminders` (триггерит reload), `GET/PUT /admin/random-phrases/schedule` (триггерит reload), `GET/PUT /admin/random-phrases/generator`, `GET/PUT /admin/autoloser` (триггерит reload), `GET /admin/loser/history`.

Миграций БД нет — всё через таблицу `admin_config` (key/value).

### Frontend (репо `kickmesc-dotcom/meetup-planner`)
- `api/admin.ts` — `LoserReasons`, `RemindersSettings`, `RPSchedule`, `RPGenerator`, `AutoLoserSettings`, `LoserHistoryRow` + fetch/update-функции.
- `features/admin/AdminScreen.tsx` — переписан как router (карточки → подменю). Корень: блок «⚡ Быстрые действия» (A5: «🚀 Прогнать рандомную фразу сейчас») + 6 карточек.
- `features/admin/SubScreen.tsx` — общий header с back-кнопкой.
- `features/admin/ChukhanLoserScreen.tsx` (A1) — веса + reroll + CRUD loser_reasons.
- `features/admin/ScheduledPublicationsScreen.tsx` (A2) — `tick_minutes` + очередь job'ов + опросы.
- `features/admin/RandomPhrasesScheduleScreen.tsx` (A3) — 4 режима расписания.
- `features/admin/RandomPhrasesGeneratorScreen.tsx` (A4) — min..max, lookback, шансы (слайдеры). Контраст ОК: явный `text-tg-text` на `bg-tg-bg/70`.
- `features/admin/AutoLoserScreen.tsx` (A6) — чекбокс + окно + interval_hours.
- `features/admin/HistoryScreen.tsx` (A7) — табы «Чуханы» / «Лохи».

### Шаги пуша P2

Backend уже синхронизирован: `meetup-planner-main/backend/` → `meetup-planner-backend/`.

```
cd C:\Users\fa1nt\meetup-planner-backend
git status
git add app/
git commit -m "feat(admin): P2 reorganization — submenus, RP/loser/reminders config"
git push
```

Фронт — отдельным коммитом из `meetup-planner-main/frontend/` в `kickmesc-dotcom/meetup-planner`.

### Проверка после деплоя
1. В админке вместо одной длинной портянки — список карточек.
2. Тап по карточке → подменю с back-кнопкой.
3. Quick Action «🚀 Прогнать фразу» работает с верхнего уровня.
4. Сохранение «⏰ тик напоминаний» → в логах HF появляется `scheduler.reminders_tick_reloaded minutes=...`.
5. Сохранение расписания фраз → `scheduler.random_phrases_reloaded mode=...`.
6. Сохранение Автолоха → `scheduler.autoloser_enabled` / `scheduler.autoloser_disabled`.
7. Существующие meme-фразы лоха продолжают подгружаться (пока админ не нажал «Сохранить» в новом редакторе с пустым списком).

---

# Инструкция по выкладке P0+P1 (2026-05-14)

## Backend (HF Space `fryesw/meetup-planner-backend`)

P0 (стабильность бота):
- `bot/dispatcher.py` — подкласс aiohttp-сессии, форс IPv4.
- `bot/scheduler.py` — декоратор с traceback на jobs.
- `main.py` — фоновая регистрация webhook/commands с retry.
- `services/loser.py` — атомарный `roll_loser` + `delete_last_loser`.
- `services/chukhan.py` — атомарный `announce_chukhan`.
- `services/random_phrases.py` — логирование пула фраз.
- `api/routes_meetings.py` — атомарный `/loser/roll` + `DELETE /loser/last`.

P1 (управление опросами):
- `api/routes_admin.py` — `GET /api/admin/polls`, `POST /api/admin/polls/{id}/close`, `DELETE /api/admin/polls/{id}`.

## Frontend (репо `kickmesc-dotcom/meetup-planner`, GitHub Pages)

P1-итерация фронта (`meetup-planner-main/frontend/`):
- `tg/webapp.ts` — расширенный `haptic()` (success/error/warning/selection).
- `features/admin/AdminScreen.tsx` — idle 10 мин + hot 5 с/3 мин, ошибки с retry, секция «Опросы в чате».
- `features/calendar/RangePill.tsx` + `ParticipantRow.tsx` — 1 ячейка = 1 день, без resize.
- `features/calendar/dateUtils.ts` — `statusLabelShort()`.
- `features/calendar/CalendarView.tsx` + `styles.css` — горизонтальный свайп, gesture hints, `overscroll-behavior-x: contain`.
- `features/editor/RangeEditorSheet.tsx` — оптимистичный patch/delete, haptic в момент тапа.
- `features/meetings/MeetingsScreen.tsx` — оптимистичный RSVP.
- `features/actions/AutoPickSheet.tsx`, `PollSheet.tsx` — haptic на тап + onError.
- `api/admin.ts` — fetch/close/delete polls.

Залить отдельным коммитом из `meetup-planner-main/frontend` в `kickmesc-dotcom/meetup-planner`. CI на pages соберёт.

## Опциональная env-переменная

В HF Space → Settings → Variables and secrets можно добавить:
- `BOT_FORCE_IPV4` = `true` (по умолчанию уже включено в коде; ставь `false`, если когда-нибудь надо будет вернуть старое поведение).

Никаких миграций БД эта итерация не вносит — Alembic трогать не нужно.

## Шаги пуша на HF

В HF Spaces git remote обычно `https://huggingface.co/spaces/fryesw/meetup-planner-backend`.

```
cd C:\Users\fa1nt\meetup-planner-backend
git status            # проверь что только app/ изменилось
git add app/
git commit -m "fix(bot): force IPv4, atomic loser/chukhan, scheduler tracebacks"
git push
```

После пуша HF Space сам пересоберёт Docker-образ. В логах должно появиться:
- `scheduler.started ...`
- (через ~5–30 сек) `webhook.set url=...`
- при ошибке сети — `webhook.set_failed attempt=1`, потом ретраи.

## Как проверить, что фикс взлетел

1. **IPv4**: в логах не должно быть `ClientConnectorError: Cannot connect to host api.telegram.org:443` после ~30 сек простоя.
2. **Атомарность лоха**: если в момент роллов попробовать сделать `/api/loser/roll` при отключённой сети к TG — ответ будет `502 telegram_send_failed`, в `loser_rolls` записи НЕ появится.
3. **Scheduler traceback**: если какая-то job упадёт — в stdout появится `scheduler.job_failed job_id=...` со стектрейсом.
4. **Random phrases**: в логах перед публикацией будет `random_phrases.pool_ready pool_sizes={...}`.

## Откат

Если что-то пойдёт не так — `git revert HEAD && git push` в HF-репо. Старая ветка из `meetup-planner-backend` (до сегодняшних правок) уже на HF — её можно вернуть как любой коммит.
