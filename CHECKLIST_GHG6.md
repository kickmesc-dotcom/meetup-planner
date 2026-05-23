# Meetup Planner — чеклист GHG6

Источник: `C:\Users\fa1nt\GHG6.txt`. Дата старта: 2026-05-18.
Single source of truth: `C:\Users\fa1nt\meetup-planner-main` (монорепо `backend/` + `frontend/`).
После каждого блока, в котором были правки `backend/`, копия `backend/` →
`C:\Users\fa1nt\meetup-planner-backend\` (отдельный git remote → HF Space).
Frontend синхронизирует пользователь сам в `kickmesc-dotcom/meetup-planner` (Pages).

Каталог `meetup-planner-frontend` упразднён — это был устаревший дубликат GitHub-репо.

Легенда: `[ ]` — не сделано, `[~]` — в работе, `[x]` — закрыто (с пометкой даты).
Приоритеты: P0 > P1 > P2 > P2.5 > P3. Идём по приоритетам сверху вниз.

---

## P0 — прокси: индикаторы, парсер, операции с пулом

Контекст: после внедрения прокси бот работает «безупречно», но в UI неочевидно,
работает ли прокси и нужно ли переключаться. Замечание про пояснение о MTProto
осталось — фраза в `ProxyScreen.tsx:134-136` «MTProto-прокси сохраняются в пуле,
но в фолбэк не идут» вводит в заблуждение (на самом деле сейчас бот ходит через
`aiohttp_socks`, MTProto-прокси — отдельный кейс).

### Backend (`meetup-planner-main/backend`)
- [x] **PX1.** (2026-05-18) `services/proxies.py::selftest_send(bot, session)` — getMe через текущую сессию бота + опц. echo в `SELFTEST_CHAT_ID` (env, default off). Возвращает `SelftestResult{ok, mode_used, proxy_id, latency_ms, error, bot_active}`. Лимит 15с.
- [x] **PX2.** (2026-05-18) `services/proxies.py::ping_proxy(session, proxy_id)` — HTTP-проба `api.telegram.org` через `aiohttp_socks` (SOCKS5/HTTP). Для MTProto — `ping_not_supported_for_type`. Обновляет `last_ok_at`/`fail_count`/`dead_until` через `mark_proxy_ok/mark_proxy_failed`.
- [x] **PX3.** (2026-05-18) `services/proxies.py::ping_all(session)` — `asyncio.gather` с семафором 5, потом по очереди пишет результаты в БД.
- [x] **PX4.** (2026-05-18) `services/proxies.py::delete_dead(session)` — удаляет где `fail_count > 0 AND last_ok_at IS NULL`. Возвращает количество.
- [x] **PX5.** (2026-05-18) `services/proxies.py::parse_mtproto_blob(text)` — регексп по `(Server|Port|Secret) [:=] value`, группировка по повторному `Server:`. Возвращает `list[ProxyDraft]`.
- [x] **PX6.** (2026-05-18) В `scheduler.py::start_scheduler` добавлен job `JOB_PROXY_HEALTH` (IntervalTrigger `PROXY_HEALTH_INTERVAL_SEC=600` + jitter 30с). Вызывает `services/proxies.py::proxy_health_tick(bot)` — он делает selftest, при `ALWAYS_ON + 0 alive` зовёт `notify_admins_about_proxy_down`.
- [x] **PX7.** (2026-05-18) `services/proxies.py::notify_admins_about_proxy_down(bot, session, reason)` — шлёт каждому ADMIN_TG_IDS, rate-limit 1/час через `proxy.last_admin_alert_at`, тоглер `proxy.admin_alerts_enabled` (default true) — `get_alerts_enabled/set_alerts_enabled`.
- [x] **PX8.** (2026-05-18) `routes_admin.py` расширен: `POST /admin/proxy/selftest`, `POST /admin/proxy/{id}/ping`, `POST /admin/proxy/ping-all`, `POST /admin/proxy/delete-dead`, `POST /admin/proxy/parse`, `PATCH /admin/proxy/{id}` (server/port/secret/type/enabled + clear_secret), `GET /admin/proxy/status`, `DELETE /admin/proxy/status/last-error`, `GET/PUT /admin/proxy/alerts`.
- [x] **PX9.** (2026-05-18) `dispatcher.py::_IPv4AiohttpSession.make_request`: при пробросе `last_exc` пишем JSON в `admin_config["proxy.last_error"]` через `record_last_error`. UI читает через `/admin/proxy/status.last_error` и может очистить через DELETE.
- [x] **PX10.** (2026-05-18) `upsert_proxy` — проверка `count(*) >= PROXY_POOL_MAX(50)` для нового прокси (для существующего — upsert проходит). При нарушении бросает `ValueError("proxy_pool_full:50")`, REST конвертит в HTTP 400.
- [x] **PX11.** (2026-05-18) `tests/test_proxy_parse.py` — 7 кейсов: один блок, два блока, `=` разделитель + mixed case, без порта, кривой порт, пустой текст, без секрета.

### Frontend (`meetup-planner-main/frontend`)
- [x] **PX12.** (2026-05-18) `api/admin.ts` — `patchProxy`, `proxySelftest`, `proxyPing`, `proxyPingAll`, `proxyDeleteDead`, `proxyParse`, `proxyStatus`, `proxyClearLastError`, `proxyAlertsGet/Set` + типы `ProxyDraft`/`ProxyPing`/`ProxySelftest`/`ProxyStatus`/`ProxyAlerts`/`ProxyEditPatch`.
- [x] **PX13.** (2026-05-18) `features/admin/ProxyScreen.tsx` переписан:
  - **Индикаторы (топ-секция):** `StatusBadge` (🟢/🔴 + режим + пул alive/total, авто-обновление 5 мин), `SelftestCard` (🧪 кнопка + цвет точки по latency: <800ms — green, провал — red), `LastErrorCard` (показывает только если есть ошибка, ✕ очищает).
  - **Режим:** radio + подсказка под выбранным.
  - **Уведомления админу:** Toggle с показом last_alert_at.
  - **Парсер:** textarea с placeholder примером, кнопка «📋 Распарсить», превью карточек с галочками выбора, «➕ Добавить выбранные (N)». Спойлер «Ввести вручную» с прежней формой.
  - **Пул (collapsible):** заголовок-кнопка `▼ Пул прокси (N/50)`, авто-открыт если N≤5. Кнопки `Ping all`/`🗑 dead`/`↕ speed`. Каждая строка: статус-точка, server:port, type/fails/dead-until/last_ok, кнопки `📶 Ping`/`✎ Edit`/`Toggle`/`✕`. Edit — inline-форма с `💾 Сохранить`/`Отмена`.
- [x] **PX14.** (2026-05-18) `Spinner` на selftest/ping/ping-all/parser/save кнопках, haptic("success"/"error"/"warning"/"medium"/"selection") на всех мутациях.

### Sync
- [x] **D-P0.** (2026-05-18) `cp backend/app/services/proxies.py backend/app/bot/{dispatcher,scheduler}.py backend/app/api/routes_admin.py backend/tests/test_proxy_parse.py → meetup-planner-backend/`. Готово к коммиту «GHG6 P0: proxy indicators + parser».

---

## P1 — авто-опросник: облегчить

Контекст: «Авто-Опросник в последней итерации слишком переутяжелили».
Сейчас (`PollSheet.tsx`) — 3 опции с `datetime-local`, обязательное время, max 5.
Хотим: только число.месяц + день недели по умолчанию, время — опционально по чекбоксу.

### Frontend
- [x] **PL1.** (2026-05-18) `PollSheet.tsx::defaultWeekendOptions(today)` — берёт пт/сб/вс **текущей** недели для будней (Вс…Чт) или **следующей** для пт/сб/вс. Каждый вариант — `<input type="date">`, справа лейбл `Пт · 17.05` (DOW_RU + dd.MM).
- [x] **PL2.** (2026-05-18) Над списком — `<Checkbox label="Указать время">` (off by default). При включении к каждому варианту добавляется `<input type="time">` с дефолтом из first poll-preset (`?.start`) или `20:00`. Уже введённое время не сбрасывается при тогле — оно живёт в `OptionDraft.time`, чекбокс лишь решает, отправлять его или нет.
- [x] **PL3.** (2026-05-18) До 6 вариантов (3 дефолтных + до 3 добавочных). `+ ещё вариант` берёт дату «последний + 1 день», время — дефолтное.
- [x] **PL4.** (2026-05-18) `<input type="datetime-local">` убран, chip-presets-кнопки времени убраны. Презеты используются только как источник дефолтного времени, когда чекбокс включён.

### Backend
- [x] **PL5.** (2026-05-18) `PollCreateRequest.options: list[str]` (вместо `list[datetime]`) — принимает и ISO datetime, и `YYYY-MM-DD`. `services/polls.py::_parse_option` возвращает `(datetime, has_time)`. `_fmt_option(dt, has_time)` — без часа печатает `Вс 17.05`, с часом `Вс 17.05 20:00`. `ends_at = +2ч` если time задано, иначе `+24ч` (тогда `services/auto_pick`/`reminders` не получат бредовое окно).
- [x] **PL6.** (2026-05-18) `tests/test_polls_date_only.py` — 7 кейсов: date-only string, ISO datetime, ISO+Z, date object, datetime object, fmt с/без времени.

### Sync
- [x] **D-P1.** (2026-05-18) `cp backend/app/services/polls.py backend/app/schemas/meetings.py backend/tests/test_polls_date_only.py → meetup-planner-backend/`.

---

## P2 — Админка: реструктуризация разделов

Контекст: «Очень странно, что настройка фраз лоха лежит в подменюшке для чухана».

### Frontend
- [x] **AD1.** (2026-05-19) `AdminScreen.tsx`: визуальные разграничители между блоками (border-top + заголовок секции с иконкой/иконкой+caps tracking). Группы: «⚡ Быстрые действия», «📅 Календарь» (ДР, пресеты времени), «⏰ Запланированные публикации» (расписание задач, автопост фраз, генератор фраз, автолох), «🎭 Чухан / Лох» (текущий объединённый экран + история), «🔧 Инфраструктура» (прокси). Группировка по «Лох» и «Чухан» отдельно отложена до AD2/AD3.
- [x] **AD2.** (2026-05-19) Создан `features/admin/loser/LoserScreen.tsx`: force-reroll (`adminLoserRollNow`), история лохов (`fetchLoserHistory` с display_name/reason_text/датой), шаблоны фраз (`fetchLoserReasons/updateLoserReasons` через переиспользуемый `ReasonsEditor`).
- [x] **AD3.** (2026-05-19) Создан `features/admin/ChukhanScreen.tsx` (заменяет старый `ChukhanLoserScreen.tsx`, удалён): веса, force-reroll чухана (`forceReroll`), история чуханов (`fetchChukhanHistory`), шаблоны фраз чухана (`fetchChukhanReasons/updateChukhanReasons` через `ReasonsEditor`). Никаких упоминаний лоха.
- [x] **AD4.** (2026-05-19) `ScheduledPublicationsScreen.tsx` переписан на единый `fetchScheduledSettings`/`updateScheduledSettings`. Шесть `ToggleBlock`-секций (reminders/loser/phrases/avatars/birthdays/chukhan) с собственным `Switch`, числовыми инпутами, `HourRange` (часы 0–23) и `HhmmRange` (`<input type="time">`). Чухан — chip-выбор дня недели. Кнопка «💾 Сохранить настройки» — sticky-внизу, активируется только при `dirty`. Существующие секции «Очередь задач» и «Опросы в чате» сохранены ниже мастер-тоглеров.
- [x] **AD5.** (2026-05-19) Quick action «🎲 Крутануть лоха» добавлена в топе AdminScreen — `useMutation(adminLoserRollNow)` с haptic success/warning/error и success/error баннерами.

### Backend
- [x] **AD6.** (ранее, в текущей сессии подтверждено) ключи в `admin_config.py`: `reminders.enabled`, `reminders.tick_minutes`, `autoloser.*` (+ `loser.auto.per_day`), `random_phrases.enabled` (+ `random_phrases.window_start/end`), `avatars.sync_enabled` / `avatars.sync_per_day`, `birthdays.alerts_enabled`, `chukhan.weekday` / `chukhan.window_start/end`. Хелперы `get_scheduled_settings` / `set_scheduled_settings`.
- [x] **AD7.** (ранее) `scheduler.py::reload_dynamic_jobs(bot)` читает `get_scheduled_settings` и пересоздаёт динамические job'ы под master-toggles.
- [x] **AD8.** (ранее) `routes_admin.py`: `GET/PUT /admin/scheduled` (`ScheduledSettingsIO`).
- [x] **AD9.** Миграция не нужна — `admin_config` k/v.

### Sync
- [x] **D-P2.** (2026-05-19) Sync `meetup-planner-main/backend/*` → `meetup-planner-backend/*` сделан для `app/api/routes_admin.py`, `app/api/routes_birthdays.py`, `app/bot/scheduler.py`, `app/services/admin_config.py`, `app/services/chukhan.py`. Также в HF-каталоге ждут коммита: `dispatcher.py`, `schemas/meetings.py`, `services/polls.py`, `services/proxies.py`, новые тесты `tests/test_polls_date_only.py`, `tests/test_proxy_parse.py` (от P0/P1). Push в HF — за пользователем.

---

## P2.5 — ДР: тортик в ячейке участника, метки прошедших лохов/чуханов

### Frontend
- [x] **BD1.** (2026-05-19) `StripView`: 🎂 убран из шапки дня. В `ParticipantRow` иконка живёт в ячейке (user, date) того участника, чьё ДР приходится на эту дату. В `MonthView` (сетка без «строк по участникам») 🎂 остался в углу дня, но стал кликабельным (открывает поповер с первым именинником, при множественных ДР показывает `×N`).
- [x] **BD2.** (2026-05-19) Backend: `POST /api/birthdays/{user_id}/greeting?date=YYYY-MM-DD` — `routes_birthdays.py::birthday_greeting`. Шаблоны хранятся в `admin_config["birthdays.greeting_templates"]` (новые хелперы `get_birthdays_greeting_templates/set_birthdays_greeting_templates`), есть дефолтный набор. Подставляются `{name}`, `{age}`, `{age_phrase}`, `{age_or_year}` с RU-склонением (`год`/`года`/`лет`). LLM не дёргаем. Тест `tests/test_birthday_greeting.py` (8 кейсов). Frontend: `features/calendar/BirthdayPopover.tsx` — модалка с двумя кнопками: «✨ Креативное поздравление» (textarea + 📋 Скопировать + 🔄 Ещё вариант) и «📅 Назначить встречу» (закрывает поповер, кладёт `ui.pollSheetPresetDate=YYYY-MM-DD` и открывает `PollSheet`). `PollSheet` при наличии preset-даты подставляет её как первый вариант (+1, +2 дня), и очищает пресет при закрытии.
- [x] **BD3.** (2026-05-19) В `ParticipantRow` ячейка состоит из absolute-inset основной кнопки + абсолютной кнопки-иконки 🎂 поверх с `z-10` и `e.stopPropagation()` в onClick — тап мимо иконки уходит на основную кнопку (создание availability как обычно).

### Backend
- [x] **BD4.** (2026-05-19) Новый `app/api/routes_calendar.py` + `GET /api/calendar/marks?from=&to=`. Записи источников: `LoserRoll.rolled_at` пишется в `services/loser.py::roll_loser` (atomic commit), `WeeklyChukhan.week_start` — в `services/chukhan.py::announce_chukhan` (idempotent по неделе). В ответе: `LoserRoll` маппится один-к-одному в `{date, user_id, type:"loser"}`; `WeeklyChukhan` раскрывается в 7 дней (с понедельника по воскресенье) — чухан «висит» на участнике всю неделю. Чистая функция `build_marks` вынесена для теста (`tests/test_calendar_marks.py`, 8 кейсов: окно, дедуп, частично-внутри-окна, sort). Фронт-клиент: `api/birthdays.ts::fetchCalendarMarks`. Ревизия фраз: runtime-источник `admin_config["loser_reasons.list"]`/`["chukhan_reasons.list"]` через `ReasonsEditor` в UI — изменения пользователя в БД учитываются автоматически, отдельная sync-операция в коде не нужна.
- [x] **BD5.** (2026-05-19) `CalendarView` подтягивает marks (`useQuery` с staleTime 30c), фильтрует по user_id, прокидывает в `ParticipantRow`. На прошедших днях (dayKey < todayKey) в углу ячейки рисуются 👑 (loser) / 💩 (chukhan) с `pointer-events-none` — клик уходит на основную кнопку.

### Sync
- [x] **D-P2.5.** (2026-05-19) Backend sync `meetup-planner-main/backend/` → `meetup-planner-backend/`: новые `app/api/routes_calendar.py`, обновлённые `app/main.py`, `app/api/routes_birthdays.py`, `app/services/admin_config.py`, новые тесты `tests/test_calendar_marks.py`, `tests/test_birthday_greeting.py`. Diff пуст. Push в HF — за пользователем. Frontend синхронизируется пользователем сам (`kickmesc-dotcom/meetup-planner`).

---



## P3 — Календарь: горизонтальный таймлайн (большой блок)

Переработка `CalendarView` и связанных компонентов — последний крупный блок GHG6.
**CL0 уже сделан и приземлён** (admin master-toggle `calendar.timeline_enabled`,
default true, эндпоинты `GET/PUT /admin/calendar/timeline`). `CalendarView.tsx`
уже читает флаг и готов ветвиться на новый таймлайн / legacy.

**Снято с чеклиста (2026-05-20):**
- **CL10.** Миграция `confidence`/`time_from`/`time_to` не нужна — `AvailabilityRange`
  уже содержит `confidence: SmallInteger 1..5` (default 3, check constraint) и
  `starts_at`/`ends_at`/`all_day`. Бэк-схема готова, миграция отменена.
- **CL11.** `PUT /api/availability/{date}` с одним статусом на день — отказ.
  За день у участника может быть несколько диапазонов (несколько окон, разные
  уровни уверенности) — переходить на «один статус на день» это регресс модели.
  Фронт адаптируется под существующий `/api/availability/range`.

### Этап 1 — Скелет TimelineView (CL1)

- [x] **CL1.** (2026-05-21, аудит) `TimelineView.tsx` создан:
  - Sticky-left колонка аватара (60px) живёт внутри `ParticipantRow` (не отдельный
    компонент, но структура верна).
  - `TimelineGrid` — `overflow-x-auto`, общий горизонтальный скролл шапки и строк через
    единый контейнер (синхронизация автоматическая).
  - `TimelineHeader` — `sticky top-0 z-20`, grid `repeat(${days.length}, ${cellWidth}px)`,
    подсветка сегодня, ruWeekdayShort.
  - cellWidth default 56px, окно ±21 (`WINDOW_HALF=21`, span=43).
  - Без жестов, без confidence-заливки. Зум-слайдер уже зашит в `TimelineNavBar`, но это
    задел под CL5 (на CL1 неактивен).
- [x] **CL1.2.** (2026-05-21, аудит) `CalendarView.tsx:176-191` — ветвление
  `useTimelineForCurrentZoom = timelineEnabled && (zoom in day/week/month)`, при true
  отдаётся `<TimelineView/>` и гасятся `NavBar`/`ZoomController`. `TimelineNavBar` живёт
  отдельно. Legacy-views (Hours/Strip/Month/Year/AllYears) остаются под `timelineEnabled=false`.

### Этап 2 — Скролл, зум, режимы (CL2, CL3, CL5, CL6, CL12, CL13)

- [ ] **CL6.a.** Дефолт `cellWidth = containerWidth / 7.4` (ResizeObserver).
- [ ] **CL5.** Слайдер зума `cellWidth ∈ [24, 120]px`, 5 пресетов
  (День / Неделя / Месяц / Год / Все года), framer-motion на изменение.
  На «Год» и «Все года» — переиспользуем существующие `YearView`/`AllYearsView`
  (не выкидываем — они уже работают).
- [ ] **CL3.** Жесты в `TimelineGrid`:
  - `pointermove` + RAF inertia (decay velocity).
  - `pointerup` → магнит к ближайшему дню (`round(scrollLeft / cellWidth)`,
    `scrollTo({behavior:'smooth'})`).
  - Авто-скролл у краёв (15% ширины, RAF-loop, скорость = f(distance from edge)).
- [ ] **CL2.** Виртуализация: рендерим только видимые дни ± overscan 14. Невидимые
  ячейки — `<div style={{width:cellWidth}}/>` без контента. Без сторонних
  библиотек — у нас всего 6 строк, простая ручная реализация.
- [ ] **CL6.b.** Кнопка «📍 К сегодня» — `scrollTo({left: todayOffset - W/2})` с
  анимацией.
- [ ] **CL13.** Нижняя плашка: стрелки `←`/`→` (двигают на `7×cellWidth`),
  селектор режима, слайдер зума, «📍 К сегодня». Sticky.
- [ ] **CL12.** Дефолт TimelineView — «Неделя». Режим «twoWeeks» в legacy не
  трогаем (за ним стоит чекбокс админа). В TimelineView переименовать
  «2 недели» → «Произвольный диапазон» (если нужно).

### Этап 3 — Motion blur + ячейка под confidence (CL4, CL7)

- [ ] **CL4.** Motion blur: `filter: blur(${clamp(|v|/200, 0, 4)}px)` на
  `TimelineGrid` во время инерции, снимать через 80ms после `pointerup`.
  **Выключаем при `@media (prefers-reduced-motion: reduce)`** — a11y + защита
  слабых устройств. Кружок пользователей — 6 человек, у части не флагман.
- [ ] **CL7.** `TimelineCell` рендерит confidence-заливку. Без range на день →
  серый `bg-tg-secondary-bg`. С range — по worst-status и по confidence:
  - `status=1` (свободен): conf 5 → green-500 solid · 4 → green-400/60 ·
    3 → gray-300 · 2 → red-400/60 · 1 → red-500 solid.
  - `status=2` (занят): инверсия.
  - `status=3` (под вопросом) → желтый средней насыщенности.
  - Если на день несколько range — берём worst-status (приоритет: 2 > 3 > 1).

### Этап 4 — Bottom-sheet редактор и timeline-метки (CL8, CL9)

- [ ] **CL8.** Доработать `RangeEditorSheet`:
  - Радио status (1/2/3) — есть в схеме.
  - Слайдер confidence 1..5 — есть в схеме.
  - Чекбокс «Конкретное время» → два time-picker (часы/минуты). On: `all_day=false`,
    `starts_at`/`ends_at` = `selectedDate + time_from/time_to`. Off: `all_day=true`,
    окно 00:00..23:59:59 (как сейчас).
  - Дефолт confidence по status: свободен→5, занят→1, под вопросом→3.
- [ ] **CL9.** `TimelineCell` при `all_day=false` рисует частичную горизонтальную
  заливку (доля дня от 0:00 до 24:00) + иконка 🕓 в углу.

### Этап 5 — Sync и пост-релиз (D-P3, D-FINAL, D-MEM)

- [ ] **D-P3.** Sync `backend/` → `meetup-planner-backend/`. По плану в бэке менять
  нечего (миграция CL10 отменена). Если по ходу появится хелпер
  `services/availability.py::worst_status_for_day` — попадёт сюда.
- [ ] **D-FINAL.** `DEPLOY_NOTES.md` — раздел «GHG6 (2026-05-XX)»: env-переменные
  не менялись, флаг `admin_config.calendar.timeline_enabled` теперь default-true,
  ссылка на откат через `PUT /admin/calendar/timeline {enabled:false}`.
- [ ] **D-MEM.** Память `project_meetup_planner_deployed.md` — упоминание
  `meetup-planner-frontend` уже удалено, проставить `[x]` после P3.

---

## D — багфиксы и UX-правки по результатам теста

Сырой репорт пользователя (оригинал):
> «У меня так и не удалось добавить новые прокси. Я закинул порядка 13 новых, через
> авто-парсинг и вручную, протыкав разные боксы (mtproto, http, socks5). Единственный
> до сих пор рабочий прокси — `tg1.tgproxy1.fun` с прошлых билдов.
> Парсер хочется максимально дружелюбный (хочу не из чата по полям копировать).
> Порт почти всегда 443 — пусть будет предзаполнен.
> На iPhone 13 Pro экран отпрыгивает вверх при появлении клавиатуры, поле уходит из видимости.
> На главной (календарь) логично добавить «прогон фразы» в quick actions.
> Из быстрых действий админки убрать «реролл лоха» (он игнорит кулдаун и не показывает recent).
> Порядок секций админки: Быстрые действия → Прокси → Запл. публикации → Календарь → Лох → Чухан → История.»

Приоритет P0 (блокирует базовый сценарий — добавление прокси), остальное P1.

### Backend (`meetup-planner-main/backend`)
- [x] **D1.** (2026-05-20) Фикс `routes_admin.py::admin_create_proxy` — `upsert_proxy`
  возвращает `(row, created)` кортеж, старый код передавал кортеж в `_proxy_to_out`
  → ошибка сериализации, все ручные/парсерные добавления падали. Распаковка
  `row, _created = await upsert_proxy(...)`. Это и есть корень «13 прокси не добавились».
- [x] **D1b.** (2026-05-20) `services/proxies.py::parse_mtproto_blob` расширен:
  поддержка ссылочного формата `tg://proxy?...` и `https://t.me/proxy|socks?...`
  (типичный формат forward'a из @ProxyMTProto), нормализация key-aliases
  (`host/ip/address` → server, `password/pass` → secret, `protocol` → type),
  определение типа по hint-маркеру в заголовке блока (`SOCKS5 proxy ... Server: ...`),
  дедуп по `(server, port)`. Старые тесты сохранены, добавлены 6 новых
  (tg://, https://t.me/, SOCKS-url, KV-hint, дубли, mix URL+KV) — все 13 проходят.

### Frontend (`meetup-planner-main/frontend`)
- [x] **D2.** (2026-05-20) `ProxyScreen.tsx::AddProxyForm` — port default = "443",
  ресет после submit тоже на "443" (а не пустой).
- [x] **D3.** (2026-05-20) `tg/webapp.ts::installFocusScrollFix` — глобальный
  фикс iOS keyboard jump. На `focusin` для `<input>`/`<textarea>`/`contenteditable`
  делается `el.scrollIntoView({block:'center', behavior:'smooth'})` сразу и
  повторно через 300мс (после полного выезда клавиатуры). Плюс подписка на
  `WebApp.onEvent('viewportChanged')` — догоняем, когда WebApp пересчитывает
  размеры. `date/time/datetime-local` пропускаются (открывают пикер, а не
  клавиатуру). Срабатывает по всему приложению — не только в прокси-форме.
- [x] **D4.** (2026-05-20) `AdminScreen.tsx`:
  - Quick actions: убрана кнопка «🎲 Крутануть лоха» (force-reroll живёт в
    подразделе «🤡 Лох», там есть подтверждение и история). Осталась
    «🚀 Прогнать рандомную фразу» + спойлер пула фраз.
  - Новый порядок секций: Quick actions → **🌐 Прокси** (в топе после quick) →
    ⏰ Запл. публикации → 📅 Календарь → 🤡 Лох → 💩 Чухан → 📜 История.
  - Секция «🔧 Инфраструктура» упразднена (внутри был только прокси, который
    переехал наверх).
- [x] **D5.** (2026-05-20) `features/actions/ActionBar.tsx` (нижняя плашка на
  календаре): добавлена кнопка «🗯 Прогон фразы» — видна только админам
  (эндпоинт `/admin/random-phrases/run-now` admin-only). Grid авто-перестраивается:
  3 кнопки для не-админов, 4 для админов. Спиннер на pending, haptic+showAlert.
- [x] **D6.** (2026-05-20) Раздел D в этом чеклисте переписан в структурированный
  формат (P0/P1, чекбоксы, отдельные backend/frontend пункты).

### Sync
- [x] **D-D.** (2026-05-20) Sync `meetup-planner-main/backend/*` →
  `meetup-planner-backend/*` сделан для `app/api/routes_admin.py`,
  `app/services/proxies.py`, `tests/test_proxy_parse.py`. Diff: 158+/20-,
  3 файла. Frontend синхронизируется пользователем сам в
  `kickmesc-dotcom/meetup-planner`. Push в HF / Pages — за пользователем.

---


D-FINAL и D-MEM перенесены в раздел P3 этап 5 — закрываются вместе с P3.

---

## F — багфиксы после E6 (2026-05-23, из `error.txt`)

Источник — `C:\Users\fa1nt\error.txt`: после пуша E6 (game nominations) билд упал на
`NameError: name 'ProxyPingOut' is not defined`. Пользователь зафиксил роут вручную
по совету Gemini, билд встал — но обнаружились ещё проблемы. Все P0 (блокеры).

### Backend
- [x] **F1.** (2026-05-23) `routes_admin.py` — `class ProxyPingOut` перенесён выше
  его использования в `ProxyAddOut` (Pydantic не разрешал forward-ref в кавычках на
  module-level scope). Снят forward-ref `"ProxyPingOut | None"` → прямой
  `ProxyPingOut | None`. Это первый из двух коммитов.
- [x] **F2.** (2026-05-23) Send-isolation для `/admin/games/poll-create`:
  `services/games_poll.py::create_game_choice_poll` и `create_game_when_poll`
  оборачивают `bot.send_poll` в `asyncio.wait_for(timeout=8)`, ловят
  `TelegramRetryAfter/Forbidden/Network/APIError + asyncio.TimeoutError` →
  бросают `GamesPollSendFailed(reason=type_name)`. `session.add(poll)` и
  `commit` делаются ТОЛЬКО после успешного send — никаких висячих записей
  в БД без TG-сообщения. `routes_admin.py::admin_games_poll_create` ловит
  `GamesPollSendFailed` → 503 `telegram_send_failed:<reason>`.
  `handle_game_choice_closed` (зовётся из bot-handler, не HTTP) глотает
  `GamesPollSendFailed` warning-логом, follow-up `game_when` не создаётся.
- [x] **F3.** (2026-05-23) То же лечение для обычных meetup-полов:
  `services/polls.py::create_poll_in_chat` + `PollSendFailed`. Роуты в
  `routes_polls.py` (`/polls` и `/polls/auto-pick`) теперь ловят
  `PollSendFailed` отдельной веткой и возвращают 503 — раньше всё падало
  через generic `except Exception` в 502 (что плохо отличало badparse-ошибки
  от network).
- [x] **F4.** (2026-05-23) Reply-bug E9: `compose_random_phrase` зашивает
  префикс 🗣 «Сводный хор» / 👤 «Имя вещает» — в reply бота это выглядело
  как цитата от другого участника. Добавлена чистая функция
  `format_bot_reply(chunks, n)` + async-обёртка `compose_bot_reply_phrase`
  (без шапки, только `<i>склейка</i>`). `bot_reactions._react` переведён
  на новую функцию. Старая `compose_random_phrase` (для автопоста) не
  тронута — там префиксы корректны.
- [x] **F5.** (2026-05-23) `main.py::_register_bot_metadata` — `/nominate_game`
  и `/remove_nominated_game` добавлены в обоих списках `private_cmds` и
  `group_cmds`. Пользователь не находил их в меню `/` бота.
- [x] **F6.** (2026-05-23) `tests/test_bot_reply.py` — 5 кейсов на
  `format_bot_reply`: нет префиксов 🗣/👤, пустой пул → fallback, обёртка
  `<i>…</i>`, маленький пул не падает, дедуп работает. 76/76 pytest зелёный.

### Sync
- [x] **D-F.** (2026-05-23) Sync `meetup-planner-main/backend/*` →
  `meetup-planner-backend/*`: `app/api/routes_admin.py`, `app/api/routes_polls.py`,
  `app/services/games_poll.py`, `app/services/polls.py`,
  `app/services/random_phrases.py`, `app/bot/handlers/bot_reactions.py`,
  `app/main.py`, `tests/test_bot_reply.py`. Два коммита в каждом репо
  («ProxyPingOut» + «hotfix F»). Push в HF/Pages — за пользователем.

### Что НЕ закрыто

- **/zaebal (E11)** — пользователь в error.txt спрашивал про неё. Раздел E11
  в чеклисте всё ещё `[ ]` (миграция bot_pause, handler `/zaebal`+`/zaebal-vote`,
  auto-zaebal job, snapshot/restore, UI-плашка). Файл `app/bot/handlers/zaebal.py`
  на 199 строк уже существует — но интеграция (миграция, регистрация роутера,
  scheduler-job, UI) не завершена. Отложено по решению пользователя в этой
  сессии — займёмся в следующую итерацию.
