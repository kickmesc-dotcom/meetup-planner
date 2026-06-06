# Meetup Planner — чеклист GHG8

Преемник `CHECKLIST_GHG7.md` (тот оставлен как архив релиза P0–P10, задеплоен
2026-06-01). Здесь — только то, что **предстоит сделать**: незакрытый план из
GHG7 + прод-фидбек от 03.05.26 (был дописан в хвост GHG7 как пункты 1–10).

Single source of truth: `C:\Users\fa1nt\meetup-planner-main` (монорепо
`backend/` + `frontend/`). После правок `backend/` —
`cp backend/* → C:\Users\fa1nt\meetup-planner-backend\` (отдельный git remote →
HF Space). Frontend пользователь синхронизирует сам в
`kickmesc-dotcom/meetup-planner` (Pages). Push в HF/GitHub делает ассистент
(git PAT) ИЛИ пользователь — фиксируется в каждом sync-подэтапе.

## Легенда статусов
- `[ ]` — не начато
- `[~]` — в работе (был обрыв или ждём чего-то)
- `[x]` — закрыто

## Правила работы с чеклистом (как в GHG7)
1. Этапы разбиты на нумерованные подэтапы `PX.Y`, при необходимости — `PX.Y.a`.
2. После закрытия подэтапа — `[x]` + однострочная пометка
   `(YYYY-MM-DD) <что сделано> — <ключевой файл/коммит>`.
3. Sync `backend/` → `meetup-planner-backend/` — отдельный подэтап с галкой.
4. Обрыв → `[~]` с пометкой, на каком файле/шаге остановились.
5. Investigate-пункты (`INV-N`) не «фиксят», а отвечают на вопрос и при
   необходимости порождают follow-up подэтапы. `INV-N` закрывается выводом +
   ссылкой на созданные подэтапы.

---

## Контекст из GHG7 (что уже сделано — кратко, для ориентира)

Задеплоено в релизе GHG7 (HF `cf79c18`, Pages `773f688`, 2026-06-01):
- **P0** — баги доставки: автолох через outbox+retry, копилка фраз
  (пропагация роутеров SkipHandler), healthcheck (двухступенчатый selftest).
- **P1** — чекбоксы (`.chk-tg`), `@gunghogunsbot` в командах, индикация
  `/zaebal`-паузы в `/help`.
- **P2.1/P2.2/P2.3/P2.5** — иконки-шапки, уведомления о паузе/разморозке,
  реорганизация меню админки, UI-тогглер таймлайна.
- **P5** — реакции бота на медиа (бэк + админ-UI, хранение в `admin_config`).
- **P8** — прод-инцидент доставки лоха: env `LOSER_SEND_TIMEOUT` (25с),
  `PROXY_HEALTH_INTERVAL_SEC` (1ч), retry-job 1мин→5мин.
- **P9** — разделение семантики 👑 «Лох дня» (auto/manual) vs 🤡 «Автолох»
  (duel, не в статистику).
- **P10** — упрощение иконок-шапок (💩 чухан сверху, 🪱 червь снизу).

Детали и file:line — в `CHECKLIST_GHG7.md` (не удалять, архив).

---

## Q — прод-фидбек 03.05.26 (новое, приоритет — разобрать первым)

Источник: хвост `CHECKLIST_GHG7.md` (пункты 1–10), логи `incidentlog.txt`,
`memefail.txt`. Пронумеровано Q1–Q10 по исходным пунктам.

### Известные факты из логов (собрано 2026-06-04 при актуализации)

- **incidentlog.txt** (обрыв второй части поста чухана, Q2):
  - `asyncpg.exceptions.ConnectionDoesNotExistError: connection was closed in
    the middle of operation` (стр. 250) — Neon рвёт коннект посреди операции
    (`bot_pause_auto_restore` job, 09:13). Объясняет, почему «вторая часть
    поста отвалилась»: между двумя `send_message` коннект к БД/каналу гибнет.
  - Серия `webhook.set_failed` ×5 (`HTTP Client says - Request timeout error`)
    на старте + `bot.set_commands_failed`/`set_menu_button_failed`. Старт
    идёт через висящий канал, webhook ставится только с N-й попытки.
- **memefail.txt** (медиа-реакция не летит, Q7):
  - Каждый медиа-апдейт от TG → `aiogram.event: Update ... is not handled.
    Duration ~31–32 сек` + `webhook.handler_error` (exc_info=true), updates
    801770066–801770069. То есть **media-handler виснет на ~32с** (= таймаут
    сессии бота ~30с при throttling канала) и падает по таймауту, ответ в чат
    не уходит. Никаких `proxy`-свапов внутри хендлера НЕ происходит.
  - `tg.registration_gave_up` (стр. 92) — после 6 попыток webhook так и не
    встал в первом окне.
  - В логе НЕТ ни одной строки от media-подсистемы (force-эндпоинт,
    `set_message_reaction`) — значит force «не найдено» отрабатывает ДО сети
    (пустой `_recent` после рестарта Space, P5.2.b: in-memory store теряется).
- **Причины чухана не обновляются** (Q5): подтверждено чтением кода —
  `chukhan.py:241` берёт причины из `get_chukhan_reasons` →
  `admin_config[chukhan_reasons.list]` (`admin_config.py:538`). Дефолт из
  кода (`_DEFAULT_CHUKHAN_REASONS`, `admin_config.py:456`) подхватывается
  ТОЛЬКО если ключа в БД нет. Лох устроен идентично (`LOSER_REASONS_KEY`).
  Значит правки пользователя в `chukhan.py` (дефолт) игнорируются, пока в
  `admin_config` лежит старый список. Фронт читает через
  `GET /api/admin/chukhan-reasons` (виден в memefail.txt:51).

### Q-INV — расследования

- [x] **Q-INV-1 (Q5). Причины чухана: 6 старых, правки не видны.** (2026-06-04)
  Прямой коннект к Neon невозможен — прод `DATABASE_URL` в репо нет (только
  заглушка `.env.example`). Разрешено по коду: `_DEFAULT_CHUKHAN_REASONS`
  (`admin_config.py:456`) — это РОВНО 6 фраз = те самые «6 унылых из первого
  билда». `get_chukhan_reasons` читает `admin_config[chukhan_reasons.list]`
  через `_get_value` (прямой `session.get`, кеша процесса НЕТ), и при
  `None`/невалидном JSON/не-списке строк МОЛЧА фолбэчит на эти 6 дефолтов.
  Вывод: правка пользователя в Neon легла либо не под тот ключ, либо
  невалидным JSON (косяк с запятой) → тихий фолбэк маскировал ошибку под «6
  старых». Правка `chukhan.py` (дефолт) by design не применяется при наличии
  валидного ключа. У лоха правки «появились», т.к. он правил через UI
  (`set_loser_reasons` → валидный JSON). Follow-up: Q5.a/Q5.b закрыты ниже.
- [x] **Q-INV-2 (Q7). Медиа-реакция: handler виснет 32с, _recent эфемерен.**
  (2026-06-06) Подтверждено по коду: (а) `_send_emoji_reaction`/
  `_send_reply_phrase`/`_bot_id().me()` в `handlers/media_reactions.py` шли БЕЗ
  `asyncio.wait_for` — висели на 30с-таймауте сессии (`_IPv4AiohttpSession`,
  `dispatcher.py:253`), а `on_media`/`on_reaction` зовутся синхронно из
  `dp.feed_update` → webhook блокировался ~32с (memefail Duration). При
  таймауте внутри make_request прокси-ретраи были, но 3 попытки × 30с только
  усугубляли. (б) `_recent`/`_reacted` — module-level in-memory
  (`media_reactions.py:79-81`), рестарт Space обнуляет → force 404. Решение:
  и короткий таймаут, И persist (оба дёшевы). Follow-up: Q7.a–d закрыты ниже.
- [x] **Q-INV-3 (Q2). Обрыв второй части поста чухана.** (2026-06-04) Разрешён:
  «две части» = `_drumroll` (барабанная дробь, серия edit'ов, заканчивается
  «🎉 Имя 🎉») + основной пост. Основной пост виснул на таймауте сессии (нет
  обёртки wait_for) → в чате оставался огрызок дроби. Закрыто блоком **P11**
  (таймаут + удаление огрызка + retry недоставленного). Follow-up: P11.1–P11.8.

### Q5. Причины чухана не обновляются (КРИТ — данные/кеш)
- [x] **Q5.a.** (2026-06-05) Выбран вариант (1): кнопка в админ-UI «↩ Сбросить
  к дефолтам из кода» + read-only диагностика. Backend: `POST /admin/chukhan-
  reasons/reset` (`set_chukhan_reasons(_DEFAULT_CHUKHAN_REASONS)` → валидный
  JSON, вытесняет кривой/пустой ключ) и `GET /admin/chukhan-reasons/raw`
  (сырое значение + результат парсинга: `key_present`/`parse_ok`/`parsed_count`/
  `using_default`) — `routes_admin.py:1116,1154,1191`. Frontend:
  `ChukhanScreen.tsx` — блок «🔍 Диагностика» (показывает «активны дефолтные N
  фраз — невалидный JSON / ключ отсутствует» либо «кастомный список N фраз ✓»)
  + кнопка сброса с `showConfirm`. `admin.ts`: `fetchChukhanReasonsRaw`/
  `resetChukhanReasons`. Зафиксировано: правка `chukhan.py` (дефолт) в проде НЕ
  применяется при наличии валидного ключа — ожидаемо, не баг кода.
- [x] **Q5.b.** (2026-06-05) `get_chukhan_reasons` (`admin_config.py:541`):
  лог `chukhan_reasons.fallback_default` с `reason` (`key_missing`/
  `not_list_of_str`/`invalid_json`) + `raw_len`/`error`/`value_type` — раньше
  невалидный JSON глотался молча и маскировался под «6 старых фраз». Диагностика
  в проде теперь видна и в логах, и через `/raw`-эндпоинт.
- [x] **Q5.c.** (2026-06-05) Sync. Backend → HF-копия (`acc5f3b`), запушено в
  HF (`8fc7230`) + GitHub/Pages-source (`78f4af4`). pytest main и HF-копия
  220 passed, `npx tsc --noEmit` чист (baseline = 2 ошибки HistoryScreen, игнор).

### Q4. Чёрный непрозрачный фон у 💩-шапки (косметика) — ЗАКРЫТО
- [x] **Q4.a.** (2026-06-04) `ParticipantRow.tsx`: у 💩-бейджа (шапка, `-top-2`)
  и 🪱-бейджа (`-bottom-1`) убрана фон-плашка `bg-tg-bg rounded-full px-0.5
  shadow-sm` → читаемость через `[filter:drop-shadow(0_1px_1px_rgba(0,0,0,0.45))]`
  (как у 💩 в ячейках календаря — там фона нет). Правка была сделана прошлой
  сессией в рабочем дереве (метка «GHG7 P11 инцидент 03.06 #4»), но НЕ
  закоммичена/задеплоена — зафиксирована сейчас.
- [x] **Q4.b.** (2026-06-05) Sync. `ParticipantRow.tsx` в коммите `3dd3f2a`,
  запушен в GitHub/Pages-source (`78f4af4`). Pages пересоберётся автоматически.

### Q7. Реакции на медиа: не летят + история теряется при рестарте
- [x] **Q7.a.** (2026-06-06) `handlers/media_reactions.py`: `_media_send_timeout()`
  (env `LOSER_SEND_TIMEOUT`, дефолт 25с < 30с сессии — зеркало chukhan/
  routes_meetings); `set_message_reaction`, reply-`send_message` и `me()` в
  `_bot_id` обёрнуты в `asyncio.wait_for`. Фейл логируется (`emoji_failed`/
  `reply_failed`), апдейт не валится (try/except были и раньше — best-effort).
- [x] **Q7.b.** (2026-06-06) Persist в `admin_config` БЕЗ миграции (паттерн P5):
  ключ `media_reactions.recent_media` (JSON `{chat_id: {kind, message_id,
  author_name}}`, `admin_config.py`). `services/media_reactions.py`:
  `parse_recent_media` (чистый парсер, кривой JSON → `{}`),
  `get_recent_media_persisted`, `save_recent_media` (UPSERT одной строки).
  `_schedule_reaction` пишет best-effort (сбой Neon не ломает реакцию,
  лог `persist_recent_failed`). Нагрузка ≈ chat_capture (1 UPSERT на медиа).
- [x] **Q7.c.** (2026-06-06) Force-эндпоинт (`routes_admin.py`): при промахе
  in-memory — фолбэк на `get_recent_media_persisted`; если нет нигде — 404
  `no_recent_media`, который фронт (`client.ts:humanizeApiError`) теперь
  переводит в «Бот ещё не видел ни одного мема такого типа…» вместо
  «Не найдено».
- [x] **Q7.d.** (2026-06-06) Тесты: `tests/test_media_recent_persist.py` — 13
  новых (env-таймаут по паттерну test_loser_send_timeout_env; парсер: None/
  мусор/мульти-чат/частично-валидный/roundtrip формата save). Сьют **247
  passed** (было 234), tsc чист (baseline HistoryScreen). Sync: backend →
  HF-копия (247 passed), HF push `a4c74fa`; main + frontend (client.ts) →
  GitHub/Pages. **HF env-напоминание:** новых env НЕ требуется (переиспользован
  `LOSER_SEND_TIMEOUT`, persist — в `admin_config`).

### Q2 + Q1. Обрыв поста чухана / скип чухана — закрыто блоком P11
См. **P11** ниже. Q-INV-3 разрешён: «две части» = барабанная дробь
(`_drumroll`, серия edit'ов) + основной пост. При недоставке основного поста в
чате оставался огрызок дроби «🎉 Имя 🎉». Корень — отсутствие таймаута на send
(висел на 30с сессии при throttling) + откат пика (rollback) при фейле, из-за
чего чухан не повторялся до след. недели (Q1, инцидент #1). incidentlog.txt
подтверждает: `asyncpg.ConnectionDoesNotExistError` + `webhook.set_failed`.

## P11 — отказоустойчивость чухан-поста (инциденты 03.06 #1, #2, #4)

Работа прошлой сессии лежала в рабочем дереве НЕзакоммиченной (3 backend-файла
+ ParticipantRow). Доведена и зафиксирована 2026-06-04.

- [x] **P11.1.** (2026-06-04) `chukhan.py`: таймаут на send основного поста.
  `_chukhan_send_timeout()` (env `LOSER_SEND_TIMEOUT`, дефолт 25с < 30с сессии,
  зеркало `routes_meetings`), `send_photo`/`send_message` обёрнуты в
  `asyncio.wait_for`. Раньше обёртки не было — пост виснул на таймауте сессии.
- [x] **P11.2.** (2026-06-04) `chukhan.py`: `_drumroll` возвращает message_id;
  при недоставке основного поста дробь удаляется (`delete_message`), чтобы в
  чате не висел огрызок «🎉 Имя 🎉» (инцидент #2).
- [x] **P11.3.** (2026-06-04) `chukhan.py`: при фейле send пик НЕ откатывается
  (`session.commit()`, `posted_at` остаётся None) — раньше был `rollback`,
  из-за чего чухан терялся до след. недели (инцидент #1). `retry_undelivered_
  chukhan(bot)` ищет строку текущей недели с `posted_at IS NULL` и добивает
  доставку тем же юзером (идемпотентность `pick_chukhan_for_week` по week_start).
- [x] **P11.4.** (2026-06-04) `scheduler.py`: job `chukhan_retry`
  (IntervalTrigger 30мин, jitter 60, misfire_grace 30мин) зовёт
  `retry_undelivered_chukhan`. Дёшево для Neon: обычно один SELECT впустую.
- [x] **P11.5.** (2026-06-04) `main.py`: `_retry_undelivered_chukhan_on_startup`
  — фоновая задача в lifespan (backoff 30→480с, 5 попыток), дотягивает чухана
  при рестарте/redeploy Space. Завершение задачи добавлено в shutdown-цикл.
- [x] **P11.6.** (2026-06-04) **Фикс дыры контракта (мой).** P11.3 опирался на
  фильтр `posted_at IS NOT NULL`, но его НЕ было → недоставленный пик показался
  бы 💩 на календаре и в шапке. Добавлен `.where(posted_at.is_not(None))` в
  `routes_calendar.py`: `calendar_marks` (chukhan_rows) и `titles_current`
  (chukhan текущей недели). `posted_at` nullable (`models.py:320`) — фильтр
  валиден.
- [x] **P11.7.** (2026-06-04) Тесты: весь сьют **220 passed** (main и HF-копия).
  Новая БД-логика (retry/posted_at-фильтр) не покрыта юнит-тестом — async-БД-
  стенда в проекте нет (зафиксированное ограничение); `build_marks` принимает
  уже отфильтрованный список, его контракт прежний и зелёный.
- [x] **P11.8 sync** (2026-06-05) `meetup-planner-main/backend/` →
  `meetup-planner-backend/`: `chukhan.py`, `scheduler.py`, `main.py`,
  `routes_calendar.py`. HF-копия 220 passed. Запушено в HF (`8fc7230`) и в
  GitHub/Pages-source (`78f4af4`) вместе с Q5/Q-FIX.
  **HF env-напоминание:** P11 использует существующий `LOSER_SEND_TIMEOUT` —
  новых env НЕ требуется.

### Q-NET. Сетевая отказоустойчивость (Q8/Q9/Q10) — архитектура
Контекст: РКН душит прокси, всё идёт через direct; джобы зависают, помогает
свап proxy↔direct или смена VPN на телефоне; рестарт Space «расклинивает».
Пользователь просит **конкретные варианты на уровне Python-кода и архитектуры**
(пункт 10, направления а–г). НЕ трогать первый (зелёный) прокси (Q8).

> Это крупный блок. Сначала — план/INV с конкретными вариантами под наш стек
> (aiogram 3.x + aiohttp-сессия бота, APScheduler, FastAPI, HF Space webhook),
> потом разбивка на реализуемые подэтапы. Не начинать кодить до согласования.

#### Q-NET-INV: план (2026-06-06, по коду dispatcher.py/proxies.py)

**Диагноз «зависает, рестарт расклинивает»:** aiohttp `TCPConnector` держит
keep-alive-пул; при throttling РКН соединение полудохнет, но остаётся в пуле и
переиспользуется → каждый следующий запрос виснет на нём до 30с. Рестарт Space
= новый коннектор = «расклинило». Свап proxy↔direct помогает по той же причине:
`_swap_session` пересоздаёт `ClientSession` (dispatcher.py:101). ⇒ ядро решения —
**уметь пересоздавать сессию без рестарта и не дать дохлым keep-alive жить**.

- **(a) Circuit Breaker** — модуль `app/services/net_breaker.py`: счётчик
  последовательных сетевых фейлов в `make_request` (там уже ловятся
  ClientConnectorError/ClientOSError/ServerDisconnected/Timeout,
  dispatcher.py:167). N фейлов подряд (дефолт 3, admin_config) → «трип»:
  принудительный `_swap_session(текущий transport)` — пересборка ClientSession
  с тем же путём (направление НЕ меняем — Q8: первый прокси не трогать),
  + лог + admin-алёрт (rate-limit как у proxy down). Half-open: после успеха
  счётчик в 0. Состояние — module-level (как `_state` в proxies). Дёшево,
  без новых зависимостей, бьёт точно в диагноз.
- **(b) Таймауты/пул** — в `_make_direct_connector`/`_build_session`:
  `keepalive_timeout=15` (дохлые соединения не живут в пуле дольше 15с),
  гранулярный `aiohttp.ClientTimeout(total=25, sock_connect=8)` вместо
  плоских 30с (фейл коннекта виден за 8с, а не 30). Опц. env
  `BOT_FORCE_CLOSE=true` — `force_close` коннектора, каждый запрос по свежему
  соединению (медленнее, но неубиваемо; выключено по дефолту). Связь с Q7.a:
  таймауты хендлеров уже стоят, это нижний слой.
- **(c) curl_cffi** — РЕКОМЕНДАЦИЯ: отклонить. aiogram завязан на
  aiohttp-сессию (BaseSession.make_request — это aiohttp API); подмена
  транспорта = форк-обёртка над всем Bot API клиентом, поломает smart-proxy
  (a) и (b). TLS-fingerprint РКН для api.telegram.org — гипотеза, факты из
  логов (вебхук в итоге встаёт, сообщения ходят) на неё не указывают.
- **(d) Webhook ↔ Long Polling** — admin_config `bot.transport` ∈
  {webhook, polling} + переключатель в админке (Прокси/Сеть-экран) +
  применение на лету: supervisor-задача в lifespan (main.py) — при polling
  `delete_webhook` + `dp.start_polling` фоновой задачей; при webhook —
  остановка polling + `set_webhook` (готовая retry-логика старта уже есть).
  FastAPI/Mini App продолжают жить на 7860 в обоих режимах. Плюс: TG DC не
  пессимизирует доставку из-за неотвеченных вебхуков (incidentlog:
  `webhook.set_failed` ×5). Минус: +1 постоянный long-poll коннект через
  тот же канал. Объём — самый большой из четырёх (~средний P-блок).

Рекомендуемый порядок: **b → a → d** (по росту объёма; c — отклонить).

> **Статус (2026-06-06):** INV/план готов (выше), пользователь решил
> **отложить Q-NET** — сначала плановые блоки (P2.4/P3/P4/...). Подэтапы
> a–e ниже остаются открытыми, реализация по этому плану при возврате.

- [ ] **Q-NET.a (10а). Circuit Breaker / авто-fallback на direct.**
  Спроектировать: при первом сетевом таймауте/провале selftest бесшовно
  переключать пул на direct или ротировать прокси, НЕ дожидаясь зависания всей
  очереди APScheduler. Где живёт состояние брейкера, как сбрасывается.
- [ ] **Q-NET.b (10в). Таймауты и пул соединений.**
  Сконфигурировать `ClientTimeout`/пул aiohttp-сессии бота так, чтобы фоновые
  задачи не висели 30с (memefail: Duration ~32с). Связать с Q7.a/Q2.
- [ ] **Q-NET.c (10б). TLS fingerprint / curl_cffi.**
  Оценить интеграцию более скрытного клиента (curl_cffi вместо aiohttp/httpx)
  в контекст aiogram. ВЗВЕСИТЬ риск: aiogram завязан на aiohttp-сессию —
  возможно неоправданно. Сначала研究/INV, реализация под вопросом.
- [ ] **Q-NET.d (10г). Переключатель Webhook ↔ Long Polling.**
  Добавить ПЕРЕКЛЮЧАЕМУЮ опцию (не замена) на long polling с кастомным
  клиентом, чтобы TG DC не пессимизировал доставку из-за неотвеченных
  вебхуков (incidentlog: `webhook.set_failed` ×5, `registration_gave_up`).
  Сохранить оба метода, переключение на лету (admin setting).
- [ ] **Q-NET.e.** Тесты + sync + DEPLOY_NOTES (новые env/настройки).

### Q-FIX. Слипшиеся фразы CHUKHAN_TAGLINES (пропущена запятая) — ЗАКРЫТО
- [x] **Q-FIX.a** (2026-06-05) `chukhan.py:147`: в списке `CHUKHAN_TAGLINES`
  не было запятой после `"Приторговывание тузом… ниже курса"` → Python
  конкатенировал её со следующей фразой `"держит ёршик…"` в одну строку (тихий
  баг implicit string concatenation). Пользователь починил это на HF через
  web-UI (коммит `e594e79`, 03.06), но в main (source of truth) правка не
  попала — main продолжал содержать баг. Запятая добавлена в main; синхронизация
  ниже мёрджит web-UI-коммит, чтобы он не потерялся при push.
  (retry недоставленного пика: job каждые 30мин + дотягивание на старте Space;
  пик больше не откатывается при фейле send).
- **Q3.** Реакции на мемы «в текущем виде работают чётко» — подтверждение, не
  баг (но Q7 про отдельный сбой при throttling).
- **Q8.** НЕ удалять первый зелёный прокси. Остальные не работают и вряд ли
  починим (РКН). Кнопка «найти живые прокси» = «сервис недоступен» с самого
  начала, никогда не работала — низкий приоритет, см. Q-NET.a.
- **Q9.** Диагностика зависаний (много переменных) — учтено в Q-NET.
- **Q6.** Актуализация чеклиста — **этот файл** (выполнено 2026-06-04).

---

## Плановые из GHG7 (не начаты)

### P2.4. ДР-меню — три новые кнопки
Источник: GHG7.txt стр. 39–43.
- [x] **P2.4.a.** (2026-06-06) Все 4 кнопки в `BirthdayPopover.tsx`:
  «✨ Креативное поздравление» и «📅 Назначить встречу» были (GHG6 BD2);
  добавлены «🤖 Пост от лица бота» и «✍️ Пост от своего имени» — появляются
  под textarea после генерации, постят отредактированный текст (showConfirm
  перед отправкой, блокировка на время мутации).
- [x] **P2.4.b.** (2026-06-06) Семантика согласована с пользователем: копипаста
  уже есть («📋 Скопировать»), «от своего имени» = бот постит с пометкой
  «— Поздравил %username%». Backend: `POST /api/birthdays/{user_id}/greeting/
  post` (`routes_birthdays.py`) — body `{text, signed}`, `signed=true` дописывает
  подпись (`compose_greeting_post`, чистая функция). Send через
  `asyncio.wait_for` (env `LOSER_SEND_TIMEOUT`, дефолт 25с — паттерн P11),
  фейлы → явные HTTP 503 (`telegram_retry_after/_forbidden/_network_timeout/
  _api_error` — все уже замаплены в `client.ts:humanizeApiError`). parse_mode
  не используется — юзерский текст с `<`/`&` не ломает отправку.
- [x] **P2.4.c.** (2026-06-06) Get-together контекст: новый стор-пресет
  `pollSheetPresetQuestion` (`ui.ts`), ДР-поповер кладёт «Собираемся на ДР
  {имя}?», `PollSheet` инициализирует им question (вместо «Когда собираемся?»),
  очистка вместе с presetDate при close. Дата ДР первым вариантом — было (BD2).
- [x] **P2.4.d.** (2026-06-06) Тесты: `tests/test_birthday_greeting_post.py`
  — 15 новых (compose: подпись/strip/HTML-спецсимволы; env-таймаут по паттерну
  test_loser_send_timeout_env; GreetingPostIn: пустой/оверлонг/дефолт signed).
  Сьют **262 passed** (было 247), tsc чист (baseline = 2 ошибки HistoryScreen).
  Sync: `routes_birthdays.py` + тест → `meetup-planner-backend/` (262 passed).
  Запушено: HF `8eef976`, GitHub/Pages-source `bd455c3` (фронт пересоберётся
  автоматически). **HF env-напоминание:** новых env НЕ требуется
  (переиспользован `LOSER_SEND_TIMEOUT`).

### P3. Иммунитет именинника к лоху/чухану
Источник: GHG7.txt стр. 47–51.
- [x] **P3.1.a.** (2026-06-06) Настройка: `admin_config[birthdays.immunity_mode]`
  ∈ {announce, silent}, default **announce** (режима «off» нет by design —
  настраивается только подача). Backend: `get/set_birthdays_immunity_mode`
  (`admin_config.py`), поле `immunity_mode` в `ScheduledBirthdaysIO`
  (`routes_admin.py`, дефолт — старые клиенты не сбрасывают). Frontend: чипы
  «📣 С оглашением / 🤫 Без оглашения» в `BirthdaysScreen` (рядом с
  master-switch, optimistic-мутация через тот же `["admin","scheduled"]`).
- [x] **P3.1.b.** (2026-06-06) announce: новый модуль
  `services/birthday_immunity.py` — `resolve_immune_pick` (чистая функция,
  pick_fn-стратегия: равновесный у лоха, взвешенный у чухана; честный бросок
  по полному пулу, именинник → skipped_names + реролл по чистому пулу),
  `announce_immunity_skips` («🎂 Мог бы стать %name%, но ДР…», пауза 1.5с,
  wait_for 25с, best-effort). В БД/историю/календарь черновые НЕ пишутся —
  row создаётся только финальному (loser.py / chukhan.py). Оглашения встроены
  во все 4 точки публикации: `scheduler._autoloser_job`, `routes_meetings`
  (duel), `routes_admin.roll_now`, `chat_commands./loser`; у чухана — перед
  дробью, только при created=True (ретрай не дублирует оглашение).
- [x] **P3.1.c.** (2026-06-06) silent: именинники выкинуты из пула ДО выбора
  (`resolve_immune_pick`); вырожденный пул «все именинники» → иммунитет
  игнорируется (кто-то должен выпасть, не падаем).
- [x] **P3.1.d.** (2026-06-06) `birthdays.py:_render`: к поздравлению дописана
  строка «🛡 Бонус: сегодня у тебя иммунитет — лохом или чуханом не станешь».
- [x] **P3.1.e.** (2026-06-06) `tests/test_birthday_immunity.py` — 12 новых:
  оба режима, пустой/вырожденный пул, «2 именинника в день», инвариант
  «финальный — не именинник» (200 рандом-прогонов), unknown mode → announce,
  формат оглашения. Сьют **274 passed** (было 262), tsc чист (baseline
  HistoryScreen).
- [ ] **P3.1.f.** Sync.

### P4. Экран приветствия с быстрой инфой
Источник: GHG7.txt стр. 25–31.
- [ ] **P4.1.a.** Welcome-screen: Чухан недели, Главный лох, Лох дня (или «не
  выбран»), Червь-пидор (если есть).
- [ ] **P4.1.b.** Единый формат отображения блоков: `name | avatar |
  name+avatar`, default `avatar`. Один селектор на все блоки.
- [ ] **P4.1.c.** При закрытии — диалог «не показывать снова, вернуть в
  настройках профиля». Сохранение в персональных настройках юзера.
- [ ] **P4.1.d.** Отдельное меню профиля. Туда переезжают «Топы» (вместо кнопки
  в нижнем меню). Команда `/top` ведёт туда же.
- [ ] **P4.1.e.** История лохов/чуханов — внутри меню профиля.
- [ ] **P4.1.f.** Sync.

### P2.1.c. Клик по иконке-шапке → попап-история номинации (отложено в GHG7)
- [ ] **P2.1.c.** Требует истории по ролям (для чухана — leaderboard, для
  червя/ДР API истории пока нет). Низкий приоритет.

### P6. Генератор фраз с типажами
Источник: GHG7.txt стр. 151–179.
- [ ] **P6.1.a.** Место хранения персоналий вне git: Neon-таблица
  `participant_personas` (uid, persona_text) — рекомендовано (текст длинный,
  проект открытый). Учесть нагрузку на Neon.
- [ ] **P6.1.b.** Сидинг 6 персоналий (GHG7.txt стр. 154–159) — руками
  пользователя через админку, не коммитом.
- [ ] **P6.1.c.** Sync.
- [ ] **P6.2.a.** Генератор v2: выбор участника по весу активности → шаблон из
  его персоналии (грамм. слоты) → склейка. Без LLM.
- [ ] **P6.2.b.** Унаследовать кулдауны и ручной триггер от v1.
- [ ] **P6.2.c.** Sync.
- [ ] **P6.3.a.** Setting `phrase_generator.version` ∈ {`legacy`, `personas`}.
- [ ] **P6.3.b.** Sync.

### P7. Пул шуток на «мёртвый чат»
Источник: GHG7.txt стр. 200–201.
- [ ] **P7.1.a.** Таблица `dead_chat_phrases` (threshold ∈ {24h, 72h, week,
  month, half_year, year}, text, enabled).
- [ ] **P7.1.b.** Seed: безобидные → философские.
- [ ] **P7.1.c.** Scheduler-job раз в час: проверка lastMessageAt чата →
  публикация фразы из пула нужного threshold (anti-spam: один пост в окно).
- [ ] **P7.1.d.** Sync.

---

## Отложено явно (НЕ в этой итерации)
- **Бот сам постит мемы.** GHG7.txt стр. 203–204 — «Пока не реализуем».
- **Реальный цитатор** (P6.4 из GHG7) — слишком большой объём, требует индекса
  сообщений в Neon. Перенесено сюда из GHG7, остаётся отложенным.

## P13 — рекурси-вес рандом-фраз по возрасту сообщения (фидбек 05.06.2026)

> **Источник (дословно, п.1 от 05.06):** «когда бот выплёвывает рандом фразу, в
> большей половине случаев это буквально одно из 3-5 последних сообщений в чате.
> Поначалу это было даже по-своему прикольно, в передразнивающей манере. Но
> когда это происходит раз за разом, выглядит довольно тупо. Было бы прикольно
> придумать систему, чтобы более свежие сообщения имели меньший вес, а
> старенькие настоявшиеся были более предпочтительными. Критически важно не
> нагружать NEON частыми запросами / хранением всей истории со временем отправки
> (если оно уже не делает этого).»

### P13-INV (разобрано по коду 2026-06-05)
- `random_phrases.py:compose_random_phrase` тянет ОДИН SELECT всех сообщений за
  `lookback_days` (дефолт 7), режет на чанки/слова, выбирает **равновесным**
  `random.choice` по плоскому пулу. Свежие сообщения доминируют, когда чат
  малоактивный (за неделю мало сообщений → последние 3-5 = большая доля пула).
- **Время отправки УЖЕ хранится:** `ChatMessage.sent_at` (timestamptz) + индекс
  `ix_chat_msg_user_sent (user_id, sent_at)` (`models.py:358`). Окно памяти = 7
  дней (`chat_capture.RETENTION_DAYS`, cleanup при каждом сообщении). Значит
  «настоявшиеся» = в пределах этих 7 дней; ничего старше нет физически.
- **⇒ Вывод: НИКАКИХ новых таблиц/миграций/доп. запросов.** Вес считаем в Python
  на том же уже-извлечённом пуле — НОЛЬ доп. нагрузки на Neon. Меняем только
  способ выбора: `random.choices(pool, weights=...)` вместо `random.choice`.

### Согласованный дизайн (AskUserQuestion 2026-06-05)
- **Профиль весов — «порог + плато»:** сообщение младше `quarantine_hours`
  (дефолт ≈18ч) получает околонулевой вес `quarantine_weight` (дефолт 0.05);
  старше порога — полный вес 1.0 (все «отстоявшиеся» равны между собой). Просто
  объяснить, легко крутить.
- **Охват: и автопост, и reply.** Веса применяются и в `compose_random_phrase`
  (дневной автопост), и в `compose_bot_reply_phrase` (reply на @mention —
  главный источник «передразнивания»).
- **Настраиваемость через админку:** `admin_config` ключи
  `random_phrases.recency_quarantine_hours` и
  `random_phrases.recency_quarantine_weight` + контролы в `RandomPhrasesScreen`.

### Подэтапы
- [x] **P13.1.a.** (2026-06-05) `random_phrases.py`: `ChatMessage.sent_at`
  добавлен в SELECT обоих композеров (основной + fallback-100); пул теперь
  `list[tuple[str, float]]` — каждый чанк/слово несёт `age_hours` своего
  сообщения. `by_user`/`all_units` перестроены на кортежи.
- [x] **P13.1.b.** (2026-06-05) Хелпер `_recency_weight` («порог + плато»):
  `quarantine_weight if age < quarantine_hours else 1.0`. Константы
  `RECENCY_QUARANTINE_HOURS_DEFAULT=18.0` / `..._WEIGHT_DEFAULT=0.05`.
  Отрицательный возраст (рассинхрон часов) = свежее.
- [x] **P13.1.c.** (2026-06-05) `_weighted_sample(pool, k)` —
  `random.choices(texts, weights=...)`, фолбэк на равновесный при суммарном
  весе 0. Включён в обе ветки `compose_random_phrase` (collective + per-user),
  в `format_bot_reply` (новый опц. параметр `aged_chunks` — без него прежний
  равновесный путь, обратная совместимость) и `compose_bot_reply_phrase`.
  `bot_reactions._react` читает настройки и передаёт их в reply-композер.
- [x] **P13.2.a.** (2026-06-05) `admin_config.py`: ключи
  `random_phrases.recency_quarantine_hours/weight`, геттеры/сеттеры с клампом
  (hours 0..168, weight 0..1), дефолты 18.0/0.05. `run_random_phrases_job`
  читает и логирует оба значения.
- [x] **P13.2.b.** (2026-06-05) `routes_admin.py`: `GeneratorSettingsOut/Update`
  расширены полями `recency_quarantine_hours/weight` (с дефолтами — старые
  клиенты не присылают), GET/PUT `/admin/random-phrases/generator` читает/пишет.
- [x] **P13.2.c.** (2026-06-05) Frontend: `RPGenerator` (admin.ts) + секция
  «🕰 Карантин свежести» в `RandomPhrasesGeneratorScreen` (`GeneratorBody`,
  встраивается в RandomPhrasesScreen): NumField часов + PercentSlider веса,
  dirty-учёт, `?? 18`/`?? 0.05` для старых серверов. NaN-guard: `|| 0` нельзя,
  0 часов валиден (карантин выключен).
- [x] **P13.3.a.** (2026-06-05) `tests/test_recency_weight.py` — 14 тестов:
  порог/плато/границы/отрицательный возраст; `_weighted_sample` (пустой пул,
  k=0, статистика >85% старых, весь пул свежий, нулевой суммарный вес →
  фолбэк); `format_bot_reply` (без aged_chunks — прежний путь; с aged_chunks —
  свежак почти не попадает). `_FakeSession` в `test_random_phrases_mode.py`
  дополнен `sent_at` (48ч — за карантином, счётчики слов не зависят от весов).
  Сьют: **234 passed** (было 220), tsc чист (baseline HistoryScreen).
- [x] **P13.4.a.** (2026-06-06) Sync: backend P13-файлы уже были скопированы в
  `meetup-planner-backend/` (diff identical, сьют 234 passed) — закоммичены
  (`2f4e04e`) и запушены в HF. Main (P13 `4dd8ae1` + merge web-UI README
  `7305981` → `5cbbbc3`) запушен в GitHub/Pages-source. Frontend (P13.2.c)
  уезжает тем же push — Pages пересоберётся автоматически.
  **HF env-напоминание:** новых env НЕ требуется (всё в `admin_config`).