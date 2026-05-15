# Meetup Planner — чеклист доработок (GHG4)

Источник: `C:\Users\fa1nt\GHG4.txt`. Дата старта: 2026-05-14.

Правим **monorepo** `C:\Users\fa1nt\meetup-planner-main` (single source of truth).
После каждого крупного блока — `rsync`-копия `backend/` в `C:\Users\fa1nt\meetup-planner-backend` (это то, что уходит на HF Space `fryesw/meetup-planner-backend`). Фронт уходит в репо `kickmesc-dotcom/meetup-planner` (GitHub Pages).

Легенда: `[ ]` — не сделано, `[~]` — в работе, `[x]` — закрыто (с пометкой даты).

---

## P0 — стабильность бэка (критично, чинит «бот молчит»)

- [x] **B1.** (2026-05-14) `app/bot/dispatcher.py`: подкласс `AiohttpSession` с TCPConnector(AF_INET) + timeout=30s. Env `BOT_FORCE_IPV4` (default true) переключает на легаси-сессию. SecretStr-guard сохранён.
- [x] **B2.** (2026-05-14) `app/main.py`: регистрация webhook/commands/menu-button вынесена в фоновый `asyncio.create_task` с экспоненциальным retry (5→10→20→40→80→160 с, до 6 попыток). Не блокирует startup, не валит процесс.
- [x] **B3.** (2026-05-14) `services/loser.py`: `roll_loser` принимает `on_announce` callback — flush, попытка отправки, commit/rollback. `delete_last_loser` + DELETE `/api/loser/last` (admin) добавлены. `services/chukhan.py`: `pick_chukhan_for_week` только flush, `announce_chukhan` коммитит после успешной публикации, иначе rollback.
- [x] **B4.** (2026-05-14) `app/bot/scheduler.py`: декоратор `_logged_job` оборачивает все jobs — `log.exception` с job_id перед re-raise, traceback гарантированно в stdout HF.
- [x] **B5.** (2026-05-14) `services/random_phrases.py`: лог `pool_sizes` (на каждого юзера) перед композицией + `random_phrases.starting` с n/chat_id. `log.exception` вместо тихого error.

## P0.5 — синхронизация и деплой (после каждого P0-блока)

- [x] **D1.** (2026-05-14) Backend синхронизирован: meetup-planner-main/backend/app → meetup-planner-backend/app (bot/, services/, api/, main.py).
- [x] **D2.** (2026-05-14) Инструкция по деплою P0 → `DEPLOY_NOTES.md` (только backend на HF; frontend в этой итерации не трогаем).

## P1 — UX/фронт (снижение нагрузки + читаемость)

- [x] **F1.** (2026-05-14) `AdminScreen.tsx`: idle-интервал 10 мин (`JOBS_IDLE_INTERVAL_MS`), hot-режим 3 мин с тиком 5с (`JOBS_HOT_INTERVAL_MS/DURATION_MS`), `enterHotMode()` дёргается из reroll/runPhrases/cancelJob. Индикатор «тик 5с / 10м» и кнопка ↻.
- [x] **F2.** (2026-05-14) `AdminScreen.tsx`: блоки ошибок для `forceReroll` и `triggerRandomPhrases` с кнопкой Retry; haptic("error") в onError.
- [x] **F3.** (2026-05-14) Календарь: `RangePill` переписан в display-only (без useDrag/resize). `ParticipantRow`: тап по пустой ячейке → `createRange` на 1 день + открыть редактор. Существующие multi-day из БД продолжают рендериться полосой.
- [x] **F4.** (2026-05-14) `dateUtils.ts`: `statusLabelShort()` → «своб.» / «может» / «зан.». `RangePill` использует короткую форму при `rect.span <= 1`. Полные слова — на широких span.
- [x] **F5.** (2026-05-14) `styles.css`: `.calendar-pan-container { touch-action: pan-y; overscroll-behavior-x: contain; overflow-x: hidden }`. Горизонтальный свайп переведён на явный `useDrag` (axis: 'x', threshold 60px → `shift(dir)`).
- [x] **F6.** (2026-05-14) `CalendarView.tsx`: state `hintEdge` + компонент `GestureHint` (›/‹ по краям при свайпе, +/− по центру при pinch). Гасится через 450 мс.
- [x] **F7.** (2026-05-14) `MeetingsScreen` RSVP — `onMutate` оптимистично переключает `my_rsvp`+`attendees`, откатывается на error; `RangeEditorSheet` patch/delete — оптимистично патчит/выпиливает диапазон из кэша. Haptic в момент тапа во всех action-sheet (`AutoPickSheet`, `PollSheet`, `RangeEditorSheet`, `MeetingsScreen`); `selection`/`warning`/`error` подключены через расширенный `haptic()`.
- [x] **F8.** (2026-05-14) Backend: `GET/POST(close)/DELETE /api/admin/polls[/{id}[/close]]` в `routes_admin.py` — `stopPoll`+`deleteMessage` best-effort, FK cascade на options/votes. Frontend: новая секция «📊 Опросы в чате» в `AdminScreen.tsx`, кнопки 🔒/✕ с confirm + haptic. Backend синхронизирован в meetup-planner-backend.