- **Реакции на мем/подборку мемов** — фича не реализована, в админке нет
  настроек. Не оценена в GHG6 (не было в исходной спеке), ждёт постановки.

---

## E — правки от пользователя (2026-05-21), вносим ДО P3

Источник — раздел «Добавлено пользователем» (см. ниже, оставлен как первоисточник).
Раскладка в чекбоксы и приоритизация. Идём по приоритетам сверху вниз.

### E-P0 — блокеры базовых сценариев

#### E1. Прокси: план Б, диагностика «почему не добавляются» (источник: п.1)
- [x] **E1.1.** (2026-05-21) Backend `services/proxies.py::upsert_proxy` — `record_add_error`/`get_add_errors`/`clear_add_errors`
  (ring-buffer 20 в `admin_config["proxy.add_errors"]`, ключ `PROXY_ADD_ERRORS_KEY`). Причины: `proxy_pool_full` и
  `db_error` пишутся в `upsert_proxy`, `validation_error` — в роуте `admin_create_proxy` для любой не-pool `ValueError`
  (теперь все ValueError возвращают HTTP 400, а не 500). `duplicate` сознательно не записывается — upsert по
  `(server, port)` это нормальное обновление, фронт получает `created=False` в `ProxyAddOut`. Новые REST:
  `GET /admin/proxy/add-errors` (`ProxyAddErrorsOut{errors:[ProxyAddErrorItem]}`) + `DELETE /admin/proxy/add-errors`.
