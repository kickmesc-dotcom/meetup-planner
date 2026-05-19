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

Это переработка `CalendarView` и связанных компонентов. Поэтому P3 — последний.
Подзадачи разбить ещё внутри, ниже — крупными мазками. Как будто на будущее было бы неплохо еще добавить возможность в админке принудительно переключить бота на рудиментарный вид календаря (исключение - убрать режим отображения 2 недели и сделать по умолчанию "неделя"). После внедрения нового вида, для тестовых прогонов пока оставляем его стандартным - этот пункт добавить к чеклисту, ДО внедрения новго режима отображения. Подружить оба варианта отображения между собой, чтобы ничего не конфликтовало и не падало на уже релизнутых билдах.

### Архитектура
- [ ] **CL1.** Новый компонент `TimelineView.tsx`:
  - Слева — `ParticipantColumn` (фиксированная, нескрываемая, 6 строк в порядке из `WHITELIST_NAMES`).
  - Справа — горизонтально-скроллируемая зона. Каждая строка = `ParticipantTimelineRow` (`overflow: hidden`, ширина = `days × cellWidth`).
  - Header сверху над таймлайн-зоной (синхронно скроллится по X).
- [ ] **CL2.** Виртуализация (опционально для MVP): рендерить ±N дней от текущего, при скролле подгружать.
- [ ] **CL3.** Жесты: `pointermove` с инерцией (request-animation-frame-based), магнит к ближайшему дню после `pointerup`. У краёв (15% ширины с каждой стороны) — автоскролл (`requestAnimationFrame` loop, скорость = функция расстояния пальца от края).
- [ ] **CL4.** Motion blur во время быстрой прокрутки: CSS-фильтр `filter: blur(...)` пропорционально |velocity|, снимать при остановке.
- [ ] **CL5.** Слайдер зума (диапазон cellWidth 24px…120px), плавная анимация изменения через `framer-motion`. Привязать «дни/неделя/месяц/год/все года» к пресетам слайдера.
- [ ] **CL6.** Дефолтное состояние: cellWidth ≈ `containerWidth / 7.4` (неделя + хвосты). Кнопка «📍 К сегодня» — анимация `scroll-to` с центрированием.

### Ячейка
- [ ] **CL7.** Заливка ячейки по `confidence` (5 уровней) — пропорция высоты ячейки + цвет (точно нет = красный сплошной, скорее нет = красный 60%, неизвестно = серый, скорее да = зелёный 60%, точно да = зелёный сплошной).
- [ ] **CL8.** Bottom-sheet (`RangeEditorSheet.tsx` — переделать): радио занят/свободен/под вопросом, слайдер уверенности (5 stops), чекбокс «Конкретное время» → time-from/time-to (на pickerах часов/минут). Дефолт уверенности зависит от выбранного статуса (свободен → точно да, занят → точно нет, под вопросом → неизвестно).
- [ ] **CL9.** Если задан временной диапазон, ячейка рисует частичную заливку (горизонтальная полоса по доле дня) + иконка 🕓.
- [ ] **CL10.** Сохранение на бэк: расширить модель `Availability` полем `confidence` (int 1..5, default 3) и опциональными `time_from`/`time_to`. Миграция alembic `0008_availability_confidence_time.py`.
- [ ] **CL11.** API: `routes_availability.py::PUT /api/availability/{date}` принимает `{status, confidence, time_from?, time_to?}`.

### Режимы
- [ ] **CL12.** Удалить режим «2 недели» (или переименовать в «Произвольный диапазон» с пользовательским пресетом). По умолчанию — «Неделя».
- [ ] **CL13.** Стрелки `←` / `→`, селектор режима (день/неделя/месяц/год/все года), слайдер зума, «📍 К сегодня» — собрать в нижнюю/верхнюю плашку.

### Sync
- [ ] **D-P3.** Копия backend (миграция!). Этапная — сделать после CL1–CL11.

---

## D — пост-релиз

- [ ] **D-FINAL.** Обновить `DEPLOY_NOTES.md` — раздел «GHG6 (дата)»: какие env-переменные новые (`PROXY_HEALTH_INTERVAL_SEC`, `SELFTEST_CHAT_ID?`), миграции (`0008_availability_confidence_time`), новые admin_config ключи (список из AD6).
- [ ] **D-MEM.** Обновить память `project_meetup_planner_deployed.md`: топология теперь без `meetup-planner-frontend`.
