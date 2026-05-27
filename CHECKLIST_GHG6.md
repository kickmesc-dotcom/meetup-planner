# Meetup Planner — чеклист GHG6 (остаток)

Источник: `C:\Users\fa1nt\GHG6.txt`. Дата старта итерации: 2026-05-18.
Single source of truth: `C:\Users\fa1nt\meetup-planner-main` (монорепо `backend/` + `frontend/`).
После каждого блока с правками `backend/` — `cp backend/* → C:\Users\fa1nt\meetup-planner-backend\`
(отдельный git remote → HF Space). Frontend синхронизирует пользователь сам в
`kickmesc-dotcom/meetup-planner` (Pages).

Каталог `meetup-planner-frontend` упразднён — это был устаревший дубликат GitHub-репо.

Легенда: `[ ]` — не сделано, `[~]` — в работе, `[x]` — закрыто (с пометкой даты).
Приоритеты: идём по разделам сверху вниз (от простого к сложному).

История закрытых разделов GHG6 (P0, P1, P2, P2.5, P3 CL1–CL7/CL12/CL13/CL8,
D, E1–E10, F, G1, частично E11/G2/G3/H1) выгребена 2026-05-26 — детали в git
log и в `DEPLOY_NOTES.md`. Здесь оставлены только открытые пункты и пункты,
которые ещё нужно разложить из «Добавлено пользователем» (16–21).

---

## H — Раздельный cooldown auto/manual для loser (п.16, backend готов)

Контекст: автолох крутится ежедневно и блокировал ручную рулетку из-за 12-часового
cooldown'а, потому что `time_until_next_roll` смотрел МАКС `rolled_at` по всей
таблице. Решение: `LoserRoll.source` ∈ {'auto','manual'}, cooldown считается
отдельно по каждому источнику. Автолох игнорирует кулдаун (`bypass_cooldown=True`).

### Backend
- [x] **H1.1.** (2026-05-25) Миграция `alembic/versions/0012_loser_source.py`:
  `loser_rolls.source String(8) NOT NULL DEFAULT 'manual'`, индекс
  `ix_loser_source_rolled_at(source, rolled_at)`. Существующие строки помечаются
  как `'manual'` — ретро-разметка нерелевантна для текущего cooldown'а.
- [x] **H1.2.** (2026-05-25) `services/loser.py::time_until_next_roll(session, source)` —
  параметр `source` ('auto'|'manual'), фильтрует `rolled_at` по нужному семейству.
  `roll_loser(..., bypass_cooldown=False, source='manual')` — kwargs, автолох и
  admin force-reroll зовут с `bypass_cooldown=True, source='auto'`.
- [x] **H1.3.** (2026-05-25) `tests/test_loser_cooldown_split.py` — fake-session-stub
  + 4+ кейса (manual cooldown независим от auto, bypass игнорит cooldown, новой
  записи нет → cooldown=0).

### Backend sync
- [x] **D-H1.** (2026-05-26) Все три файла (`alembic/versions/0012_loser_source.py`,
  `app/services/loser.py`, `tests/test_loser_cooldown_split.py`) синкнуты в HF-клон
  в рамках общего mass-sync'а «D-E11 + tails G2/G3/H1». Push в HF — за пользователем.

---

## E11 — /zaebal, /zaebal-vote, авто-zaebal, snapshot/restore (исходник: п.11)

Backend по фактическому коду готов; frontend BotPauseBar уже подключён.
Остались мелкие хвосты — sync и провер сценариев на проде.

### Backend
- [x] **E11.1.** (2026-05-22) Таблица `bot_pause` (миграция `0009_bot_pause.py`):
  id, started_at, ends_at NULL, started_by_tg_id, reason ENUM, settings_snapshot JSONB.
  Partial unique index на (1) WHERE ended_at IS NULL — гарантия ≤1 активной строки.
- [x] **E11.2.** (2026-05-22) `bot/handlers/zaebal.py`:
  - `/zaebal` — ring-buffer голосов на 1 час, при `>= zaebal.threshold` (default 2)
    стартует пауза на `zaebal.duration_days` (default 3), прощальная фраза.
  - `/zaebal_vote` — `bot.send_poll` «GHG Bot - zaebal?», `open_period =
    zaebal.poll_hours * 3600` (default 24). Закрытие диспетчится через
    `on_poll_update` → `handle_zaebal_poll_closed`.
  - `/zaebal_undo` — снять паузу из чата (admin-only).
- [x] **E11.3.** (2026-05-22) `scheduler.py::JOB_AUTO_ZAEBAL` — `CronTrigger(day='15-18',
  hour=*, minute=…)`, `services/zaebal.run_auto_zaebal(session, bot)`. Master-toggle
  `zaebal.auto_enabled` (default true), `zaebal.auto_max_per_month` (default 1).
- [x] **E11.4.** (2026-05-22) `services/bot_pause.py::start_pause` снимает snapshot всех
  master-toggles (`reminders/loser/phrases/avatars/birthdays/chukhan/bot_reactions/
  zaebal.auto`) в `settings_snapshot`, выставляет их в false. Tick scheduler-а проверяет
  `ends_at <= now` → `restore_from_snapshot` + `end_pause`.
- [x] **E11.5.** (2026-05-22) `_notify_admin_about_pause` — личка первому из ADMIN_TG_IDS
  (Серж-Neo). Тихо логирует ошибки send (личка может быть закрыта).
- [x] **E11.6.** (2026-05-22) `POST /admin/bot-pause/start` (`{duration_days?, reason?}`),
  `POST /admin/bot-pause/stop`, `GET /admin/bot-pause/current` — те же snapshot/restore.
- [x] **E11.9.** (2026-05-22) `tests/test_bot_pause.py` — кейсы старт/snapshot/истечение→
  restore/ручное снятие→restore/повторный старт пока активна → ValueError.

### Frontend
- [x] **E11.7.** (2026-05-22) `features/admin/BotPauseBar.tsx` — sticky-плашка наверху
  AdminScreen при активной паузе: «Бот на паузе. Возобновится через Xд Yч» (живой таймер),
  кнопка `▶️ Снять паузу`. Master-toggle ниже — disabled/grayscale через CSS-флаг.
- [x] **E11.8.** (2026-05-22) В том же `BotPauseBar.tsx` — модалка «⏸ Поставить бота на
  паузу» (когда паузы нет): инпут «N дней / Бессрочно» + причина.

### Sync
- [x] **D-E11.** (2026-05-26) Backend sync `meetup-planner-main/backend/*` →
  `meetup-planner-backend/*` сделан общим mass-sync'ом «D-E11 + tails G2/G3/H1»
  (см. D-G2/D-G3/D-H1). По E11 в этом синке поехали: уже синкнутые ранее
  `alembic/versions/0009_bot_pause.py`, `app/db/models.py` (`BotPause` модель),
  `app/services/bot_pause.py`, `app/services/zaebal.py`,
  `app/bot/handlers/zaebal.py`, `app/bot/dispatcher.py`,
  `tests/test_bot_pause.py`. В этой итерации догнаны хвосты:
  `app/bot/scheduler.py` (JOB_AUTO_ZAEBAL), `app/api/routes_admin.py`
  (`/admin/bot-pause/*` + `/admin/games/*` + `/admin/polls/*`),
  `app/services/admin_config.py` (POLLS_PIN_DEFAULT/QUORUM/PIN_RESULT/WORM/...).
  92/92 backend-теста зелёные в main. Push в HF — за пользователем
  (см. итоговую инструкцию ниже).

---

## G2 — Пин опроса при публикации (исходник: п.14, backend готов, фронта нет)

### Backend
- [x] **G2.1.** (2026-05-24) `app/bot/utils/pinning.py::pin_message_safely(bot, chat_id,
  message_id, disable_notification=True)` — глотает `TelegramAPIError/Forbidden/Network/
  asyncio.TimeoutError`, лог-warning при провале. Timeout 5с.
- [x] **G2.2.** (2026-05-24) `services/polls.py::create_poll_in_chat(..., pin: bool = False)`:
  после успешного `send_poll` + commit — если `pin=True`, зовёт `pin_message_safely`.
- [x] **G2.3.** (2026-05-24) `services/games_poll.py::create_game_choice_poll(..., pin)` и
  `create_game_when_poll(..., pin)` — то же. `pin` follow-up наследует значение choice.
- [x] **G2.4.** (2026-05-24) `admin_config.POLLS_PIN_DEFAULT_KEY = "polls.pin_default"`
  (bool, default false) + `get/set_polls_pin_default`.
- [x] **G2.5.** (2026-05-24) `routes_admin.py::admin_games_poll_create` — `GamesPollCreateIn.pin:
  bool | None` (None → `get_polls_pin_default`). `routes_polls.py::PollCreateRequest.pin:
  bool | None`. Прокидываем в сервисы.
- [x] **G2.6.** (2026-05-24) `tests/test_polls_pin.py` — pin_message_safely ловит каждый
  тип исключения, `disable_notification=True`, `pin=False` не зовёт, `pin=True` зовёт.

### Frontend
- [x] **G2.7.** (2026-05-26, аудит) Типы уже на месте: `api/admin.ts::createGamesPoll`
  принимает `pin?: boolean | null`; `api/meetings.ts::PollCreateRequest` имеет
  `pin?: boolean | null`. Бэк уже разбирает `null` как «брать дефолт из admin_config».
- [x] **G2.8.** (2026-05-26) `features/admin/GamesScreen.tsx::PollLauncher` —
  чекбокс «📌 Закрепить опрос в чате» добавлен под чекбоксом follow-up.
  Стейт `pinPoll` (default false). Прокидывается в `startPoll.mutate({pin})`.
  Подсказка про disable_notification и наследование follow-up'ом.
- [x] **G2.9.** (2026-05-26) `features/actions/PollSheet.tsx` — тот же чекбокс
  над выбором «Закрыть через». Стейт `pin` (default false), прокидывается в
  `createPoll`-payload.
- [x] **G2.10.** (2026-05-26) Реализовано вместе с G3.6 в одном блоке UI:
  чекбокс «📌 Закреплять опросы при публикации» в `PollsDefaultsBlock`.
  Endpoint: единый `GET/PUT /admin/polls/defaults` со всеми четырьмя ключами.

### Sync
- [x] **D-G2.** (2026-05-26) Backend синкнут (`app/bot/utils/__init__.py`,
  `app/bot/utils/pinning.py`, `app/services/polls.py`, `app/services/games_poll.py`,
  `app/api/routes_polls.py`, `app/api/routes_admin.py`, `app/services/admin_config.py`,
  `tests/test_polls_pin.py`) в рамках общего mass-sync'а «D-E11 + tails».
  Frontend (G2.7–G2.10) — отдельная задача, ещё не сделано.

---

## G3 — Авто-закрытие опроса по кворуму + пин результата (исходник: п.15)

### Backend
- [x] **G3.1.** (2026-05-24) `admin_config.py`:
  - `POLLS_QUORUM_AUTO_CLOSE_KEY = "polls.quorum_auto_close"` (bool, default true).
  - `POLLS_LIVE_PARTICIPANTS_KEY = "polls.live_participants_count"` (int, default 5).
  - `POLLS_PIN_RESULT_KEY = "polls.pin_result"` (bool, default false).
  - Хелперы `get/set_*` для каждого ключа.
- [x] **G3.2.** (2026-05-24) `services/polls.py::record_poll_answer` — после INSERT/UPDATE
  votes считает `unique_voters` (count distinct user_id) по `poll_id`. Если `>=
  live_participants_count` И `quorum_auto_close=true` И `poll.is_closed=false` — зовёт
  `force_close_poll`. Поле `polls.is_closed` добавлено миграцией `0011_poll_is_closed.py`.
- [x] **G3.3.** (2026-05-24) `services/polls.py::force_close_poll(session, bot, db_poll,
  chat_id)` — `bot.stop_poll` с try/except на стандартные TG-exceptions, на успехе
  выставляет `db_poll.is_closed = True` и коммитит. Объявление результата идёт через
  существующий `on_poll_update` от Telegram.
- [x] **G3.4.** (2026-05-26) Применение `get_polls_pin_result` в трёх announce-точках:
  `handle_game_choice_closed` и `handle_game_when_closed` (`services/games_poll.py`)
  после `bot.send_message(...)` ловят `sent.message_id`, под флагом
  `pin_result=true` зовут `pin_message_safely`. `handle_zaebal_poll_closed` —
  send живёт в `bot/handlers/poll_answer.py`, там добавлен симметричный блок.
  Все три точки: если send упал — пин не зовётся (нечего пинить).
- [x] **G3.5.** (2026-05-26) `tests/test_polls_quorum.py` — 11 кейсов:
  - `force_close_poll` happy path: stop_poll успешен → is_closed=True, return True.
  - already-closed poll → early return False, stop_poll не зовётся.
  - `tg_message_id is None` → early return False.
  - Параметризованно 5 типов TG-исключений (Forbidden/APIError/Network/RetryAfter/
    asyncio.TimeoutError) — глотает, return False, но is_closed=True уже коммитнут
    (защита от двойного срабатывания).
  - `handle_game_choice_closed` пин: pin_result=true → pin_message_safely зовётся,
    pin_result=false → не зовётся, send упал → пин не зовётся даже при true.
  Тесты для unique_voters/quorum_auto_close в record_poll_answer не делаем —
  сама `record_poll_answer` слишком плотно повязана с реальными SQL-запросами
  через Session.scalar/scalars; покрытие через моки получалось бы хрупким.
  Логика «vote → unique_voters → force_close_poll» тестируется на проде
  ручным сценарием (5 голосов в один опрос). Backend тесты 103/103 ✅.

### Frontend
- [x] **G3.6.** (2026-05-26) `ScheduledPublicationsScreen.tsx::PollsDefaultsBlock` —
  новая секция «📌 Дефолты опросов в чате» прямо над «📊 Опросы в чате» (где
  список зависших). Четыре строки через `DefaultsRow`:
  - Switch `pin_default` (G2.10).
  - Switch `quorum_auto_close` + NumberInput `live_participants_count`
    (disabled пока quorum_auto_close=false — чтобы значение не вводило в
    заблуждение).
  - Switch `pin_result`.
  Auto-save: debounce 500мс на каждое изменение draft'а, последняя версия
  побеждает. REST: `GET/PUT /admin/polls/defaults`, типы `PollsDefaults` +
  `fetchPollsDefaults/updatePollsDefaults` в `api/admin.ts`. Backend endpoint
  использует существующие хелперы `get/set_polls_*` в `admin_config.py`,
  новых ключей не вводит. `tsc --noEmit` чист.

### Sync
- [x] **D-G3.** (2026-05-26) Скопированы `backend/app/services/games_poll.py`,
  `backend/app/bot/handlers/poll_answer.py`, `backend/app/api/routes_admin.py`,
  `backend/tests/test_polls_quorum.py` из `meetup-planner-main/backend/` в
  `meetup-planner-backend/`. `diff -r` чист (кроме `.venv`/`.gitignore`),
  `git status` в HF-клоне показывает ровно эти 4 файла как готовые к коммиту.
  Frontend (`frontend/src/api/admin.ts`,
  `frontend/src/features/admin/ScheduledPublicationsScreen.tsx`) — пушится
  пользователем из `meetup-planner-main` в `kickmesc-dotcom/meetup-planner`.
  Push в HF / Pages — за пользователем.

---

## P3 этап 4–5 — Календарь: остаток TimelineView (CL9, D-P3, D-FINAL, D-MEM)

### CL9 — частичная заливка таймлайн-ячейки при `all_day=false`
- [x] **CL9.3.** (2026-05-26) `dateUtils.ts::confidenceFillForDay` расширен:
  принимает опциональное `all_day?: boolean` в range'ах, отслеживает «выигравший»
  worst-range (не только status/confidence). Возвращаемый тип теперь
  `DayFill = { background, status, confidence, partial: {top, height} | null }`.
  При worst.all_day=false считает `top = (visStart - dayStart)/24h`,
  `height = (visEnd - visStart)/24h`, защищён clamp [0,1] и проверкой height>0.
  Tie-break при равных status+confidence: предпочитаем all_day=true (точнее
  отражает покрытие дня). Старые callers без поля `all_day` остаются на полной
  заливке (обратная совместимость).
- [x] **CL9.1.** (2026-05-26) `ParticipantRow.tsx` — при `fill.partial != null`
  background уходит с самой button (она становится прозрачной), а отдельный
  `pointer-events-none div` с `top/height` в процентах и `fill.background`
  рисует полосу строго по времени worst-range'а (0:00 = top ячейки, 24:00 = низ).
  Полная заливка остаётся для all_day=true / range, покрывающего ≥24ч.
- [x] **CL9.2.** (2026-05-26) Иконка 🕓 в **левом-верхнем** углу ячейки при
  `hasPartial` (top-0.5 left-0.5). Право-верх занят бейджем 🎂 — поэтому
  левый угол выбран как «свободное место». pointer-events-none, text-[10px],
  opacity-70 как было в спеке.
  aria-label и title таймлайн-кнопки обогащены суффиксом «(часть дня) / · часть дня».
  `tsc --noEmit` чист.

### Финал GHG6
- [x] **D-P3.** (2026-05-26) CL9 чисто фронт — backend-каталог не менялся
  (`diff -r meetup-planner-main/backend meetup-planner-backend` пуст). No-op.
- [x] **D-FINAL.** (2026-05-27) `DEPLOY_NOTES.md` — раздел «GHG6 (2026-05-27)»
  дописан наверху файла: миграции 0008–0012 с откатами, новые `/admin/*`-ручки
  (calendar/timeline, bot-pause, zaebal-settings, polls/defaults, games, worm,
  bot-reactions, avatars, proxy/{selftest,ping,...}), флаг
  `admin_config.calendar.timeline_enabled` (фактический default = **false**,
  не true как было в исходной формулировке чеклиста — поправлено по коду
  `admin_config.py:461`), включение/откат через
  `PUT /admin/calendar/timeline`, шаги пуша backend в HF, проверка после
  деплоя, инструкция отката (git revert HF + `alembic downgrade 0007_proxies`
  на Neon).
- [ ] **D-MEM.** Память `project_meetup_planner_deployed.md` — упоминание `meetup-planner-frontend`
  уже удалено, проставить `[x]` после релиза GHG6.

---

## I — Линейный экран «Интервалы» в админке (п.16, frontend)

Контекст из «Добавлено пользователем» п.16: настройки интервалов сейчас разбросаны
(автолох, чухан, фразы, опросы — каждый в своём подэкране). Цель — единый блок
«⏱ Интервалы» внизу `AdminScreen`, ниже всех прочих секций. Принцип «выставил и
забыл», поэтому ниже квик-экшенов и оперативных модулей. Дублирующие поля в исходных
подэкранах УДАЛЯЮТСЯ — единый источник правды.

### Backend
- [x] **I1.** (2026-05-26) Отдельный endpoint `/admin/intervals` не понадобился:
  `IntervalsScreen` переиспользует существующий `GET/PUT /admin/scheduled`
  (`fetchScheduledSettings`/`updateScheduledSettings`, `ScheduledSettingsIO`).
  В нём уже агрегированы `reminders.tick_minutes`, `loser.per_day`,
  `loser.window_start_hour/end_hour`, `phrases.window_start/end`,
  `chukhan.weekday`, `chukhan.window_start/end`. PUT уже вызывает
  `scheduler.reload_dynamic_jobs(bot)` (см. AD7). Дублировать ради формального
  «своего» endpoint смысла нет.

### Frontend
- [x] **I2.** (2026-05-26, аудит) `features/admin/IntervalsScreen.tsx` уже
  содержит все четыре блока (🔔 reminders tick / 🤡 автолох per_day+окно /
  💬 окно фраз / 💩 weekday-chip+окно чухана) + sticky-кнопку
  «💾 Сохранить интервалы». Дополнительные параметры расписания фраз
  (`schedule_mode/schedule_param`) живут в отдельном `RandomPhrasesScheduleScreen` —
  он сложнее, и таскать его в общий экран было бы регрессией.
- [x] **I3.** (2026-05-26, аудит) `ScheduledPublicationsScreen.tsx` уже
  не содержит числовых полей расписания — grep по `tick_minutes`, `per_day`,
  `window_start_hour`, `HourRange`, `HhmmRange`, `NumberInput` в файле пуст.
  Дубли вычищены в рамках раздела AD ранее.
- [x] **I4.** (2026-05-26) `AdminScreen.tsx` — новая секция «⏱ Интервалы»
  внизу, ниже «📜 История»: импорт `IntervalsScreen`, union `Section` расширен
  `"intervals"`, ветка рендера и `Card "🎛 Интервалы и окна"` добавлены.
  `tsc --noEmit` чист.

### Sync
- [x] **D-I.** (2026-05-26) Backend не менялся (см. I1). Frontend синхронизируется
  пользователем сам в `kickmesc-dotcom/meetup-planner`.

---

## J — Двойные короны лоха в календаре (п.16, frontend)

Контекст: после H1 в один день могут быть две записи лоха — авто (`source='auto'`) и
ручная (`source='manual'`). В календаре нужно показывать обе короны рядом 👑👑.
Текущий `routes_calendar.py::build_marks` отдаёт по одной записи на дату.

### Backend
- [x] **J1.** (по факту 2026-05-25, в рамках H2 mass-sync'а) `routes_calendar.py`
  уже отдаёт `CalendarMark.source: str | None`, `build_marks` дедупает по
  `(date, user_id, source)` — за один день у одного юзера выживают и `auto`,
  и `manual`. Endpoint считывает `r.source or "manual"` из `LoserRoll`.
- [x] **J2.** (по факту 2026-05-25) `tests/test_calendar_marks.py` — 9 кейсов,
  включая `test_loser_auto_and_manual_same_day_both_kept` и
  `test_loser_dedup_same_day_same_user_same_source`. Прогон 9/9 ✅ (2026-05-26).

### Frontend
- [x] **J3.** (2026-05-26) `api/birthdays.ts::CalendarMark` — добавлено поле
  `source?: "auto" | "manual" | null`. Комментарий поясняет, что для
  `type='loser'` приходит источник, для `chukhan` всегда null.
- [x] **J4.** (2026-05-26) `ParticipantRow.tsx` — `marksByDate` заменён на
  `chukhanByDate: Set<string>` + `loserSourcesByDate: Map<dayKey, Set<source>>`.
  В углу дня рисуем 👑 за каждый уникальный источник (1→👑, 2→👑👑). При
  `cellWidth < 40` сжимаем в 👑×N (legacy StripView без cellWidth всегда
  рисует подряд — там ячейка растягивается на 1fr и места достаточно).
  aria-label «Был лохом N раза» для compact-варианта. tsc --noEmit чист.

### Sync
- [x] **D-J.** (2026-05-26) Backend (`routes_calendar.py`,
  `test_calendar_marks.py`) уже идентичен в `meetup-planner-backend/` — синкнут
  в рамках H1/H2 mass-sync'а 2026-05-25. `diff` пуст. Frontend
  (`api/birthdays.ts`, `features/calendar/ParticipantRow.tsx`) — push из
  `meetup-planner-main` в `kickmesc-dotcom/meetup-planner` за пользователем.

---

## K — Список чат-команд /help (п.21)

Контекст: «Лист всех доступных чат команд, с максимально информативным, но лаконичным
описанием принципа действия каждой команды.»

### Backend
- [x] **K1.** (2026-05-26) `app/bot/handlers/help.py` — handler `/help`
  (+ alias `/commands`). В группе отвечает только участникам whitelist; в
  личке — кому угодно (это публичный список команд, скрывать бесполезно).
  Reply на исходное, parse_mode HTML, disable_web_page_preview.
- [x] **K2.** (2026-05-26) `app/bot/commands_catalog.py` — единый каталог
  `CommandSpec(cmd, desc_ru, scope: 'private'|'group'|'both', admin_only,
  hidden)`. Хелперы: `visible_for(scope, is_admin)` для /help и
  `bot_commands_for_scope(scope)` для set_my_commands (admin_only исключены,
  т.к. Telegram BotCommandScope не различает админов).
- [x] **K3.** (2026-05-26) `render_help(scope, is_admin)` — чистая функция:
  `📖 <b>Доступные команды</b>` + список `<b>/cmd</b> — desc`. У админа в
  личке добавляется блок `🔧 <b>Админ</b>` с admin_only-командами. В группе
  admin_only-команды скрыты всегда.
- [x] **K4.** (2026-05-26) `dispatcher.py` — `include_router(help_handler.router)`
  добавлен до `chat_capture.router`.
- [x] **K5.** (2026-05-26) `tests/test_help_commands.py` — 8 кейсов:
  catalog непуст / well-formed, group hides admin_only, private admin sees
  «🔧 Админ», hidden никогда не показывается, bot_commands_for_scope не
  светит admin_only, private user-help содержит ожидаемые команды.
  Все 8 ✅, полный сьют 111/111 ✅.

### Sync
- [x] **D-K.** (2026-05-26) Скопированы в `meetup-planner-backend/`:
  `app/bot/commands_catalog.py`, `app/bot/handlers/help.py`,
  `app/bot/dispatcher.py`, `app/main.py` (переключение
  `_register_bot_metadata` на каталог — К2-bis),
  `tests/test_help_commands.py`. `diff -r` чист, `git status` в HF-клоне
  показывает ровно эти 5 файлов. Push в HF — за пользователем.

---

## L — Режимы сбора фраз (п.20)

Контекст: «Бот полностью проигнорировал лимит 2..2 слов и скинул цитату в 8 слов.
Нужно сделать разные режимы сбора фраз и строго соблюдать min/max:
 а) только слова из сообщений: от x до y слов
 б) только цельные фразы из истории: от x до y фраз
 в) смесь из фраз и сообщений: от x до y фраз\сообщений (выбран по умолчанию)»

### Backend
- [x] **L1.** (2026-05-27) `admin_config.py`:
  `RANDOM_PHRASES_MODE_KEY = "random_phrases.mode"`, валидируется через
  `_RANDOM_PHRASES_MODES = ("words","phrases","mix")`, default `'mix'`.
  Хелперы `get/set_random_phrases_mode`. Невалидное значение в БД → silent
  fallback на `'mix'` в getter'е.
- [x] **L2.** (2026-05-27) `services/random_phrases.py::compose_random_phrase`
  разветвлён по mode:
  - `words`: `_split_into_words` (regex `[^\W_]{3,}`) даёт отдельные слова ≥3
    символа. Склейка через `_glue_words` (пробел + капитализация + терминатор).
  - `phrases`: `_split_into_chunks` (по пунктуации, MIN_CHUNK_LEN=6). Склейка
    через `_glue_chunks` со связками.
  - `mix`: оба пула объединены в единый список единиц, склейка через `_glue_chunks`.
  Невалидный mode → log-warning + fallback на `mix`.
- [x] **L3.** (2026-05-27) Строгое соблюдение [min..max] делается через
  существующий `dedup_chunks(picked_raw, all_pool=..., target_n=n)`: на входе
  `n*2` кандидатов с возвратом, на выходе ≤ n уникальных (≤ — потому что пул
  может быть скудным). При `len(picked) < n` пишется `random_phrases.pool_undersized`
  с pool/requested — это не ошибка.
- [x] **L4.** (2026-05-27) `routes_admin.py` — `mode` ушёл из
  `RandomPhrasesSettings` (этот endpoint используется только для enable+count) в
  `GeneratorSettingsOut/Update` (`/admin/random-phrases/generator`), потому что
  именно там живут `count_min/count_max` — единицы которые `mode` определяет.
  GET читает через `get_random_phrases_mode`, PUT пишет через `set_random_phrases_mode`.
  Старые клиенты без поля `mode` → Pydantic подставит default `'mix'`,
  совместимость не страдает.
- [x] **L5.** (2026-05-27) `tests/test_random_phrases_mode.py` — 12 кейсов:
  - чистые юниты `_split_into_words` / `_glue_words` (фильтр коротких,
    капитализация, терминатор, пустой ввод).
  - `compose_random_phrase` через fake-async-session (паттерн `test_loser_cooldown_split`):
    words 50 прогонов с min=max=2 → строго 2 слова в выводе;
    phrases 50 прогонов с n=1..3 → непустой вывод;
    mix 50 прогонов с n=2..5;
    invalid mode → fallback на mix;
    пустой пул → fallback-строка;
    пул < n → отдаём что есть (≤ size of pool), без падения.
  - бекап-тест `_split_into_chunks` (MIN_CHUNK_LEN=6).
  Полный сьют 123/123 ✅ (было 111 — +12 за L).

### Frontend
- [x] **L6.** (2026-05-27) `api/admin.ts::RPGenerator` обогащён полем
  `mode: RandomPhrasesMode` (+ экспорт type). `features/admin/RandomPhrasesGeneratorScreen.tsx`:
  - Секция «🧩 Режим сбора» сверху над «📏 Длина цитаты». 3 chip'а
    (🔤 Слова / 💬 Фразы / 🌀 Смесь) на `ModeChip`-компоненте, haptic('selection')
    при тапе.
  - Лейблы count_min/count_max динамические: `min слов (2..6)` /
    `min фраз (2..6)` / `min фраз/сообщений (2..6)` по выбранному mode.
  - Хинт под chip'ами объясняет семантику текущего режима.
  - `mode` участвует в `dirty`-проверке и в `body`-payload. Старые серверы без
    поля `mode` в ответе → `initial.mode ?? "mix"`. tsc --noEmit чист.

### Sync
- [x] **D-L.** (2026-05-27) Скопированы в `meetup-planner-backend/`:
  `app/services/admin_config.py`, `app/services/random_phrases.py`,
  `app/api/routes_admin.py`, `tests/test_random_phrases_mode.py`.
  `diff -rq` чист (только `.venv/.git/__pycache__/.pytest_cache/.env/.gitignore`
  исключены). Frontend (`api/admin.ts`, `RandomPhrasesGeneratorScreen.tsx`) —
  пушится пользователем сам в `kickmesc-dotcom/meetup-planner`.

---

## M — Очередь задач: видимое место + ручное управление (п.17)

Контекст: «Очередь задач это отдельная менюшка и она должна располагаться повыше
(сразу под прокси). Меня интересует, насколько сложно будет прямо сюда вшить фишку
чтобы можно было не только посмотреть на запланированную задачу, но и вручную
подправить время (даже если оно было назначено рандомно). А в некоторых случаях
и отменить принудительно.» Принципы:
- если задача рандомная (random_interval / fixed_times и т.п.) — при отмене
  scheduler сам назначит следующее рандомное время, исключая уже прошедшие часы;
- если задача периодическая (посуточная/понедельная) — отмена откладывает её
  на следующие сутки/неделю.

### Backend
- [ ] **M1.** `app/api/routes_admin.py::admin_jobs_list` (есть? проверить —
  если нет, добавить `GET /admin/jobs`) возвращает `[{id, name, next_run_time,
  trigger_kind: 'interval'|'date'|'cron', editable: bool}]`.
- [ ] **M2.** `POST /admin/jobs/{id}/reschedule` `{run_at: ISO}` — для editable-задач
  пересоздаёт триггер с `next_run_time` = `run_at`. Использует существующие
  `DateTrigger` или `IntervalTrigger.modify`. Для `cron` — отдельный кейс
  (cron не двигается одной точкой; альтернатива — задать `next_run_time` через
  `sched.modify_job`).
- [ ] **M3.** `POST /admin/jobs/{id}/cancel` — для one-shot (DateTrigger) удаляет
  job; для periodic (Interval/Cron) — выставляет `paused=True` до следующего
  цикла (или `pause_for_one_run`-механика).
- [ ] **M4.** Тесты `tests/test_admin_jobs.py` (mock APScheduler) — list / reschedule /
  cancel one-shot / cancel recurring.

### Frontend
- [ ] **M5.** `features/admin/JobsQueueScreen.tsx` — таблица задач, под каждой:
  - `next_run_time` форматированный (локальное время),
  - кнопка «✎ Изменить» → inline `<input type="datetime-local">` + «💾 Сохранить»,
  - кнопка «🚫 Отменить» (one-shot) / «⏭ Пропустить ближайший запуск» (recurring).
- [ ] **M6.** `AdminScreen.tsx` — секция «📋 Очередь задач» поднята **сразу
  под «🌐 Прокси»** (новый порядок после п.16: Quick → Прокси → Очередь задач →
  Запл. публикации → Календарь → Лох → Чухан → История → ⏱ Интервалы).

### Sync
- [ ] **D-M.** `cp backend/app/api/routes_admin.py backend/tests/test_admin_jobs.py
  → meetup-planner-backend/`. Frontend — пользователь сам.

---

## N — История опросов и встреч + пост-фактум голосование (п.18)

Контекст: «По опросам можно вести небольшую хистори, когда и кем была предложена
игра, когда голосовали и что выбрали, когда играли. Аналогичную темку с историей
можно запилить для встреч: кто предложил, в какое время собрались, на следующий
день после состоявшейся встречи запустить голосовалку "как собрались", варианты по
5-звёздочной системе, можно указать/не указывать причину оценки, можно выбрать
вариант "меня не было" — за это повышается вес на чуханство на 0.5 пункта и
уведомить об этом чатик.»

Самый крупный блок. Делится на N1 (история опросов, чисто чтение) и N2 (после-встречи-
голосование с побочными эффектами на вес чухана).

### N1 — История опросов
- [ ] **N1.1.** Backend `routes_admin.py::GET /admin/polls/history` — `[{poll_id,
  kind, question, created_at, closed_at, options:[{label, votes:[user_id]}]}]`.
  Источник: существующие таблицы `polls`, `poll_options`, `poll_votes`.
- [ ] **N1.2.** Backend `routes_admin.py::GET /admin/games/history` — фильтр
  `polls.kind in ('game_choice','game_when')`, обогащение `meetings.tag='game'`-
  записями (если был follow-up `game_when` → `Meeting.starts_at` → реально ли
  «сыграно» = `now() > Meeting.starts_at`).
- [ ] **N1.3.** Frontend `features/admin/PollHistoryScreen.tsx` — список опросов
  с раскрытием опции/голосов. Подключить как ссылку из `AdminScreen` «📜 История»
  (рядом с уже существующей историей лохов/чуханов).

### N2 — Пост-фактум голосование по встрече (5★)
- [ ] **N2.1.** Backend: миграция `0013_meeting_feedback.py` — таблица
  `meeting_feedback` (id, meeting_id, user_id, rating SMALLINT 1..5 NULLABLE,
  was_absent bool default false, reason_text text NULL, created_at).
  Unique(meeting_id, user_id).
- [ ] **N2.2.** Backend `services/meeting_feedback.py`:
  - `submit_feedback(session, meeting_id, user_id, rating?|was_absent?, reason?)`.
  - При `was_absent=True` — `chukhan_weights[user_id] += 0.5` (через существующий
    `services/chukhan.py::add_weight` или новый helper), запись в общий feed.
- [ ] **N2.3.** Backend `bot/handlers/meeting_feedback.py` — на следующий день
  после `Meeting.starts_at` (scheduler-job `JOB_MEETING_FEEDBACK`, daily 12:00)
  публикует в чат «Как собрались?» Telegram-poll 5★ + «пропустил». При
  голосе — `submit_feedback` через `on_poll_update` (расширить диспетчер kind).
- [ ] **N2.4.** Backend: тост в чат при `was_absent=True` («@user пропустил
  встречу — +0.5 к весу чухана» - добавим возможность отключить это уведомление в настройках встреч).
- [ ] **N2.5.** Frontend `PollHistoryScreen.tsx` — секция «🍻 История встреч» —
  список Meeting-записей с агрегированной средней оценкой и количеством отсутствий.
- [ ] **N2.6.** Тесты `tests/test_meeting_feedback.py` — submit / increment /
  duplicate (unique constraint) / scheduler-job создаёт polls только для тех
  Meeting.status='confirmed' старше дня.

### Sync
- [ ] **D-N.** `cp backend/alembic/versions/0013_meeting_feedback.py
  backend/app/services/meeting_feedback.py backend/app/bot/handlers/meeting_feedback.py
  backend/app/bot/scheduler.py backend/app/api/routes_admin.py
  backend/tests/test_meeting_feedback.py → meetup-planner-backend/`. Frontend — пользователь сам.

---

## Источник: «Добавлено пользователем» (приоритетные правки)

Ниже — исходный текст пользователя для пунктов 16–21, на основе которого построены
разделы H/I/J/K/L/M/N. Оставлен как первоисточник на случай, если в чекбоксах что-то
переврано.

> 16. Уже не в первый раз замечаю что если открыть расписание задач и посмотреть на
> сколько стоит фраза или автолох, то все норм. Но в назначенное время бот тупо
> забивает (или возможно пытается выполнить, но не проходят пакеты). Хотя сейчас
> для теста я дождался нужного времени, бот не выполнил задачу (автолох и рандом
> цитата) и просто перенес таймер на следующее значение. Я покликал вручную и
> цитата замечательно отправилась, а автолох прокрутился. Возможно это связано с
> тем что у нас теперь в нескольких местах блоки настройки. Я хочу попробовать
> переобъединить чтобы вообще все интервалы которые задаются для разных модулей
> (лох, чухан, пресеты голосований и т.д.), были в едином блоке "интервалы" из
> других блоков эту настройку убрать чтобы не было путаницы. Сам блок нужно
> разместить где-то внизу, менее приоритетно по очереди, поскольку у такой настройки
> принцип выставил и забыл, нет необходимости туда заглядывать часто, но нужда
> иметь возможность подвинуть настройки - есть. Еще во избежание конфликтов хочу
> чтобы автолох игнорировал кулдаун вызванный ручной прокруткой. Автолох у нас
> крутится каждый день, а рулетка по желанию (но с кулдауном). При этом именно
> лохом дня будет считаться назначенный по автолоху. А ручная прокрутка просто
> назначает лоха (но все равно запись добавляется в базу +1 лох и в календаре
> можно выставить короны как у автолоха так и у прокрученного. А если вдруг совпало
> что автолох стал еще и лохом по прокрутке, то просто делаем две короны рядом в
> календарике). Все остальные настройки и тоглы включения остаются там где и были.
> Расписание это приоритетный фикс.
>
> 17. Очередь задач это отдельная менюшка и она должна располагаться повыше (сразу
> под прокси). Меня интересует, насколько сложно будет прямо сюда вшить фишку чтобы
> можно было не только посмотреть на запланированную задачу, но и вручную подправить
> время (даже если оно было назначено рандомно). А в некоторых случаях и отменить
> принудительно (но опять же, если это рандом, то он должен будет назначить рандомно
> следующее время за исключением уже прошедших часов, а если это посуточная\понедельная
> задача, то она инициируется уже в следующие сутки\неделю).
>
> 18. По опросам можно вести небольшую хистори, когда и кем была предложена игра,
> когда голосовали и что выбрали, когда играли (если был опрос по времени игры, то
> выйгравшее время приложением учитывается как - сыграно, по прошествии данного
> времени. аналогичную темку с историей можно запилить для встреч, кто предложил, в
> какое время собрались, на следующей день после состоявшейся встречи запустить
> голосовалку - как собрались, варианты по пятизвездочной системе, можно
> указать\не указывать причину оценки, можно выбрать вариант меня не было - за
> это повышается вес на чуханство на 0.5 пункта и уведомить об этом чатик).
>
> 19. (Диагностический пункт — VPN/прокси проблемы пользователя, не задача.)
>
> 20. Самое тупое что перед прогоном фразы я выставил лимит с 2 до 2 слов, а бот
> полностью проигнорировал это и скинул цитату в 8 слов. Нужно короче сделать
> разные режимы сбора фраз из:
>  а) только слова из сообщений: от x до y слов
>  б) только цельные фразы из истории: от x до y фраз
>  в) смесь из фраз и сообщений: от x до y фраз\сообщений (выбран по умолчанию).
>
> 21. Лист всех доступных чат команд, с максимально информативным, но лаконичным
> описанием принципа действия каждой команды.