- [x] **E1.2.** (2026-05-21, аудит) Уже сделан в предыдущей сессии: `proxies.py::upsert_proxy_with_ping` (вызывает
  `ping_proxy` сразу после upsert для свежей записи), `routes_admin.py::ProxyAddOut{proxy, created, ping_result}`,
  POST `/admin/proxy` возвращает ping_result в ответе. MTProto отдаёт
  `error="ping_not_supported_for_type:mtproto"` — UI должен это отличать от «мёртв».
- [x] **E1.3.** (2026-05-21) `frontend/src/api/admin.ts`: `createProxy` теперь возвращает
  `ProxyAddResult{proxy, created, ping_result}`; добавлены типы `ProxyAddErrorItem`,
  `ProxyBootstrapResult` и функции `proxyGetAddErrors`/`proxyClearAddErrors`/`proxyBootstrapFetch`.
  `ProxyScreen.tsx`: компонент `AddResultBanner` (рендерится после `add.mutateAsync` —
  ✅/⚠️/ℹ️ по `ping_result.ok`, отдельный случай для `ping_not_supported_for_type:mtproto`).
  Раздел `🚨 Ошибки добавления (N)` — collapsible, рендерится только если буфер не пуст,
  кнопка `✕ Очистить` с confirm. Локализованные подписи `proxy_pool_full`/`db_error`/
  `validation_error`. Add-mutation после success/error инвалидирует
  `["admin","proxy-add-errors"]`. TS-проверка чистая. Кроме E1.3 — заодно влита кнопка
  `🌐 Найти живые прокси` (см. E1.4 frontend).