## P2 — функционал админки (реорганизация и новые подменю)

- [x] **A1.** (2026-05-14) Подменю «💩 Чухан / 🤡 Лох» (`ChukhanLoserScreen.tsx`) объединяет веса + force-reroll + CRUD loser_reasons. Backend: `LOSER_REASONS_KEY` в `admin_config` (JSON-строкой), `get/set_loser_reasons` с лёгким импортом дефолта из `services/loser.py` для разрыва цикла. `roll_loser` теперь читает `await get_loser_reasons(session)` с fallback на in-code список. API: `GET/PUT /api/admin/loser-reasons`. Существующие фразы из `loser.py` сохранены и продолжают подгружаться, пока админ не начал кастомизацию.
- [x] **A2.** (2026-05-14) Подменю «⏱️ Запланированные публикации» (`ScheduledPublicationsScreen.tsx`) — редактор `tick_minutes` (1..120, default 10) + перенесена очередь job'ов + перенесены опросы. Backend: `REMINDERS_TICK_MINUTES_KEY`, `get/set_reminders_tick_minutes`, `GET/PUT /api/admin/reminders`. PUT дёргает `reload_dynamic_jobs(bot)` для пересборки `meeting_reminders_tick` job'а на лету.
- [x] **A3.** (2026-05-14) Подменю «💬 Автопост рандомных фраз» (`RandomPhrasesScheduleScreen.tsx`) — 4 режима (daily_n/weekly_n/fixed_times/random_interval) + чекбокс enabled. Backend: `RANDOM_PHRASES_SCHEDULE_MODE_KEY/_PARAM_KEY`, `get/set_random_phrases_schedule`, `GET/PUT /api/admin/random-phrases/schedule`. Scheduler: `_build_random_phrases_trigger` строит cron/interval-trigger, для `fixed_times` с несколькими временами создаёт дополнительные job'ы `random_phrases:extra:N`.
- [x] **A4.** (2026-05-14) Подменю «🧪 Генератор рандомных фраз» (`RandomPhrasesGeneratorScreen.tsx`) — min..max (2..6), lookback_days (1..365), collective_chance (0..100% слайдер), user_chance (0..100% слайдер). Все инпуты явно `text-tg-text` на `bg-tg-bg/70` — контраст ОК. Backend: новые ключи `_COUNT_MIN/_MAX/_LOOKBACK_DAYS/_COLLECTIVE_CHANCE/_USER_CHANCE`, legacy-совместимость с `RANDOM_PHRASES_COUNT_KEY`. `compose_random_phrase` и `run_random_phrases_job` читают из admin_config с fallback на дефолты.
- [x] **A5.** (2026-05-14) Кнопка «🚀 Прогнать рандомную фразу сейчас» в блоке «⚡ Быстрые действия» на верхнем уровне `AdminScreen.tsx` (вне подменю). Использует существующий `POST /api/admin/random-phrases/run-now`.
- [x] **A6.** (2026-05-14) Подменю «🤡 Автолох» (`AutoLoserScreen.tsx`) — чекбокс enabled, окно (start/end hour 0..23), interval_hours (0=random раз/сутки в окне, ≥1=фикс. интервал с jitter 5 мин). Backend: `AUTOLOSER_*` ключи, `_autoloser_job` использует `roll_loser` с announce-callback в group chat, `_build_autoloser_trigger` (IntervalTrigger или DateTrigger на случайное HH:MM в окне). PUT дёргает `reload_dynamic_jobs`.
- [x] **A7.** (2026-05-14) Подменю «📜 История» (`HistoryScreen.tsx`) с двумя табами — «💩 Чуханы» и «🤡 Лохи» (последние 30 ролов с reason_text). Backend: `GET /api/admin/loser/history`, новая модель `LoserHistoryRow`.

### A0 — реорганизация навигации
- [x] (2026-05-14) `AdminScreen.tsx` переписан как роутер: корень = список карточек + блок Quick Actions (A5), детальные подменю (A1, A2, A3, A4, A6, A7) — отдельные компоненты `*Screen.tsx` с общим `SubScreen.tsx` (header с кнопкой ←). Pattern «Список карточек → детальный экран», как договорились.

## P3 — Дни рождения (новая фича)

