# Meetup Planner — чеклист GHG5

Источник: `C:\Users\fa1nt\GHG5.txt`. Дата старта: 2026-05-16.
Single source of truth: `C:\Users\fa1nt\meetup-planner-main`.
После каждого крупного блока — копия `backend/` → `C:\Users\fa1nt\meetup-planner-backend`.
Frontend синхронизирует пользователь сам в `kickmesc-dotcom/meetup-planner` (Pages).

Легенда: `[ ]` — не сделано, `[~]` — в работе, `[x]` — закрыто (с пометкой даты).
Приоритет: P0 > P1 > P2 > P3.

---

## P0 — критичные баги (то, что у юзера НЕ работает прямо сейчас)

- [x] **L1.** (2026-05-16) `routes_meetings.py::loser_roll_endpoint` — `asyncio.wait_for(send_message, 15s)`, отдельные обработчики `TelegramRetryAfter`/`TelegramForbiddenError`/`TelegramNetworkError`/`asyncio.TimeoutError`/`TelegramAPIError` с понятными `detail` (`telegram_retry_after:N`, `telegram_forbidden`, `telegram_network_timeout`, `telegram_api_error:Class`). Структ-лог `loser.rolled_ok` с `total_ms` и `send_ms` для диагностики. Frontend `api/client.ts` — `humanizeApiError()` переводит detail в русский текст. `tg/webapp.ts` — `showAlert()` helper. `LoserSheet.tsx` использует `humanizeApiError` + `showAlert` на сетевых ошибках, `haptic("success")`/`haptic("error")` на финале мутации. Backend синхронизирован.

- [x] **L2.** (2026-05-16) Закрыт фиксом L1: фронтовый LoserSheet получает 504 с `telegram_network_timeout` максимум через 15s (бэк больше не висит 30+с), на onError — `humanizeApiError()` + `showAlert()` с понятным русским текстом, haptic("error"). Отдельной админской «прокрутки лоха» нет — `forceReroll` в `api/admin.ts` относится к чухану, не лоху.

- [x] **BD-CAL1.** (2026-05-16) Новый публичный endpoint `GET /api/birthdays/calendar?from=&to=` (`routes_birthdays.py`) возвращает массив `{user_id, display_name, date, bday, year_known}` для всех ДР, попадающих в окно (29.02 в невис. году → 28.02). Подключён в `main.py`. Frontend: `api/birthdays.ts`, `CalendarView.tsx` подтягивает `fetchBirthdaysInWindow` (staleTime 10s), пробрасывает в `MonthView`/`StripView`. В обоих видах в углу дня рисуется 🎂 с tooltip с именами. `BirthdaysScreen.tsx` после сохранения invalidate-нет `["birthdays"]` — др-шка появляется в календаре сразу же. Backend синхронизирован.

- [x] **CAL1.** (2026-05-16) `ParticipantRow.tsx`: контейнер пилюль `overflow-hidden [contain:layout_paint]` — пилюли больше не выходят за свою клетку строки даже во время framer-motion layout-анимаций. Ячейки получили явные `border-r border-tg-secondary-bg/70` (последняя без, чтоб не сдваивалось с правой границей контейнера) — видны как клетки, а не полосы. `StripView.tsx`: header дней получил такие же вертикальные границы — выровнено с строками. `overflow-x: hidden` на `.calendar-pan-container` и `touch-action: pan-y` остались.

- [x] **POLL-HOURS1.** (2026-05-16) Backend: `admin_config.POLL_TIME_PRESETS_KEY` + `get/set_poll_time_presets` + дефолты `12-15/15-18/18-20/20-23`. `auto_pick.find_best_slots` принимает `presets=[{"start","end"}]` и строит кандидаты как `день × пресет` вместо `cursor += step`. Схемы `AutoPickRequest`/`PollAutoPickRequest` имеют `use_presets: bool = True`. `/api/meetings/auto-pick` и `/api/polls/auto-pick` подтягивают presets из admin_config. Public `GET /api/poll-presets` (whitelist-only) + admin `GET/PUT /api/admin/poll-presets` в `routes_admin.py`. Frontend: `api/admin.ts` хелперы, новый `PollPresetsScreen.tsx` (редактор `HH:MM→HH:MM`, +/✕/↻ дефолт) подключён в `AdminScreen` карточкой 🕒. `AutoPickSheet`: убран select длительности, показан текущий список пресетов с подсказкой «меняются в админке». `PollSheet`: дефолтные опции стартуют с первого пресета, под каждым input — chip-кнопки `12:00–15:00` ... для быстрого выбора. Backend синхронизирован.