- [x] **E1.4 (backend).** (2026-05-21) REST `POST /admin/proxy/bootstrap-fetch`:
  тело `ProxyBootstrapIn{url_override?: str}`, ответ `ProxyBootstrapOut` со всеми полями
  `BootstrapResult` (source_url, fetched, pinged_alive, added, skipped_*, errors). Если в
  результирующих ошибках есть `bootstrap_not_configured` (override пуст + env пуст +
  BUNDLED_BOOTSTRAP_URLS пуст) — HTTP 503 `bootstrap_not_configured`. Иначе 200 со сводкой.
  Сервисная `bootstrap_fetch` (proxies.py:561) уже была.
- [x] **E1.4 (frontend).** (2026-05-21) `proxyBootstrapFetch` в `api/admin.ts`, кнопка
  `🌐 Найти живые прокси` под парсером, по success — alert со сводкой (источник,
  fetched/alive/added/skipped/errors). По 503 — `humanizeApiError` показывает `bootstrap_not_configured`.

#### E2. iOS keyboard jump в форме прокси (источник: п.2)
- [x] **E2.1.** (2026-05-21) Корень — `SubScreen.tsx:33` оборачивает контент в собственный
  `overflow-y-auto`-контейнер. На iOS-WKWebView внутри Telegram дефолтный
  `el.scrollIntoView({block:'center'})` иногда не проникает во вложенный прокрутный
  родитель (особенно когда Telegram сам двигает viewport под клавиатуру в тот же кадр).
  `tg/webapp.ts::installFocusScrollFix` теперь: 1) идёт по предкам, ищет ближайший
  `overflow-y: auto/scroll`-родитель с реальным `scrollHeight > clientHeight`;
  2) считает `targetTop = offsetWithinParent - parent.clientHeight/2 + elRect.height/2`;
  3) явно `parent.scrollTo({top, behavior:'smooth'})`; 4) параллельно дёргает старый
  `scrollIntoView` для случаев без вложенного родителя. Без меток `data-scroll-root` —
  фикс автоматически распространяется на все экраны через `SubScreen`.
- [x] **E2.2.** (2026-05-21) В `focusin`-обработчике: если `WebApp.viewportStableHeight < 500px` —
  зовём `WebApp.expand()`. Уже-expanded — no-op. Никаких per-form data-атрибутов не нужно,
  фикс глобальный.

#### E3. Loser-spin: зависание рулетки → telegram error (источник: п.3)

