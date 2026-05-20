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

- [ ] **CL1.** `frontend/src/features/calendar/views/TimelineView.tsx`:
  - `ParticipantColumn` (sticky-left, 6 строк по `WHITELIST_NAMES`, аватар+имя).
  - `TimelineGrid` (`overflow-x-auto`, `overflow-y-hidden`, 6 строк
    `ParticipantTimelineRow`, ширина = `days × cellWidth`).
  - `TimelineHeader` (sticky-top, синхрон по X через общий `scrollLeft` ref).
  - Этап 1 — жёсткий `cellWidth=56px`, окно ±21 день от `anchor`, без жестов,
    без зума, без confidence-заливки (`bg-tg-secondary-bg` пустой ячейки).
- [ ] **CL1.2.** Ветвление в `CalendarView.tsx`: `if (timelineEnabled) <TimelineView/>`,
  иначе текущий switch по zoom. NavBar/ZoomController гасятся для нового вида —
  у TimelineView собственная нижняя плашка (этап 2).

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