## P0.5 — синхронизация и деплой

- [x] **D1.** (2026-05-16) После каждого закрытого блока P0 (L1, BD-CAL1, POLL-HOURS1) синхронизирован `meetup-planner-main/backend/app` → `meetup-planner-backend/app`. P1 — только фронт, sync не требуется.
- [x] **D2.** (2026-05-17) В `DEPLOY_NOTES.md` добавлен блок «GHG5 (2026-05-17)» с инструкциями по P0/P1/P2: какие файлы, какие env-переменные (`SMART_PROXY_ENABLED`, `PROXIES_BOOTSTRAP_JSON`, `PROXY_DEAD_COOLDOWN_MIN`, `PROXY_MAX_ATTEMPTS`, `PROXY_MIN_SWITCH_INTERVAL_SEC`), миграция `0007_proxies`, новая зависимость `aiohttp-socks==0.10.1`, чек-лист проверки после деплоя.

## P1 — UI/UX (контраст + Optimistic UI + Haptic, GHG5 Task 2)

- [x] **U1.** (2026-05-17) Снят глобальный `input,textarea,select { color:#000 !important; bg:#fff !important }` из `frontend/src/styles.css` — переписан на `var(--tg-theme-text-color)` / `var(--tg-theme-secondary-bg-color)` + `color-scheme: light dark` для date/time inputs. Добавлены глобальные классы `.chk-tg` (checkbox: рамка 2px tg-hint в idle, заливка tg-link с белой галкой в checked, активная анимация scale) и `.tgl-tg` (toggle-slider 44×26 с белой ручкой, фон tg-hint→tg-link при checked). WCAG AA контраст сохранён в обеих темах.

- [x] **U2.** (2026-05-17) Созданы переиспользуемые компоненты `components/Checkbox.tsx` — `<Checkbox>` (на `.chk-tg`, опциональный label, размер sm/md) и `<Toggle>` (на `.tgl-tg`, опциональный label со строкой active/inactive подсветкой). Оба тригерят `haptic("selection")` на onChange. Применены: AutoLoser enabled toggle, Birthdays year_known + 5 toggle-ов напоминаний, RandomPhrasesSchedule enabled toggle. Кастомные локальные `Toggle` удалены.

- [x] **U3.** (2026-05-17) Optimistic update через `onMutate`/`onError revert` добавлен:
  - `AutoLoserScreen.save` — пишет в `["admin","autoloser"]` сразу.
  - `RandomPhrasesScheduleScreen.setEnabled` — пишет в `["admin","phrases"]` сразу.
  - Birthdays — drafts уже хранятся локально, отдельный optimistic не нужен.
  Остальные мутации (saveReasons, schedule, generator, setW) — server-of-truth с invalidate после success, что корректно для batch-форм.

- [x] **U4.** (2026-05-17) Haptic patterns причёсаны:
  - `haptic("selection")` — toggle/checkbox onChange (внутри Toggle/Checkbox).
  - `haptic("medium")` — action-кнопки 💾 Сохранить / Перевыбрать / Сохранить расписание / mutate в LoserSheet (уже было).
  - `haptic("success")` — все onSuccess мутаций (замена с "light" на "success" в Chukhan/AutoLoser/RPSchedule/Generator).
  - `haptic("error")` — все onError.
  - `haptic("warning")` — удаление элементов из списков.

- [x] **U5.** (2026-05-17) Spinner. Новый `components/Spinner.tsx` (CSS-only, currentColor, размер 14px по умолчанию) подключён в pending-состоянии всех Save-кнопок: AutoLoser, Birthdays, RPSchedule, RPGenerator, PollPresets, ChukhanLoser (reroll + reasons). Кнопка прижата `inline-flex items-center justify-center gap-2`, форма в целом не блокируется.

- [x] **U6.** (2026-05-17) `showAlert(humanizeApiError(e))` на onError добавлен в: AutoLoser, Birthdays, RPSchedule (оба mutation), RPGenerator, Chukhan/Loser (setW/resetW/reroll/saveReasons), ScheduledPublications (setTick/cancelJob/closePoll/removePoll — через общий хелпер `errAlert`). PollPresets и Loser/PollSheet/AutoPickSheet — `showAlert` уже был с P0.