⚠️ **(2026-05-21, аудит) Диагноз исходных пунктов был неверным.** Анимация рулетки живёт
на фронте (`LoserSheet.tsx::mut.mutationFn` — локальный `setInterval` имён каждые 90мс,
ожидание ≥1.1с), на бэке никакой анимации `edit_message_text` нет (`loser.py::roll_loser` —
обычный одношаговый SELECT/INSERT + commit). «Зависание» = HTTP-запрос `POST /meetings/loser/roll-now`
не отвечает вовремя, потому что бэк после ролла блокируется на `bot.send_message(group_chat_id, …)`
через прокси (в `routes_admin.py::admin_loser_roll_now._announce` и/или в публичном loser-route).
Корректный фикс — не блокировать ответ HTTP-вызова отправкой в Telegram.

**Решение (по уточнению пользователя 2026-05-21):** унифицировать публичный и админский
методы на рабочий — админская версия глотает TG-ошибки в `_announce`, поэтому `roll_loser`
коммитит запись и возвращает успех. UI-крутилка живёт чисто на фронте (LoserSheet —
локальный setInterval + ожидание ≥1.1с) и не влияет на метод отправки.

- [x] **E3.1.** (2026-05-21) `routes_meetings.py::loser_roll_endpoint._announce`: все TG-ошибки
  (`TelegramRetryAfter`/`TelegramForbiddenError`/`TelegramNetworkError`/`TelegramAPIError`/
  `asyncio.TimeoutError`/прочие) теперь ловятся внутри `_announce` и не пробрасываются —
  лог-warning, `sent_flag["ok"]=False`. `roll_loser` получает «успешный» announce → коммитит
  запись. HTTP-ответ всегда 200 (только cooldown остался 429). Таймаут на send сокращён с
  15с до 8с — UX-крутилка на фронте крутится ≥1.1с, дольше 8с никто не ждёт.
- [x] **E3.2.** (2026-05-21) Отдельный ring-buffer `loser.publish_errors` не нужен — sent_to_chat
  в ответе фронту и log.warning достаточно для диагностики. Если сообщений в чате нет, а ролл
  в истории есть — пользователь сам поймёт, что прокси умер, по селфтесту в админке.
- [x] **E3.3.** (2026-05-21) `chukhan.py:136 edit_message_text` — это не анимация рулетки, это
  редактирование «🥁 Чухан недели» сообщения при обнаружении дубликата (есть `try/except`
  с лог-warning). Админская `/admin/chukhan/reroll` уже использует тот же безопасный путь.
  Расхождения с loser-флоу нет.

### E-P1 — UX-баги и мелкие новые фичи

#### E4. Цитатник: дедуп фраз внутри одного сообщения (источник: п.4)
- [x] **E4.1.** (2026-05-21) `services/random_phrases.py::dedup_chunks(picked, all_pool, target_n,
  similarity_threshold=0.85)` — чистая функция: нормализация (`_normalize_chunk`: lower + collapse
  whitespace), сравнение через `difflib.SequenceMatcher.ratio()` со всеми уже отобранными,
  отбрасывание кандидата если max ratio > 0.85. При нехватке после фильтра — добор из
  `all_pool` (shuffle, тот же фильтр). Применена в обеих ветках `compose_random_phrase`:
  collective-ветке (после `random.sample`) и user-ветке (раньше был `[random.choice(pool) for _]`
  с возвратом — теперь берём с запасом `n*2` и фильтруем). Кейс «Русланище» (короткий пул +
  выбор с возвратом → повторы) починен: даже если функция вернёт меньше n — `_glue_chunks`
  это переживёт, повторы исключены.
- [x] **E4.2.** (2026-05-21) `tests/test_random_phrases_dedup.py` — 9 кейсов: нормализация,
  точные дубли, почти-дубли (~0.95/0.90 ratio), добор из пула при дублях в picked, граничный
  случай «пул совпадает с picked», порог 0.85 (различные ~80% — не дубли), пустые/whitespace,
  target_n=0, пустой picked. Все 61 тест проекта проходят.

#### E5. Фразы лох/чухан: приоритет свежим (источник: п.5)
- [x] **E5.1.** (2026-05-22, аудит) `services/phrase_weights.py` уже содержит `weighted_choice`
  (вес = `1 / (1 + use_count)`) на основе `phrase_hash` (SHA1 hex, 16 символов). Использовано
  в `services/loser.py:155` (LOSER_USE_COUNTS_KEY) и `services/chukhan.py:176` (CHUKHAN_USE_COUNTS_KEY).
  Fallback на `random.choice` если по какой-то причине вернётся `None`.
- [x] **E5.2.** (2026-05-22, аудит) `increment_use_count` зовётся сразу после выбора в обеих ветках.
  `cleanup_use_counts(active_phrases)` дёргается из `admin_config.set_loser_reasons:195` и
  `set_chukhan_reasons:513` — счётчики фраз, исчезнувших из списка, дропаются автоматически.
- [x] **E5.3.** (2026-05-22) REST переименованы в единый стиль: `GET/DELETE /admin/loser-reasons/use-counts`
  и `/admin/chukhan-reasons/use-counts` (раньше были `/admin/loser/reasons/...` — рассинхрон с
  `/admin/loser-reasons`). `api/admin.ts`: типы `ReasonUseCountsOut`/`ReasonUseCountsCleared` +
  функции `fetchLoserReasonUseCounts`/`clearLoserReasonUseCounts`/`fetchChukhanReasonUseCounts`/
  `clearChukhanReasonUseCounts`. `ReasonsEditor.tsx` — новые пропы `useCounts?: Record<string,number>`,
  `onResetCounts?: () => void`, `resetCountsPending`. При наличии `useCounts` рядом с каждой фразой
  серая подпись `use:N` (tabular-nums). При наличии `onResetCounts` под кнопкой «Сохранить» — отдельная
  кнопка «🔄 Сбросить счётчики использования» с confirm-диалогом и haptic warning. `LoserScreen.tsx`
  и `ChukhanScreen.tsx` подключают новые query/mutation и инвалидируют `["admin","*-reasons-use-counts"]`
  после save/reset. TS чистый, 61 backend-тест зелёный.

#### E7. Закрываемое приветствие (источник: п.7)
- [x] **E7.1.** (2026-05-22) `admin_config.py` — `UI_HIDE_GREETING_PREFIX = "ui.hide_greeting:"`,
  хелперы `get_ui_hide_greeting(session, tg_id) -> bool` / `set_ui_hide_greeting(session, tg_id, hide)`.
  Per-user, ключ привязан к `telegram_id` (стабильнее автоинкремента user.id). `routes_users.py`:
  `GET/PUT /api/me/ui-prefs` со схемой `UiPrefsIO{hide_greeting: bool}`. PUT возвращает
  актуальное состояние. Backend-тесты 61/61 ✅.
- [x] **E7.2.** (2026-05-22) `api/availability.ts` — типы `UiPrefs`, функции `fetchUiPrefs` /
  `updateUiPrefs`. `App.tsx` — query `["ui-prefs"]` + mutation с optimistic update (cancel/snapshot/
  rollback). В календарном табе `<header>` рендерится только если `!hide_greeting`. Внутри —
  абсолютная кнопка `✕` (top-right, min-h/w 8, haptic warning + selection on success,
  disabled на pending). Никаких упоминаний геймификации в UI/коде нет — это решение отложено
  до реальной имплементации, чтобы не плодить мёртвые рубильники. TS чистый.
- ⊘ **E7.3.** Снято с GHG6 по решению пользователя 2026-05-22: рубильник геймификации
  бессмыслен пока нечего гейтить (профиль/уровни не написаны). Вернёмся к этому, когда
  начнём имплементировать сами уровни/ранги — заодно тогда заведём флаг.

#### E10. Авто-синхрон аватарок → разовая кнопка + одноразовое расписание (источник: п.10)
- [x] **E10.1.** (2026-05-22) `admin_config.py::get_scheduled_settings` — default
  `avatars.sync_enabled` теперь `False` (было `True`). Существующие установки бота, где
  значение уже хранится в БД как `true`, продолжат работать как прежде — флип влияет
  только на свежие записи и пользователей, у кого ключ ещё не выставлен.
  `scheduler.py::reload_dynamic_jobs` уже корректно удаляет `JOB_AVATAR_SYNC` при
  `enabled=false` — рекуррент-job больше не регистрируется по дефолту.
- [x] **E10.2.** (2026-05-22) `POST /admin/avatars/sync-now` — синхронно зовёт
  `sync_all_avatars(session, bot)`, возвращает `{synced: N}`. `services/avatars.py::sync_all_avatars`
  доработан: теперь возвращает количество затронутых пользователей (`int`), а не `None` —
  UI показывает в alert «Запрошены аватарки N пользователей».
- [x] **E10.3.** (2026-05-22) `POST/GET/DELETE /admin/avatars/schedule-once`:
  - POST `{run_at: ISO datetime}` — валидирует «в будущем» (raise 400 иначе),
    кладёт `DateTrigger` one-shot job с фиксированным id `JOB_AVATAR_SYNC_ONE_SHOT`,
    `replace_existing=True` (старый одноразовый перезаписывается).
  - GET — отдаёт `{scheduled: bool, run_at}` (по `sched.get_job(id).next_run_time`).
  - DELETE — `sched.remove_job(id)` (если есть). Возвращает `scheduled=false`.
  Парсер `_parse_iso_future` — `datetime.fromisoformat` с подменой `Z` → `+00:00`,
  naive datetime трактуем как UTC (UI шлёт `local.toISOString()`).