- [x] **BD1.** (2026-05-15) Модель `Birthday` (user_id PK, `bday: Date | null`, `year_known`, 5 флагов: `remind_month/week/day/on_day/hint_week`) + `BirthdayNotification` (журнал отправок: user_id+year+kind UNIQUE) в `models.py`. Миграция `0006_birthdays`. Скопировано в meetup-planner-backend.
- [x] **BD2.** (2026-05-15) `BirthdaysScreen.tsx` — карточка на каждого юзера: `<input type="date">` + чекбокс «год известен» + 5 toggle-чекбоксов интервалов (📅 месяц / 🗓️ неделя / 📌 день / 🎉 в день / 💡 namёk-за-неделю). Дефолт «всё включено» — приходит с бэка для отсутствующих записей. Backend: `GET/PUT /api/admin/birthdays` (upsert через `pg_insert.on_conflict_do_update`). Карточка 🎂 добавлена в `AdminScreen` перед «📜 История». routes_admin.py синхронизирован в meetup-planner-backend.
- [x] **BD3.** (2026-05-15) `services/birthdays.py` — `run_birthdays_job`: проходит по всем `Birthday`, считает `_next_occurrence` с учётом 29.02→28.02 в невисокосный год, сравнивает diff с интервалами `[on_day=0, day=1, week=7, hint_week=7, month=30]`, для совпавших включённых флагов вставляет `BirthdayNotification` (UNIQUE user_id+year+kind = защита от дублей) и шлёт сообщение в group chat. Поздравление «в день» вытягивает фразу через `compose_random_phrase(lookback_days=30, collective_chance=0.0)` и пристёгивает её. Cron `9:7 * * *` в `start_scheduler` (job_id `birthdays_daily`). Label добавлен в `_JOB_LABELS`. Скопировано в meetup-planner-backend.

## P4 — Чат-команды (Telegram-нативно через `/`)

- [x] **C1–C4.** (2026-05-15) Новый роутер `app/bot/handlers/chat_commands.py` — `/phrase`, `/loser`, `/meetings`, `/tasks`. Whitelist-guard через `get_settings().whitelist_pairs` (чужие — молча). `/phrase` дёргает `run_random_phrases_job(bot)`. `/loser` дёргает `roll_loser(rolled_by=caller, on_announce=...)` — атомарно, как B3; ловим `CooldownError` → отвечаем «~N мин». `/meetings` — 5 ближайших future-only встреч + RSVP-сводка emoji. `/tasks` — `sched.get_jobs()` с лейблами и human-readable ETA, отсортировано по next_run_time, `random_phrases:extra:*` скрыты. Подключено в `dispatcher.py`.
- [x] **C5.** (2026-05-15) В `app/main.py` `_register_bot_metadata`: добавлены `/phrase /loser /meetings /tasks` в `private_cmds` И `group_cmds`. `set_menu_button` остаётся как был (B2 — фоновый retry).
- *Реролл чухана НЕ выносим в чат — остаётся в админке.* ✓

## P5 — генератор фраз (умнее)

- [x] **G1.** (2026-05-15) `_glue_chunks(chunks)` в `random_phrases.py` — массив связок `_CONNECTORS` (нейтральные «, » в 3x чаще + «и/а/но/потом/короче/в общем/блин/типа/ну/ну а/кстати/вообще/как бы/. И/. А/...»), случайный выбор между кусками; lowercase после связки-слова, Upper после «.». Финальный pass: `_DUP_WORD_RE` ловит «блин блин» → «блин», `_MULTI_SPACE_RE` чистит дубль-пробелы, `_SPACE_BEFORE_PUNCT_RE` убирает пробел перед `.,!?;:…`. Используется и в collective, и в шизо-цитате конкретного автора.
- [x] **G2.** (2026-05-15) Уже было реализовано в A4 (2026-05-14): `count_min/count_max` (2..6) в admin_config, `n = random.randint(cmin, cmax)` в `run_random_phrases_job`. Подтверждено.
- [x] **G3.** (2026-05-15) Backend: `GET /api/admin/random-phrases/pool` — берёт `lookback_days` из настроек, прогоняет `_split_into_chunks` по `chat_messages`, возвращает `{lookback_days, total_chunks, rows[{user_id, display_name, chunks_count}]}` (отсортировано desc по chunks_count). Frontend: раскрывающийся блок «📊 Пул фраз сейчас (N)» в Quick Actions `AdminScreen.tsx` — `useQuery(enabled: poolOpen, staleTime: 30s)`, нулевой счётчик подсвечивается busy-цветом.

---

## Процедура работы

1. Беру задачу из верхнего незакрытого пункта (P0 → P1 → ...).
2. Меняю код в `meetup-planner-main/`.
3. По завершении блока — копирую backend в `meetup-planner-backend/`.
4. Отмечаю `[x] (YYYY-MM-DD) краткая заметка о решении` прямо здесь.
5. На случай обрыва сессии — следующая Claude-сессия читает этот файл и продолжает с первого `[ ]`.

## Журнал решений

(заполняется по мере закрытия пунктов)