## P2 — Smart Proxy & Networking (GHG5 Task 1)

- [x] **P-1.** (2026-05-17) `app/services/proxies.py` с синглтоном `_state` (ProxyManager), enum `ProxyMode = ALWAYS_ON | ALWAYS_OFF | AUTO_FALLBACK` (default AUTO_FALLBACK), dataclass `ProxyRecord` (id/server/port/type/secret/enabled/fail_count/last_ok_at/last_fail_at/dead_until + `is_alive(now)`). ORM-модель `ProxyEntry` в `app/db/models.py`.

- [x] **P-2.** (2026-05-17) `_IPv4AiohttpSession` в `app/bot/dispatcher.py` переписан: переопределён `make_request`, ловит `ClientConnectorError|ClientOSError|ServerDisconnectedError|asyncio.TimeoutError`, ретраит до `MAX_ATTEMPTS_PER_REQUEST` (3 по умолчанию), между переключениями ≥`MIN_SWITCH_INTERVAL_SEC` (5с). На фейле зовёт `mark_proxy_failed` → `dead_until = now + PROXY_DEAD_COOLDOWN_MIN`. SOCKS5/HTTP прокси подключаются через `aiohttp-socks` (`ProxyConnector`). MTProto прокси сохраняются, но в HTTP-сессии не используются (Bot API ходит через HTTPS — MTProto несовместим). Env-кнопка отключения: `SMART_PROXY_ENABLED=0`.

- [x] **P-3.** (2026-05-17) Миграция `0007_proxies.py` + модель `ProxyEntry` (uq_proxy_server_port, ix_proxy_enabled_dead). Сидинг пустой, наполнение через `PROXIES_BOOTSTRAP_JSON` (см. `bootstrap_from_env`) или admin-API. Bootstrap зовётся в `lifespan` `main.py`.

- [~] **P-4.** Парсер @ProxyMTProto-каналов — **отложен в P3** (решение 2026-05-16: MVP ограничивается ручным/env наполнением). MTProto-прокси не годятся для бот-сессии всё равно, так что без user-session парсера нет смысла.

- [x] **P-5.** (2026-05-17) `admin_config` ключ `proxy.mode` через `get_proxy_mode/set_proxy_mode`. Endpoints: `GET/PUT /api/admin/proxy/mode`, `GET /api/admin/proxy`, `POST /api/admin/proxy` (upsert по server+port), `PUT /api/admin/proxy/{id}` (enabled toggle), `DELETE /api/admin/proxy/{id}`. Все admin-only. Frontend: `frontend/src/api/admin.ts` хелперы, новый экран `ProxyScreen.tsx` (выбор режима, список с toggle/delete, форма «+ добавить» server/port/type/secret). Карточка 🌐 «Прокси» в AdminScreen.

- [x] **P-6.** (2026-05-17) Реализовано в `_IPv4AiohttpSession.make_request`: счётчик попыток ≤3, проверка `can_switch()` на `MIN_SWITCH_INTERVAL_SEC=5`, `mark_switch()` после каждого пересоздания сессии. Round-robin курсор в `_state.cursor`.

- [x] **P-7.** (2026-05-17) `set_proxy_mode` зовёт `invalidate()` (обнуляет `_state.loaded_at`). Кэш пула также имеет TTL `POOL_TTL_SECONDS=30` — следующий запрос гарантированно перечитает БД. CRUD прокси тоже invalidate-ит кэш.

## P3 — Авто-парсер прокси из MTProto-каналов (ОТЛОЖЕНО по решению 2026-05-16)

- ~~P-AUTO.~~ Telethon с user-session — **не делаем сейчас**. Решено держаться MVP: ручное добавление + env-bootstrap. Парсер @ProxyMTProto можно поднять позже отдельной фичей.

---

## Процедура

1. Беру верхний незакрытый пункт.
2. Меняю код в `meetup-planner-main/`.
3. По завершении блока — копирую backend в `meetup-planner-backend/`.
4. Отмечаю `[x] (YYYY-MM-DD) краткая заметка о решении`.
5. На случай обрыва — следующая сессия читает этот файл и продолжает с первого `[ ]`.

## Журнал решений

(заполняется по мере закрытия пунктов)