- [x] **E10.4.** (2026-05-22) Frontend: `api/admin.ts` — типы `AvatarsSyncNowResult`,
  `AvatarsScheduleOnce` + 4 функции (`avatarsSyncNow`, `avatarsScheduleOnceGet/Post/Delete`).
  `ScheduledPublicationsScreen.tsx` — удалён `NumberInput` для `per_day` в AvatarsBlock,
  hint обновлён на «Регулярного авто-синхрона больше нет. Запускай вручную или планируй...»,
  вместо контента — компонент `AvatarsActions`. В нём: query `["admin","avatars-schedule-once"]`
  (staleTime 10s), кнопка «🔄 Синхронизировать сейчас» (mutation, на success — invalidate
  `["users"]` чтобы фронт подхватил новые аватарки), блок «📅 Запланировать однократно» с
  `<input type="datetime-local">` (default = завтра 10:00 локально), кнопка «📅 Запланировать»
  (mutation шлёт `local.toISOString()`), и пилюля «Запланировано: dd.MM.yyyy HH:mm» с
  крестиком отмены — рендерится только если `scheduled=true`. После плана/отмены — вызов
  `onJobsChanged()` (enterHotMode) чтобы общая очередь задач обновилась. Master-toggle
  «Синхронизация аватарок» оставлен — он отвечает только за рекуррент-job в scheduler,
  поля для него убраны.
  TS чистый, backend 61/61 ✅.

### E-P2 — новые крупные механики

#### E6. Номинации игр + голосование (источник: п.6)
- [x] **E6.1.** (2026-05-22) Backend: модель `GameNomination` (`game_nominations`: id, name, added_by_tg_id,
  added_at, removed_at). Миграция `alembic/versions/0010_games_nominations.py` добавляет таблицу +
  `polls.kind` (String 32 nullable: `'game_choice'`/`'game_when'`, NULL для legacy meetup-полов),
  `polls.game_nomination_id` (BigInteger nullable, для game_when — id игры-победителя), `meetings.tag`
  (String 16 nullable, `'game'` для встреч-игр). Лимит 10 активных (`MAX_ACTIVE_NOMINATIONS`)
  проверяется в `services/games.py`, не БД-констрейнтом — soft-deleted строки реанимируются при
  повторном добавлении имени, а не дублируются.
- [x] **E6.2.** (2026-05-22) `services/games.py`: `list_active_nominations`, `count_active_nominations`,
  `add_nomination` (lower-case dedup, restore из soft-delete, raise `NominationLimitExceeded`/
  `NominationEmpty`), `remove_nomination(id)`, `remove_nomination_by_name(name)`. REST:
  `GET /admin/games` → `{items, max_active}`, `POST /admin/games` (создание), `DELETE /admin/games/{id}`
  (soft-delete). Bot-команды (`chat_commands.py`): `/nominate_game <name>`, `/remove_nominated_game
  <name>` — whitelist-only, информативные ответы при ошибках. Лимит 10 и пустое имя обрабатываются
  отдельными ветками.
- [x] **E6.3.** (2026-05-22) `services/games_poll.py::create_game_choice_poll` — `bot.send_poll(
  is_anonymous=False, allows_multiple_answers=False, open_period=timeout_hours*3600)` в
  `settings.group_chat_id`. Сохраняет `Poll(kind='game_choice', tg_poll_id, tg_message_id, closes_at)` +
  `PollOption(label=nomination.name, starts_at=ends_at=now())` (starts_at/ends_at — заглушки,
  семантически про meetup-time-варианты, для игр не используются). Префикс `[+when]` в
  `Poll.question` хранит follow-up-флаг без расширения схемы. REST: `POST /admin/games/poll-create`
  `{timeout_hours: 1..72, nomination_ids?, follow_up_when}` → `GamesPollCreateOut`. Валидация
  ≥2 опций / ≤10 (telegram limit) в сервисе. Закрытие — `bot/handlers/poll_answer.py::on_poll_update`
  диспетчирует по `Poll.kind` (`game_choice`/`game_when` → `handle_game_*_closed`, иначе zaebal).
  Победитель выбирается по `PollVote`-counts с tie-break по id ASC.
- [x] **E6.4.** (2026-05-22) `handle_game_choice_closed` — объявляет победителя реплаем на исходный
  полл, и если был `[+when]`-префикс, дёргает `create_game_when_poll`: 3 ближайшие даты от today,
  single answer, `PollOption.starts_at` = `date 00:00 UTC` (это «слот» встречи). `Poll(kind='game_when',
  game_nomination_id)` помнит, какую игру привязать. `handle_game_when_closed` — победившая дата →
  `Meeting(title="{game.name} 🎮", starts_at, ends_at, tag='game', status='confirmed')` + объявление
  в чат. Если 0 голосов — короткое сообщение в чат, ничего не пишем.
- [x] **E6.5.** (2026-05-22) Frontend: `api/admin.ts` — типы `GameNomination`,
  `GameNominationsList`, `GamesPollCreateResult` + функции `fetchGameNominations`,
  `addGameNomination`, `removeGameNomination`, `createGamesPoll`. `tg/webapp.ts` дополнен
  `showConfirm(message)` (WebApp.showConfirm с fallback на `window.confirm`).
  `features/admin/GamesScreen.tsx` — секция «Номинации» со списком, формой «➕ Добавить» (лимит 10,
  disabled при достижении), кнопкой «🗑» с confirm; секция «Запустить голосование» с range-слайдером
  12–24ч, чекбоксом «follow-up Когда играем» (default ON), `🗳 Запустить голосование` (disabled при
  <2 номинаций, confirm + alert со сводкой). `AdminScreen.tsx` — новый `SectionGroup "🎮 Игры"`
  с карточкой, ведущей в GamesScreen.
- [x] **E6.6.** (2026-05-22) Backend: `routes_calendar.py` — новый `GET /api/games/scheduled?from&to`
  отдаёт `[GameSessionOut{meeting_id, title, date, starts_at}]` для `Meeting.tag='game'` в окне.
  Frontend: `api/birthdays.ts` — `GameSession` тип и `fetchScheduledGames`. `CalendarView.tsx` —
  новый `useQuery(["games-scheduled", win])` со staleTime 30c, прокидывает `Set<YYYY-MM-DD>`
  как `gameDates` в `StripView` / `TimelineView` / `MonthView`. В Strip/Timeline иконка 🎮 в
  правом-верхнем углу шапки дня; в MonthView — в левом-нижнем углу ячейки (right-top занят 🎂).
  Без привязки к участнику — игра коллективна.

### Sync E6
- [x] **D-E6.** (2026-05-22) Синхронизировано в `meetup-planner-backend/`:
  `app/db/models.py`, `alembic/versions/0010_games_nominations.py`, `app/services/games.py`,
  `app/services/games_poll.py`, `app/api/routes_admin.py`, `app/api/routes_calendar.py`,
  `app/bot/handlers/chat_commands.py`, `app/bot/handlers/poll_answer.py`. Frontend
  (`src/api/admin.ts`, `src/api/birthdays.ts`, `src/tg/webapp.ts`, `src/features/admin/GamesScreen.tsx`,
  `src/features/admin/AdminScreen.tsx`, `src/features/calendar/CalendarView.tsx`,
  `src/features/calendar/views/StripView.tsx`, `MonthView.tsx`, `TimelineView.tsx`) —
  через `kickmesc-dotcom/meetup-planner` пользователем. Backend-тесты 71/71 ✅, `tsc --noEmit` ✅.
  Push в HF / Pages — за пользователем. **Важно:** на HF Space перед первым стартом нужна миграция
  `alembic upgrade head` (новая 0010).

#### E8. Червь-пидор: редкая особая номинация при ролле лоха (источник: п.8)
- [x] **E8.1.** (2026-05-21, аудит) `loser.py:216 decide_worm` (чистая функция),
  `roll_loser` использует его + читает `is_worm_enabled`/`get_worm_chance` из admin_config (default 0.01).
  Лох-счётчик +1 пишется в любом случае (E8.1.5: червь — это «надстройка» над лохом, не замена).
- [x] **E8.2.** (2026-05-21, аудит) `db/models.py:160 WormAssignment` (worm_assignments table) +
  миграция `alembic/versions/0008_worm_assignments.py`. При новом назначении предыдущий
  `WormAssignment` закрывается (`ended_at = now`), partial unique index гарантирует не более одного
  активного носителя. admin_config helpers: `is_worm_enabled/set_worm_enabled/get_worm_chance/set_worm_chance`.
  Yellow-event в group chat — встроен в `compose_loser_message` с особой шапкой 🪱 (см. test_worm.py).
- [~] **E8.3.** (2026-05-21, аудит) Запись факта сделана через `WormAssignment` (это и есть «achievement»
  по факту). Таблицы `user_achievements` нет — но и нет UI ачивок, который её бы потреблял.
  Гейт `gamification.enabled` (E7.3) тоже не нужен пока — нечего гейтить. Считаем закрытым в рамках MVP.
- [x] **E8.4.** (2026-05-22) Backend: исправлен баг с двойным префиксом —
  `routes_calendar.py:136` маршрут был `/api/worm/current`, но роутер монтируется с
  `prefix="/api"` (см. `app/main.py:192`), реальный URL получался `/api/api/worm/current`
  → фронт никогда бы не достучался. Исправлено на `/worm/current` (итоговый URL
  `/api/worm/current`). Frontend: `api/birthdays.ts` — `WormCurrent` тип и
  `fetchCurrentWorm()`. `CalendarView.tsx` — query `["worm-current"]` со staleTime 30c
  (ролл — событие редкое, чаще опрашивать смысла нет), прокидывает `wormUserId` в
  `StripView`/`TimelineView`. Оба view — новый проп пробрасывают в `ParticipantRow`
  через `isWorm={wormUserId === u.id}`. `ParticipantRow.tsx` — в sticky-left колонке
  аватара добавлен абсолютный бейдж 🪱 (bottom-right аватара, на `bg-tg-bg` rounded-full
  с тенью, чтобы не сливался с цветным аватаром). Title аватара тоже меняется на
  «🪱 X — червь-пидор», если активен. Иконку показываем в **колонке участника**,
  а не в каждой ячейке: звание переходящее и непрерывное, дублировать по 43 ячейкам
  излишне и шумно. TS чистый, 61/61 backend-тест зелёный.
