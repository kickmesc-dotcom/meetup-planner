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