- [x] **E8.5.** (2026-05-21) Тест `tests/test_worm.py` (10 кейсов): `decide_worm` (5 — disabled, zero chance, граница <chance, ==chance не триггерит, chance=1) + `compose_loser_message` (5 — без extras, worm-layout, с prev holder, без prev, повтор same user без self-transfer). Интеграция с БД (создание/закрытие `WormAssignment`, partial unique index) проверяется вручную при первом ролле — отдельный sqlite-стенд в проект не тащим (его нет ни у одного другого сервиса). Все 52 теста проекта проходят на свежем `.venv` (Python 3.12, `pip install -e ".[dev]"`).

#### E9. Бот реагирует на @-mention и reply (источник: п.9)
- [x] **E9.1.** (2026-05-22, аудит) `bot/handlers/bot_reactions.py::on_message` — фильтр `F.text` +
  `_mentions_bot()` (entity `mention` через `@bot_username` lowercase или `text_mention` через
  `entity.user.id == bot_id`). Бот identity кешируется в модуле (`_BOT_IDENTITY`) одним
  `bot.me()`-вызовом. Реагируем только в `settings.group_chat_id` и только на whitelist'е.
  Master-toggle `bot_reactions.mention_enabled` (default true). Роутер подключён в
  `dispatcher.py` до `chat_capture`.
- [x] **E9.2.** (2026-05-22) Backend: два независимых тогла для reply, по спеке GHG6.txt п.9:
  `bot_reactions.reply_all_enabled` (default false) — отвечать на ЛЮБОЙ reply на сообщение
  бота, включая reply к рандом-цитатам; `bot_reactions.reply_except_phrases_enabled`
  (default true) — отвечать на reply, КРОМЕ случаев, когда оригинал — рандом-цитата.
  Логика в `on_message`: если `reply_all_enabled` → отвечаем; иначе если
  `reply_except_phrases_enabled and not is_phrase` → отвечаем. Цитаты опознаются по
  префиксам `🗣 ` / `👤 ` (см. `compose_random_phrase`). `_react()` шлёт `compose_random_phrase(session, n=1)`
  как reply на исходное сообщение, ошибки send'а ловятся (`log.warning`).
  **Раньше** ключи назывались `reply_enabled` / `reply_except_phrases` и работали как
  `reply_all_enabled` + «исключение», но это не совпадало со спекой (третий тогл вообще не работал
  при выключенном `reply_enabled`). Имена и логика приведены к спеке.
- ⊘ **E9.3.** Снято с GHG6 по принципу [[no-premature-gamification]]: счётчик ачивки «Укротитель
  паст» бессмысленно делать пока нет UI ачивок/уровней. Вернёмся вместе с самой геймификацией —
  тогда же добавим запись инкремента в `bot_reactions.on_message`.
- [x] **E9.4.** (2026-05-22) Frontend: `api/admin.ts::BotReactionsSettings` —
  `{mention_enabled, reply_all_enabled, reply_except_phrases_enabled}`. `ScheduledPublicationsScreen.tsx`
  → секция `BotReactionsSection` с тремя `Switch`-тоглами и подсказками. Auto-save на каждое
  изменение (debounce не нужен — три булева флага, не количественные поля). Backend
  `routes_admin.py` — `BotReactionsIO` обновлён под новые ключи.
- **Bot pause sync.** `services/bot_pause.py::apply_pause_overrides` теперь выключает оба
  reply-тогла (`reply_all_enabled=false`, `reply_except_phrases_enabled=false`), при restore из
  snapshot пользовательские значения возвращаются. `test_bot_pause.py` обновлён.

#### E11. /zaebal, /zaebal-vote, авто-zaebal, snapshot/restore (источник: п.11)
- [ ] **E11.1.** Backend: новая таблица `bot_pause` (id, started_at, ends_at NULL, started_by_tg_id,
  reason ENUM('manual_admin','zaebal_threshold','zaebal_vote','auto_monthly'), settings_snapshot JSONB).
  Миграция.
- [ ] **E11.2.** Backend `bot/handlers/zaebal.py`:
  - `/zaebal` — фиксирует голос юзера (буфер на 1 час, ring-buffer в admin_config или таблица
    `zaebal_votes`). Когда набирается `>= zaebal.threshold` (default 2 из 5) — стартует пауза на
    `zaebal.duration_days` (default 3). В чат — сообщение с прощальной фразой (random из массива).
  - `/zaebal-vote` — создаёт Telegram-полл «GHG Bot - zaebal?», `open_period = zaebal.poll_hours * 3600`.
    После закрытия — если большинство «за», пауза на `zaebal.vote_duration_days` (default 7).
- [ ] **E11.3.** Backend `scheduler.py`: job `JOB_AUTO_ZAEBAL` — между 15-18 числами раз в месяц
  (cron-like), default-on. При срабатывании — публикует «дружеский» зэбал-вот от лица бота.
  Master-toggle `zaebal.auto_enabled`, поле `zaebal.auto_max_per_month` (default 1), интервал — env.
- [ ] **E11.4.** Backend: при старте паузы — снэпшот всех master-toggles (reminders/loser/phrases/avatars/
  birthdays/chukhan/bot_reactions/zaebal.auto) и интервалов в `bot_pause.settings_snapshot`. Все ключи
  выставляются в false. По истечении (или ручному снятию) — restore из snapshot.
- [ ] **E11.5.** Backend: личка старшему админу (Серж-Neo, ADMIN_TG_IDS[0]) — `bot.send_message`
  с уведомлением о начале паузы. Лог + повторная попытка через 60с при FloodWait.
- [ ] **E11.6.** Backend: реверс — `POST /admin/bot-pause/start` (`{duration_days?, reason?}`), `POST
  /admin/bot-pause/stop`. Те же snapshot/restore, что и в E11.4.
- [ ] **E11.7.** Frontend `AdminScreen`: при активной паузе — sticky-плашка наверху раздела с
  «Бот на паузе. Возобновится через Xд Yч» (живой таймер на `setInterval(1000)`) + кнопка
  `▶️ Снять паузу`. Все master-toggle ниже — disabled (`opacity-50`, `pointer-events-none`).
- [ ] **E11.8.** Frontend: рядом с плашкой паузы — кнопка `⏸ Поставить бота на паузу` (когда паузы
  нет) с модалкой «Длительность: [N дней / Бессрочно]» + причина (опц.).
- [ ] **E11.9.** Тест: `tests/test_bot_pause.py` (5 кейсов: старт, snapshot, истечение → restore,
  ручное снятие → restore, повторный старт пока активна — отказ).

### Sync
- [~] **D-E.** После закрытия каждой подгруппы E-P0/E-P1/E-P2 — `cp meetup-planner-main/backend/* →
  meetup-planner-backend/`, отдельные коммиты «GHG6 E-P0: …», «GHG6 E-P1: …», «GHG6 E-P2: …».
  Frontend синхронизируется пользователем сам.
  - (2026-05-22, частично) Для E5 синхронизировано в `meetup-planner-backend/`:
    `app/api/routes_admin.py`, `app/services/phrase_weights.py`, `app/services/admin_config.py`,
    `app/services/loser.py`, `app/services/chukhan.py`. Заодно дотащены `app/api/routes_calendar.py`
    (BD4) и `app/bot/handlers/chat_commands.py`, которые отставали от main. Backend-тесты 61/61 ✅.
    Остаются недосинкнутые в HF-клоне `app/bot/scheduler.py` (compose_loser_message), `app/db/models.py`
    (WormAssignment) и миграция `alembic/versions/0008_worm_assignments.py` — это хвосты E8/AD,
    их пользователь подтянет следующим коммитом. Push в HF / Pages — за пользователем.
  - (2026-05-22, частично) Для E7 синхронизировано: `app/api/routes_users.py`,
    `app/services/admin_config.py` (уже выше). Frontend: `src/api/availability.ts`, `src/App.tsx` —
    через `kickmesc-dotcom/meetup-planner` пользователем.
  - (2026-05-22, частично) Для E8.4 синхронизировано: `app/api/routes_calendar.py` (фикс
    префикса `/worm/current`). Frontend: `src/api/birthdays.ts`, `src/features/calendar/CalendarView.tsx`,
    `src/features/calendar/ParticipantRow.tsx`, `src/features/calendar/views/StripView.tsx`,
    `src/features/calendar/views/TimelineView.tsx`.
  - (2026-05-22, частично) Для E10 синхронизировано: `app/api/routes_admin.py`,
    `app/services/admin_config.py`, `app/services/avatars.py`. Frontend: `src/api/admin.ts`,
    `src/features/admin/ScheduledPublicationsScreen.tsx`. Остатки E-P1/P2 (E9, E11, E6).
  - (2026-05-22) Для E9 синхронизировано в `meetup-planner-backend/`:
    `app/bot/handlers/bot_reactions.py`, `app/services/admin_config.py`,
    `app/api/routes_admin.py`, `app/services/bot_pause.py`, `tests/test_bot_pause.py`.
    71/71 backend-тест зелёный. Frontend (`src/api/admin.ts`,
    `src/features/admin/ScheduledPublicationsScreen.tsx`) — через `kickmesc-dotcom/meetup-planner`
    пользователем. Push в HF / Pages — за пользователем.

---


## ДОбавлено пользователем (приоритетные правки внести до начала работы с P3)
1. Попробовал подобавлять еще прокси, ни один из них не закинулся. Закралось подозрение что может быть у них там какая-то защита появилась чтобы могли только живые люди подрубаться. Пока еще работает всего один (самый первый добавленный в раннем билде), но это как-то ненадежно, ибо нет даже плана б (на случай если текущий отвалится)
2. Проблема прыгающего экрана пофиксилась во всех полях ввода, однако именно при добавлении прокси - сохранилась.
3. После добавления функционла прокси мы больше не сталкивались с проблемой тайм-аута телеги, НО. Если делать ролл лоха по кнопке (где крутится рулетка) - там чаще (возможно всегда) рулетка крутится слишком долго, как будто зависая и потом выдает telegram error. Это даже не связано с кулдауном, я выжидал легитимные 12 часов. А вот там где принудительный реролл чухана, игнорирующий кулдаун через админка-лох, он выбирается исправно и ни разу не завис.
4. Шизо-цитатник работает весьма криво, в 70% случаев (например цитаты пользователя Русланище) он дважды или трижды повторяет одну и ту же сказанную фразу в одном сообщении с незначительным изменением формулировки. Нужно вшить какой-то протекшен, чтобы одна фраза бралась только один раз.
5. В целом я надобавлял такой огромный пул кастомных фраз на лоха недели и чухана, но уже который раз подряд в сообщении выпадает повторка. Здесь бы тоже было неплохо внедрить систему, по которой уже использованная фраза будет иметь приоритет ниже (но не нулевой) чем свеженькие и использованные меньшее кол-во раз.
6. У нас на днях возникло предложение собраться вместе и поиграть в игру, у всех разные варианты. Хочу добавить команду \nominate_game и \remove_nominated_game где командой или в админке можно добавить кастомное кол-во игр в предложку (пусть будет до 10 шт на начальном этапе), потом отдельной кнопкой запустить голсование типа "Во что сыграем" с опциональной возможностью докинуть последующий воут "Когда играем". В админке можно смотреть\редактировать лист номинированных игр. Для голосований по играм можно посмотреть количество голосов и кто за что проголосовал (вроде как стоковый телеграм и так позволяет это видеть), только таймаут опроса должен быть по дефолту не час, а хотя бы часов 12-24. Сами намеченные игры тоже можно добавлять на календарик, раз уж имеется такой функционал.
7. По умолчанию при входе в приложение у нас открывается вид календаря, он честно говоря и так уже чутка перегружен, из-за количества кнопок быстрых действий. А вверху висит приветствие "Привет, Серж-Neo", которое не несет особой смысловой нагрузки, но съедает лишнее место на экране. Хочу чтобы оно было закрываемым, в формате "не показывать в следующий раз" и эту настроечку сохраняем персонально для каждого пользователя. Совсем удалять блок приветствия не хочу, поскольку сюда мы будем добавлять фичи редактирования профиля в будущем.
Система будет в будущем расти и перенастраиваться, но пока такой вектор наметим. Весь функционал по прокачке\левелам\рангам можно приостановить одним рубильником в админке.
8. Особая номинация (червь-пидор) - при прокрутке лоха есть редкий шанс (1 к 100) что вместо лоха участник будет назначен червем-пидором, об этом нужно яркое оповещение в чат и супер ачивка в профиль (в счетчик лохов добавляется просто как +1 лох). В календаре пользователь отмечен особой иконкой у всех. Червь-пидор это переходящее звание и при выборе нового червя, у старого забирают звание, возвращая то которое полагается из расчета его текущего левела\экспы.
9. Еще фишки:
Если тегнуть бота в сообщении через @ - отвечает рандом фразой. (отключаемо в админке, по умолчанию вкл)
Если ответить на любое сообщение бота реплаем - отвечает рандом фразой. (отключаемо в админке, по умолчанию выкл)
Если ответить на любое сообщение бота реплаем, кроме рандом цитаты - отвечает еще одной рандом фразой. (отключаемо в админке, по умолчанию вкл)
10. такую фишку как авто-синхрон аватарок по расписанию упраздняем, теперь это можно сделать принудительно по нажатию кнопки или запланировать на определенную дату\время (но делать это регулярно и на ежедневной\еженедельной основе точно нет нужды пока)
11. чат команда /zaebal - бот с сожалением сообщает в чат что скорее всего его активность поднадоела участнику %username% но честно уведомляет что если кто-то еще напишет команду и наберется x голосов (по умолчанию 2 из 5 живых участников), то вся чат-активность (автопост цитат, реакции, автолох, чухан) бота будет приостановлена на z дней (по умолчанию 3). Еще есть /zaebal-vote - которая сразу создает опрос "GHG Bot - zaebal?" и если большинство проголосовало за, то активность бота выключается уже на Y дней (по умолчанию 7). Где-то к середине месяца, между 15-18 числами, бот может сам инициировать от себя /zaebal-vote (с чуть другим оформлением, как от своего лица в духе "Друзьяшечки братушечки, отвечаем только честно - заебал?"). Автозаеб - отключаемая в настройках функция, количество раз в месяц можно задать, интервал для забного периода - можно задать. Если по итогам голосования бот был отключен, то он откидывает в общий чат прощальное сообщение в духе "I'll be back" "Я вернусь, сучки" "И ты, брут" и метку что активность возобновится через x дней y часов. Параллельно он должен отписаться в личку старшему админу (Серж-Neo) что была инициирована приостановка. Да, перед началом приостановки нужно сделать как бы снэпшот того какие галочки были включены, а какие выключены, где стояли какие интервалы и значения - чтобы автоматически все вернуть по истечению таймера паузы, или ручном снятии паузы. На период действия приостановки, все ручные "включатели" фишек автопостинга в админке - помечены серым и неинтерактивны. В самом верху раздела настроек - плашка о том что сейчас действует приостановка и там же бежит живой таймер показыающий через сколько она закончится. Прямо под ней - глобальный тумблерок, который позволит снять паузу вручную. Раз уж такое дело, давай сделаем и реверс фичу, чтобы можно было прямо с этой же кнопки в админке инициировать глобальную приостановку всех функций отправки сообщений от бота в общий чат. Можно так же задать таймер, через сколько блок снимется автоматом. Если таймер не задан, то блокировка бессрочная, до тех пор, пока не будет снята вручную админом или участником имеющим доступ в админку (по умолчанию все могут).
13. Добавлено. Когда юзер номинирует игру - нужен вывод о том что юзером была предожена игра такая-то, в текущем листе номинаций следующие игры "список". /nominate_game - слишком громоздко, давай изменим на /nominate

Обрыв сессии, я скопировал последнее содержимое окна claude:
  Теперь — тест E8.5. Создаю tests/test_worm_assignment.py.

  Read 1 file, listed 1 directory (ctrl+o to expand)

● Чистый юнит-тест по чистым функциям — тест с сессией DB их паттерн не использует. Для roll_loser нужен async-тест с
  sqlite/in-memory. Глянем, есть ли conftest:

  Listed 1 directory (ctrl+o to expand)

● (Игнорирую.) Нет conftest, async-тестов с sqlite нет — паттерн проекта чисто юнит на чистых функциях. Не буду тащить
  sqlite-инфраструктуру ради одного теста — это инвазивно. Вместо этого вынесу решение «червь» в чистую функцию
  decide_worm(now_random, enabled, chance) (тестабельная), а интеграцию с БД не тестирую отдельно (но руками проверится
  при первом ролле — это не критичная часть, она простая).

● Update(meetup-planner-main\backend\app\services\loser.py)
  ⎿  Added 12 lines
      211      )
      212
      213
      214 +def decide_worm(*, enabled: bool, chance: float, rng_value: float) -> bool:
      215 +    """Чистая функция: выпадает ли «червь-пидор»?
      216 +
      217 +    `rng_value` — число из `random.random()` (0 ≤ v < 1). Триггер: enabled AND
      218 +    chance > 0 AND rng_value < chance. Шанс ≤0 — никогда; ≥1 — всегда (clamp
      219 +    хранится при записи, здесь только сравнение). Возвращает bool.
      220 +    """
      221 +    if not enabled or chance <= 0.0:
      222 +        return False
      223 +    return rng_value < chance
      224 +
      225 +
      226  def compose_loser_message(
      227      *,
      228      loser_name: str,

● И использую decide_worm в roll_loser:

● Update(meetup-planner-main\backend\app\services\loser.py)
  ⎿  Added 3 lines, removed 1 line
      133      # E8: бросаем «червь-пидор»
      134      worm_enabled = await is_worm_enabled(session)
      135      worm_chance = await get_worm_chance(session) if worm_enabled else 0.0
      136 -    is_worm = worm_enabled and worm_chance > 0.0 and random.random() < worm_chance
      136 +    is_worm = decide_worm(
      137 +        enabled=worm_enabled, chance=worm_chance, rng_value=random.random()
      138 +    )
      139
      140      if is_worm:
      141          reason = WORM_REASON_TEXT

● И аналогично для compose_loser_message — пишу тесты обоих:

● Write(meetup-planner-main\backend\tests\test_worm.py)
  ⎿  Wrote 104 lines to meetup-planner-main\backend\tests\test_worm.py
       1 """GHG6 E8 — «Червь-пидор»: чистая логика broska/композиции сообщения.
       2
       3 Интеграция с БД (создание `WormAssignment`, закрытие предыдущего, partial
       4 unique index) проверяется руками при первом ролле — отдельный sqlite-стенд
       5 в проект не тащим (его нет для других сервисов). Здесь — только декомпозируемая
       6 часть: `decide_worm` и `compose_loser_message`.
       7 """
       8 from __future__ import annotations
       9
      10 from app.services.loser import (
     … +94 lines (ctrl+o to expand)
  ⎿  API Error: 400 You have exceeded your daily token limit. You can resume at 2026-05-22 00:00 UTC.

✻ Cogitated for 30m 47s
