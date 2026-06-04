# Meetup Planner — чеклист GHG7

> ⚠️ **АРХИВ (2026-06-04).** Итерация GHG7 закрыта и задеплоена (релиз P0–P10,
> HF `cf79c18` / Pages `773f688`, 2026-06-01). Рабочий чеклист теперь —
> `CHECKLIST_GHG8.md`. Этот файл НЕ удалять: хранит детали и file:line по
> закрытым задачам + исходный прод-фидбек 03.05.26 (пункты 1–10), разложенный
> в GHG8 как блок Q.

Источник: `C:\Users\fa1nt\GHG7.txt`. Дата старта итерации: 2026-05-28.
Single source of truth: `C:\Users\fa1nt\meetup-planner-main` (монорепо `backend/` +
`frontend/`). После каждого блока с правками `backend/` —
`cp backend/* → C:\Users\fa1nt\meetup-planner-backend\`
(отдельный git remote → HF Space). Frontend синхронизирует пользователь сам в
`kickmesc-dotcom/meetup-planner` (Pages).

## Легенда статусов
- `[ ]` — не начато
- `[~]` — в работе (был обрыв или ждём чего-то)
- `[x]` — закрыто

###Добавлено 31.05.26 09:05
В одной из последних итераций мы починили автолоха, а потом мы добавили принудительную проверку. Есть основание полагать что эта принудительная проверка спамится слишком часто и нам опять обрезают\перекрывают канал, поскольку бот уже два дня не выполнял задач по расписанию (отправка сообщений и автолок полностью пропущены) В прошлом мы уже и так сильно урезали частоту опроса сервера для таких ивентов как др и это положительно сказалось на стабильности модулей отправки сообщений. Нужно посмотреть все необязательные запросы на сервер которые летят с неоправданно высокой частотой и свести их к адекватному минимуму (например: новые др-ки проверять раз в сутки, онлайн статус бота - раз в час)

###Добавлено 31.05.26 09:050
На Neon получил такую плашку:
Approaching limit
You've used 96.2% of your monthly compute allowance for this project.
Review usage
Upgrade plan
Хоть сегодня и 31 число месяца, это означает что вроде как мы уложились тютелька в тютельку. Но в будущем не исключено что проект будет более функционален и требователен, а переходить на платную основу я пока не готов. Нужно подумать наперед что мы можем сделать для оптимизации и сокращения количества лишних обращений к Neon.

## Правила работы с чеклистом (изменено vs GHG6)
1. Каждый этап разбит на нумерованные подэтапы вида `P0.1`, `P0.2`, при
   необходимости — под-подэтапы `P0.1.a`, `P0.1.b`.
2. **После закрытия каждого подэтапа** в чеклисте проставляется `[x]` и
   однострочная пометка `(YYYY-MM-DD) <что сделано> — <ключевой файл/коммит>`.
   Никаких «закрыто целиком, детали в git log» по ходу работы — это допустимо
   только в финальной зачистке итерации.
3. Sync-копирование `meetup-planner-main/backend/` →
   `meetup-planner-backend/` — отдельный подэтап с галочкой, не комментарий.
4. Если работа над подэтапом оборвалась — он переводится в `[~]` с пометкой,
   на каком файле/шаге остановились. Следующая сессия читает чеклист и
   продолжает с `[~]`, иначе — с первого `[ ]` после последнего `[x]`.
5. Investigate-пункты (`INV-N`) не «фиксят», а отвечают на вопрос и при
   необходимости порождают новые подэтапы в `P*` блоках. Сам `INV-N`
   закрывается выводом + ссылкой на созданные follow-up подэтапы.

---

## INV — расследования перед P0

### INV-1. Где новый таймлайн в приложении (есть, но не виден)
- [x] **INV-1.a.** (2026-05-29) Прочитано напрямую из Neon `admin_config`
  (curl с initData недоступен — авторизация требует свежую TWA-подпись;
  читал прямым asyncpg-коннектом по DATABASE_URL). Ключа
  `calendar.timeline_enabled` в таблице **НЕТ** → действует дефолт `False`
  (`get_calendar_timeline_enabled`, `admin_config.py:471-479`). Подтверждает
  гипотезу: таймлайн в проде выключен, поэтому «не виден».
- [x] **INV-1.b.** (2026-05-29) **НЕ включаем.** Пользователь проверил
  таймлайн (включал ранее вручную) — «выглядит отвратительно и неюзабелен
  даже хуже текущего функционала». Дефолт остаётся `False` (legacy-вид).
  Флаг в БД не трогаем.
- [x] **INV-1.c.** (2026-05-29) **Вывод:** новый таймлайн в текущем виде
  непригоден; его либо уберут, либо перепишут в отдалённом будущем.
  Персональный переключатель режимов в профиле (был в плане P4) —
  **отменён**. Решение: глобальный тогглер новый/старый в админке, дефолт
  старый. → P2.5 переведён из «опционально» в «делаем» (см. ниже,
  закрыт в этой же сессии).

Известные факты (по чтению кода 2026-05-28):
- Бэк: `app/services/admin_config.py:468–482`, `app/api/routes_admin.py:2083–2099`.
- Фронт: `frontend/src/api/admin.ts:627–640`,
  `frontend/src/features/calendar/CalendarView.tsx:48–266`.
- UI-тогглера в админке **нет** — включать сейчас только curl'ом.
- Откат: `PUT /admin/calendar/timeline {"enabled": false}` (см. `DEPLOY_NOTES.md`).

---

## P0 — критические баги (логика данных и доставки)

### P0.1. `loser_rolls.source` перепутан manual ↔ auto
Источник: GHG7.txt стр. 1.
- [x] **P0.1.** (2026-05-28) **WONT-FIX.** Проверка кода 2026-05-28:
  все четыре пути записи в `loser_rolls` передают корректный `source`:
  - `app/bot/scheduler.py:237` (autoloser-job) → `"auto"` ✓
  - `app/api/routes_admin.py:1240` (admin force-reroll) → `"manual"` ✓
  - `app/bot/handlers/chat_commands.py:92` (`/loser`) → default `"manual"` ✓
  - `app/api/routes_meetings.py:319` (UI Mini App) → default `"manual"` ✓
  Прямых `LoserRoll(...)` мимо `roll_loser` в проде-коде нет
  (`tests/test_loser_outbox.py:80` — только тест-фикстура).
  HF-копия `meetup-planner-backend` идентична main по этим файлам
  (`diff -q` пуст). Жалоба GHG7 стр.1 описывает старые данные в Neon,
  оставшиеся от пред-GHG6-H1 кодовой базы и/или server_default='manual'
  миграции 0012. Пользователь подтвердил 2026-05-28: «это не баг и
  ни на что не влияет кроме эстетики в базе». Data-migration НЕ пишем.

### P0.2. Автолох не доставляется в чат, но появляется в БД
Источник: GHG7.txt стр. 2, 192–198.

Дизайн (решено 2026-05-28): **outbox-паттерн** для авто-лоха. Запись в
`loser_rolls` коммитится сразу, но в отдельной таблице `loser_outbox`
держим статус доставки. Calendar marks фильтрует по `status='sent'` (т.е.
до успешного поста в чат корона не видна). Scheduler-job `loser_outbox_retry`
каждую минуту повторяет недоставленные с лимитом 12 попыток через 5 минут.
Ручные пути (UI/chat-команда/admin force-reroll) остаются «best-effort»,
без outbox — там юзер сам видит результат и может ткнуть ещё раз.

- [x] **P0.2.a.** Трассировка scheduler-job → on_announce — выполнено
  2026-05-28. `app/bot/scheduler.py:99-171` (`_autoloser_job`,
  `_announce`). on_announce НЕ ловит ошибки сам, но и не проверяет
  возвращаемый `message_id`. Причина бага: send_message может «успешно»
  вернуться через висящий прокси при том что чат сообщение не получил.
  Также найден конфликт: ручные пути сознательно глотают TG-ошибки
  (best-effort с GHG6) — оставляем как есть, фикс только в авто-лохе.
- [x] **P0.2.b.1.** (2026-05-28) Alembic-миграция `0014_loser_outbox`
  написана — `backend/alembic/versions/0014_loser_outbox.py`. Таблица
  `loser_outbox` с FK на loser_rolls, CHECK status ∈ {pending,sent,failed,
  expired}, индекс `ix_loser_outbox_pending(status, next_retry_at)` для
  retry-job.
- [x] **P0.2.b.2.** (2026-05-28) Модель `LoserOutbox` добавлена в
  `app/db/models.py` сразу после `LoserRoll`. Relationship `loser_roll`,
  CheckConstraint по статусу повторяет DDL миграции, импорт `Integer`
  добавлен.
- [x] **P0.2.b.0 sync** (2026-05-28) main → GitHub
  (`kickmesc-dotcom/meetup-planner@858c295`) + backend → HF Space
  (`fryesw/meetup-planner-backend@f20a08f`). DDL применится при старте
  Space, фактическое поведение остаётся прежним (outbox не используется
  никем до b.3).
- [x] **P0.2.b.5+f sync** (2026-05-28) main `@40de092` + HF `@bc45f2c`.
  **P0.2 закрыт по основному фронту:** autoloser теперь пишет в outbox,
  retry-job каждую минуту догоняет недоставленные, корона на календаре
  появляется только после фактического поста в чат. P0.2.b.4 sync
  (`@c414706`/`@7e488f5`) — теперь pending-роллы догоняются retry-job'ом.
- [x] **P0.2.b.3 sync** (2026-05-28) main `@47453a0` + HF `@194ae78`.
  Теперь автолох ПИШЕТ в outbox при каждом срабатывании, но без retry-job
  (b.4) `pending`-записи никогда не догоняются. Без фильтра в календаре
  (b.5) корона показывается и для pending-роллов — то есть проявления
  бага P0.2 пока не полностью устранены; критически важно поскорее
  закрыть b.4 и b.5.
- [x] **P0.2.b.3.** (2026-05-28) `_announce` в `app/bot/scheduler.py`
  переписан под outbox-паттерн: создаёт `LoserOutbox(status='pending')`
  в одной транзакции с roll, пробует `send_message` с timeout=8s, при
  успехе → `status='sent'`+tg_message_id, при ошибке → `attempts=1,
  last_error, next_retry_at=now+5m`. Исключение НЕ rerais'ится (иначе
  roll_loser откатит и потеряется ретрай-материал). Закрыто заодно
  P0.2.d — логи `autoloser.outbox_sent`/`outbox_pending` с полями
  `transport=direct|proxy`, `proxy_id`, `elapsed_ms`. Константы:
  `_AUTOLOSER_SEND_TIMEOUT=8.0`, `_AUTOLOSER_RETRY_DELAY=5min`,
  `_AUTOLOSER_MAX_ATTEMPTS=12`.
- [x] **P0.2.b.4.** (2026-05-28) `_loser_outbox_retry_job` в
  `scheduler.py`: SELECT pending FOR UPDATE SKIP LOCKED LIMIT 10,
  пересборка текста из `LoserRoll+User` (без worm-стилизации в ретрае),
  send_message с timeout=8s, при успехе → sent+message_id, при фейле
  → attempts+=1, expired при достижении MAX. Зарегистрирован в
  `start_scheduler` как infra-job (IntervalTrigger 1 min, jitter 10s,
  misfire_grace=5min). Удалённые roll'ы (None при `session.get`) сразу
  помечаются expired с last_error='loser_roll missing'.
- [x] **P0.2.b.5.** (2026-05-28) LEFT JOIN с `loser_outbox` в
  `routes_calendar.py::calendar_marks`. Фильтр
  `LoserOutbox.id IS NULL OR LoserOutbox.status='sent'` — для legacy
  роллов до миграции и для всех ручных (manual outbox не пишет вообще)
  фильтр прозрачен; pending/expired auto-роллы скрыты до успешной
  доставки. Контракт `build_marks` не изменился — все 10 старых тестов
  остаются зелёными.
- [x] **P0.2.c.** (2026-05-29) N/A — объединено в b.3. Rollback для
  авто-лоха больше не делаем (исключение не rerais'ится, см. b.3),
  поэтому «защита от ложного затирания» как отдельный шаг неактуальна.
- [x] **P0.2.d.** (2026-05-28) Закрыто в составе b.3. Логи
  `autoloser.outbox_sent` (успех) и `autoloser.outbox_pending` (фейл)
  содержат `transport=direct|proxy`, `proxy_id`, `elapsed_ms`,
  `error/tg_message_id`. Для retry-job (b.4) аналогичные логи будут с
  префиксом `loser_outbox_retry.*`.
- [x] **P0.2.e.** (2026-05-29, main `@ff2c3d9`) Попап «причина ролла» по
  клику на корону. Бэк: `GET /calendar/loser/{day}/{user_id}`
  (`routes_calendar.py`) — последний `LoserRoll` за день/юзера
  (`rolled_at DESC`), без outbox-фильтра (корона уже видна => ролл
  доставлен/legacy/manual), 404 если записи нет; поля
  `reason_text/source/rolled_by_name/was_worm`. Фронт: кликабельная 👑
  (`ParticipantRow.tsx`, `pointer-events-auto` точечно + `stopPropagation`
  + `haptic`), zustand `loserReasonPopover` (`store/ui.ts`),
  `fetchLoserReason` (`api/birthdays.ts`), компонент
  `LoserReasonPopover.tsx` (ветвление по source auto/manual/worm,
  зеркалит `BirthdayPopover`). Тесты 165/165, tsc чист по затронутым
  файлам (2 ошибки в `HistoryScreen.tsx` — предсущ., не наши).
- [x] **P0.2.f.** (2026-05-28) `tests/test_loser_outbox.py` — 4 теста:
  (1) фейл send → pending+attempts=1+last_error, без raise;
  (2) успех → sent+tg_message_id;
  (3) 12-й фейл → expired;
  (4) после фейла повторный успех → sent+attempts++.
  + `test_build_marks_still_accepts_source_tuples` — регрессионный гард
  контракта build_marks. Все 14 тестов в test_loser_outbox+
  test_calendar_marks проходят локально (.venv pytest).
  Async-БД-стенда в проекте нет (см. шапку `test_loser_cooldown_split`)
  — кейс «корона физически не видна» покрывается на SQL-слое через
  ручную проверку в проде (см. INV-2 ниже, не блокирует деплой).
- [x] **P0.2.g sync** (2026-05-29) `meetup-planner-main/backend/app/api/
  routes_calendar.py` → `meetup-planner-backend/` (HF `@d13e888`). Только
  этот файл изменён бэком в P0.2.e (frontend в HF не идёт). Push в HF/GitHub
  делает пользователь.

### P0.3. Копилка фраз — резкое падение и обнуление по участникам
Источник: GHG7.txt стр. 4.

«Копилка» — `chat_messages` table (`app/bot/handlers/chat_capture.py`).
Сохраняются текстовые сообщения известных юзеров из `group_chat_id`,
non-bot, не `/`-commands. RETENTION_DAYS=7. Чтение в admin-UI —
`GET /admin/random-phrases/pool` (`routes_admin.py:464`).

- [x] **P0.3.a.** (2026-05-28) Разбор кода. Найден TZ-несоответствие
  writer/reader: `chat_capture.cleanup_old_messages` использовал
  naive `datetime.utcnow()`, а reader'ы (`random_phrases.compose_*`,
  `routes_admin.get_rp_pool`) — aware `datetime.now(timezone.utc)`.
  `ChatMessage.sent_at` — `TIMESTAMP WITH TIME ZONE`. Если TZ HF Space
  не UTC — naive интерпретируется как локальное время и cutoff
  сдвигается. На HF обычно UTC, но рассинхрон латентно-хрупкий.
  Других подозрительных мест записи/удаления `ChatMessage` не найдено.
- [x] **P0.3.b.** (2026-05-28) Два фикса в `meetup-planner-main`:
  - `app/bot/handlers/chat_capture.py:28-39` —
    `utcnow()` → `now(timezone.utc)`. Cleanup теперь aware UTC.
  - `app/api/routes_admin.py` — добавлен debug-эндпоинт
    `GET /admin/random-phrases/pool/raw`: возвращает по каждому юзеру
    `total_messages` (без cutoff), `last_sent_at`,
    `messages_within_lookback`, плюс meta `server_now_utc`,
    `cutoff_used_utc`, `total_messages_in_db`. Расхождение
    total↔within_lookback покажет, режет ли TTL слишком много;
    малый `total` при «активный юзер» = не записывается на входе.
  Тесты: 155/155 зелёные (`pytest tests/`).
- [x] **P0.3.c.** (2026-05-29) **Диагноз ПЕРЕОПРЕДЕЛЁН — это НЕ TZ/cutoff.**
  Прочитал прод-данные напрямую из Neon (asyncpg по DATABASE_URL):
  152 сообщения, диапазон `2026-05-15 .. 2026-05-22`, `user_id NULL = 0`.
  **Запись встала 22 мая**, хотя чат активен после (подтвердил пользователь).
  `loser_rolls` имеет запись от 28 мая → бот жив, scheduler-исходящие
  работают. Значит проблема — во **входящих** групповых апдейтах до
  `chat_capture`. Корень: `bot_reactions.router` (`@router.message(F.text)`)
  зарегистрирован в `dispatcher.py` ДО `chat_capture.router`; его
  `on_message` возвращал `None` при любом раннем `return`, а в aiogram 3.13
  это останавливает пропагацию между роутерами (`router.py:170` —
  `if response is not UNHANDLED: return`; `telegram.py:106-125` — `trigger`
  возвращает результат первого сматчившегося handler'а). → `chat_capture`
  никогда не вызывался с момента деплоя GHG6 E9 (~22 мая). Фикс P0.3.b
  (TZ aware) корректен, но лечил не ту причину. **Восстановления нет** —
  152 старых сообщения остаются (пользователь: «оставить как есть»),
  cleanup сам их подчистит при первом новом сообщении. Follow-up: P0.3.e.
- [x] **P0.3.d sync** (2026-05-28) `meetup-planner-main/backend/` →
  `meetup-planner-backend/`: `chat_capture.py`, `routes_admin.py`.
  Push в HF/GitHub отдельным шагом.
- [x] **P0.3.e.** (2026-05-29) **Фикс корня (перехват апдейтов).**
  - `bot_reactions.py`: логика реакции вынесена в `_maybe_react`, а
    `on_message` теперь ВСЕГДА завершается `raise SkipHandler`
    (import из `aiogram.dispatcher.event.bases`). Тогда `trigger` вернёт
    `UNHANDLED`, и Dispatcher передаст апдейт следующему роутеру
    (`chat_capture`), который сохранит сообщение. Реакция (mention/reply)
    выполняется как побочный эффект до SkipHandler.
  - `dispatcher.py:294-299`: исправлен ошибочный комментарий «порядок
    aiogram-роутеров на срабатывание не влияет» — влияет; теперь явно
    описан контракт SkipHandler.
  - `bot_reactions.py` docstring модуля переписан под реальную семантику.
  - Тест `tests/test_bot_reactions_propagation.py` (4 кейса): SkipHandler
    поднимается во всех ветках (чужой чат / не whitelist / обычный текст /
    mention с реакцией). Весь сьют 169/169 зелёный (было 165).
- [x] **P0.3.f sync** (2026-05-29) `meetup-planner-main/backend/` →
  `meetup-planner-backend/`: `app/bot/handlers/bot_reactions.py`,
  `app/bot/dispatcher.py`, `tests/test_bot_reactions_propagation.py`
  (diff -q пуст). Push в HF/GitHub делает пользователь.

### P0.4. Healthcheck бота даёт false-negative ~80%
Источник: GHG7.txt стр. 8.

Контекст 2026-05-28: пользователь уточнил, что РКН добил MTProto-прокси
почти полностью (Telegram должен менять алгоритм на своей стороне),
поэтому **не углубляемся** в переключение/восстановление прокси.
Главное — чтобы индикатор не врал в режиме direct, и не сломать сам
путь отправки команд (он сейчас работает без перебоев).

- [x] **P0.4.a.** (2026-05-28) Реализация: `selftest_send` в
  `backend/app/services/proxies.py:1061` — одна попытка `bot.get_me()`
  с таймаутом 15с (`SELFTEST_TIMEOUT_SEC`). Используется в трёх
  местах: `proxy_health_tick` (periodic), `POST /admin/proxy/selftest`
  (ручной запуск), `GET ProxyStatusOut.last_selftest`. Один тайм-аут/
  exception — сразу `ok=False`, ретраев нет.
- [x] **P0.4.b.** (2026-05-28) Двухступенчатая проверка БЕЗ касания
  transport'а. Вынес тело попытки в `_attempt_selftest`, обернул в
  `selftest_send` с логикой:
  - первая попытка — как раньше;
  - если ok → возврат сразу;
  - если фейл и ошибка — `TelegramUnauthorizedError/BadRequest/
    ForbiddenError` → НЕ ретраим (бот сам отверг, повтор не поможет);
  - иначе пауза `_SELFTEST_RETRY_PAUSE_SEC=1.0s` и вторая попытка
    через ту же session (никаких mark_proxy_failed / переключения
    пула / invalidate — путь команд бота нетронут).
  - результат содержит `retried`, `first_error` для прозрачности UI.
  `ProxySelftestOut` в `routes_admin.py:1934` расширен теми же
  полями (default'ы → backward-compatible для старого фронта).
  `proxy_health_tick` логирует `retried`+`first_error` в
  `proxy.health_tick`.
- [x] **P0.4.c.** (2026-05-28) `tests/test_selftest_retry.py` — 4 кейса:
  (1) первая ok → один вызов get_me, retried=False;
  (2) первая timeout + вторая ok → retried=True, ok=True,
      first_error='timeout';
  (3) оба timeout → retried=True, ok=False, error='timeout';
  (4) первая TelegramUnauthorizedError → НЕ ретраим (get_me_calls==1),
      retried=False, bot_active=True.
  Все 159/159 тестов зелёные.
- [x] **P0.4.d sync** (2026-05-28) `meetup-planner-main/backend/` →
  `meetup-planner-backend/`: `app/services/proxies.py`,
  `app/api/routes_admin.py`, `tests/test_selftest_retry.py`.
  Push в HF/GitHub отдельным шагом.

---

## P1 — мелкие UX / визуальные баги

### P1.1. Чекбокс «снимите галочку чтобы пропустить» в добавлении прокси
Источник: GHG7.txt стр. 6. Чёрное на чёрном, нет индикации.
- [x] **P1.1.a.** (2026-05-28) `ProxyScreen.tsx:937` — нативный `<input
  type="checkbox">` без классов. В проекте уже есть `.chk-tg` в
  `styles.css:80` (рамка `tg-hint`, заливка `tg-link`, белая галка
  при checked, WCAG AA). Добавлен `className="chk-tg"` к input,
  плюс `min-h-11` на label — hit-target 44px по Apple/TG guideline.
- [x] **P1.1.b sync** (2026-05-28) Только main. Frontend push в
  `kickmesc-dotcom/meetup-planner` пользователь делает сам.

### P1.2. Чекбоксы «после победителя» / «закрепить опрос» в играх
Источник: GHG7.txt стр. 11. Чёрное на чёрном + крошечный hit-target.
- [x] **P1.2.a.** (2026-05-28) `GamesScreen.tsx:219-252` —
  два `<label>` (followUp + pinPoll). Применён `.chk-tg`,
  `min-h-11 py-1.5`, `items-start → items-center`. Попутно тот же
  паттерн применён к `PollSheet.tsx:246` (чекбокс «Закрепить опрос»)
  — идентичная проблема, оставлять рассинхрон нелогично.
- [x] **P1.2.b sync** (2026-05-28) Только main. Frontend push
  пользователем.

### P1.3. Глобальный убрать `@gunghogunsbot` из отображения команд
Источник: GHG7.txt стр. 44.
- [x] **P1.3.a.** (2026-05-28) `main.py::_register_bot_metadata` ставит
  `BotCommand(command=c.cmd, ...)` — без `@`-суффикса в нашем коде.
  Суффикс приписывает сам Telegram, когда видит в чате нескольких
  ботов и неуверен в адресации. Сейчас scope = `AllPrivateChats` +
  `AllGroupChats` — общий, TG страхуется.
- [x] **P1.3.b.** (2026-05-28) Дополнительно вызываем `set_my_commands`
  с прицельным `BotCommandScopeChat(chat_id=settings.group_chat_id)`
  для нашей шестёрки. У TG приоритет scope'ов: специфический (Chat)
  перекрывает общий (AllGroupChats), и в этом чате TG считает команды
  «однозначно нашими» — не клеит `@gunghogunsbot`. Для других group
  chat'ов (если бот когда-нибудь окажется в ещё одной группе)
  остаётся AllGroupChats-fallback.
- [x] **P1.3.c sync** (2026-05-28) `main/backend/app/main.py` →
  `meetup-planner-backend/app/main.py`. Применяется при следующем
  старте Space (вызов в `_register_telegram_metadata_with_retry`).

### P1.4. Индикация активной `/zaebal`-паузы в списке команд
Источник: GHG7.txt стр. 13.
- [x] **P1.4.a.** (2026-05-28) Через `BotCommand.description` TG-меню
  нельзя обновлять часто (rate limit + кеш TG). Поэтому индикация
  живёт в нашем `/help` (`backend/app/bot/handlers/help.py`):
  - `render_help` получил опциональный `paused_until: datetime | None`
    (backward-compatible default `None`). Если задан и > now —
    к строке `/zaebal` дописывается `⏸️ пауза N` через хелпер
    `_format_remaining` («2д 4ч 15м», «3ч 20м», «43м», «<1м» —
    последний для race condition «пауза уже истекла, autorestore не
    успел»).
  - `on_help` подгружает `BotPause.ends_at` через `get_active_pause`
    и передаёт в `render_help`.
  - Badge только на `/zaebal`, не на `/zaebal_vote` (это запуск
    голосования, не сама пауза).
  Тесты в `tests/test_help_commands.py`: 6 новых кейсов
  (`_format_remaining` × 4 ветки + 2 render-теста). Все 165/165
  тестов зелёные.
- [x] **P1.4.b sync** (2026-05-28) `main/backend/app/bot/handlers/help.py`
  + `tests/test_help_commands.py` → `meetup-planner-backend/`.

---

## P2 — средние UX-улучшения

### P2.1. Иконки др/лох/корона/червь — переделать как «шапку» аватарки
Источник: GHG7.txt стр. 19.

Решения 2026-05-29/30: шапка = **актуальные звания** (кто кем является
прямо сейчас), не агрегат по дням. Дневные 👑/💩/🎂 в ячейках остаются как
есть (это события на дату). Несколько званий — **стеком рядом** по приоритету.
Лох дня = 👑, главный лох = 🤡 (разные иконки).
- [x] **P2.1.a.** (2026-05-30) **Backend:** новый read-only эндпоинт
  `GET /api/titles/current` (`routes_calendar.py`, `CurrentTitlesOut`):
  worm (`get_current_worm`), чухан текущей недели (прямой SELECT по
  `current_week_start()` — НЕ `pick_chukhan_for_week`, она бы создала
  запись), лох дня (последний `LoserRoll` за сегодня UTC), главный лох
  (`pick_main_loser` — max по `loser_stats`, тай-брейк меньший user_id),
  ДР сегодня (`Birthday` по дню/месяцу). Тест `test_titles_current.py`
  (5 кейсов на `pick_main_loser`), сьют 174/174.
  **Frontend:** `fetchCurrentTitles`/`CurrentTitles` (`api/birthdays.ts`),
  query `["titles-current"]` в `CalendarView` (заменил отдельный
  `["worm-current"]` — worm теперь приходит здесь), проп `titles`
  прокинут в `StripView`/`TimelineView` → `ParticipantRow`.
- [x] **P2.1.b.** (2026-05-30) `ParticipantRow.tsx`: per-user `titleBadges`
  по `user.id`, отрисовка горизонтальным стеком над аватаркой
  (`-top-2 left-1/2 -translate-x-1/2 z-20`, каждая иконка на плашке
  `bg-tg-bg rounded-full` для читаемости). Приоритет слева-направо:
  🎂 ДР · 👑 лох дня · 🤡 главный лох · 💩 чухан недели · 🪱 червь.
  Прежний bottom-right 🪱-бейдж убран — червь теперь часть общего стека.
  z-20 выше кружка (z-10), статус-пилюли в сетке ячеек не затрагиваются.
  tsc по затронутым файлам чист (2 ошибки в `HistoryScreen.tsx` — предсущ.).
- [ ] **P2.1.c.** Клик по иконке → попап-история номинации участника
  (сколько раз был в этой роли, топ номинантов). **Отложено отдельным
  подэтапом** (требует истории по ролям: для лоха — частично `loser_stats`,
  для чухана — leaderboard, для червя/ДР истории-API пока нет). Иконки
  сейчас информативные (title/aria-label), некликабельные.
- [x] **P2.1.d sync** (2026-05-30) Backend `routes_calendar.py` +
  `test_titles_current.py` → `meetup-planner-backend/` (diff -q пуст).
  Frontend (`api/birthdays.ts`, `CalendarView.tsx`, `views/StripView.tsx`,
  `views/TimelineView.tsx`, `ParticipantRow.tsx`) — push пользователем.

### P2.2. Уведомления о паузе бота (через команду/voot vs админка)
Источник: GHG7.txt стр. 14–15.
- [x] **P2.2.a.** (2026-05-31) Анонс паузы в группу уже был
  (`/zaebal` порог → `handlers/zaebal.py:117`; `/zaebal-vote` close →
  `handlers/poll_answer.py:148-178`; auto-monthly идёт тем же путём).
  Главный пробел — **разморозка по таймеру была silent**. Добавлено:
  `WELCOME_BACK_PHRASES`+`_welcome_back_phrase()` в `services/zaebal.py`;
  `stop_pause(..., announce=False)` шлёт «злобное приветствие + меня не было
  N ч» через `_announce_welcome_back_safe` (изолированный импорт бота, как
  `_reload_jobs_safe`); `maybe_auto_restore` зовёт `stop_pause(automatic=True,
  announce=True)`. Часы — `_format_absence_hours` (round, min 1, терпит naive
  started_at).
- [x] **P2.2.b.** (2026-05-31) Silent-режим подтверждён и закреплён предикатом
  `should_announce_restore(reason, announce)` (`bot_pause.py`): анонс только
  при `announce=True AND reason∈CHAT_INITIATED_REASONS` (zaebal_threshold/
  zaebal_vote/auto_monthly). Админка start/stop (`routes_admin.py:2260-2288`)
  и `/zaebal_undo` зовут `stop_pause(session)` без `announce` → всегда silent,
  даже если пауза ставилась командой. `manual_admin`-пауза при авто-истечении
  таймера тоже молчит (не в CHAT_INITIATED_REASONS). Код админки не менялся
  (уже был silent).
- [x] **P2.2.c.** (2026-05-31) `tests/test_bot_pause_announce.py` (8 кейсов):
  фразы из пула, матрица анонса (chat-reasons при automatic → да; manual_admin
  → нет; любое ручное снятие announce=False → нет), `CHAT_INITIATED_REASONS ⊆
  VALID_REASONS` без manual_admin, расчёт часов (round/min-1/naive-tz). Весь
  сьют 182/182 зелёный (было 174).
- [x] **P2.2.d sync** (2026-05-31) `meetup-planner-main/backend/` →
  `meetup-planner-backend/`: `app/services/zaebal.py`,
  `app/services/bot_pause.py`, `tests/test_bot_pause_announce.py` (diff -q пуст,
  тесты в HF-копии 8/8 зелёные). Push в HF/GitHub делает пользователь.

### P2.3. Реорганизация меню админки (frontend-only)
Источник: GHG7.txt стр. 32–37. Backend НЕ менялся (контракты те же).
- [x] **P2.3.a.** (2026-06-02) `AdminScreen.tsx`: `SectionGroup "⏱ Интервалы"`
  поднята из самого низа сразу ПОД «⏰ Запланированные публикации» (смежные
  настройки расписания).
- [x] **P2.3.b.** (2026-06-02) Объединены «Автопост рандомных фраз» +
  «Генератор фраз» → одна Card «💬 Рандомные фразы» → новый
  `RandomPhrasesScreen.tsx` с двумя секциями. Тела вынесены из исходных экранов
  как `ScheduleBody`/`GeneratorBody` (export без SubScreen-обёртки); старые
  дефолт-экспорты остались тонкими враппер-экранами (на случай прямых ссылок),
  но из роутинга `AdminScreen` убраны (`rp-schedule`/`rp-generator` → `rp`).
  Каждое тело со своим query/мутацией — состояние не делится.
- [x] **P2.3.c.** (2026-06-02) Подсказки автовыбора переписаны во влитой
  `AutoLoserForm` (теперь внутри `LoserScreen`): окно — «Часы суток (время
  сервера, 0–23), когда бот может назначить лоха. Вне окна — молчит.»; частота
  — «**0** — раз в сутки в случайный момент окна. **N≥1** — каждые N часов
  внутри окна» + пример.
- [x] **P2.3.d.** (2026-06-02) Шаблоны фраз подняты выше истории в
  `loser/LoserScreen.tsx` и `ChukhanScreen.tsx` (было сделано прошлой сессией,
  лежало незакоммиченным в рабочем дереве — теперь зафиксировано; слияние лоха
  P2.3.h это сохранило).
- [x] **P2.3.e.** (2026-06-02) `BirthdaysScreen.tsx`: `BirthdaysMasterSwitch` —
  глобальный рубильник всех ДР-напоминаний (привязан к `birthdays.alerts_enabled`,
  общий queryKey `["admin","scheduled"]` → синхронизация с «Запланированными
  публикациями»; per-user галочки сохраняются). Было незакоммичено прошлой
  сессией — зафиксировано.
- [x] **P2.3.f.** (2026-06-02) `BotReactionsSection` вынесена из
  `ScheduledPublicationsScreen.tsx` в новый `BotReactionsScreen.tsx` (компонент
  самодостаточен — свой query `["admin","bot-reactions"]`, авто-save). В
  `AdminScreen` новая `SectionGroup "🤖 Реакции"` верхнего уровня + одна Card.
  Локальный `Switch` скопирован в новый экран (в родителе ещё используется).
- [x] **P2.3.h.** (2026-06-02) **Дубль «Лох дня» устранён.** Были два пункта
  меню с одинаковым названием: `AutoLoserScreen` (настройки автовыбора, в
  «Запланированных публикациях») и `LoserScreen` (реролл/история/шаблоны, в
  секции «Лох»). Бэкенд хранит всё под одними ключами `autoloser.*` (источник
  правды один — `get_autoloser_settings`), расхождения данных НЕТ → слияние
  чисто UI. `AutoLoserForm` влит первой секцией в `LoserScreen` (порядок как у
  Чухана: ⚙️ автовыбор → 🎲 реролл → 🤡 шаблоны → 📜 история),
  `AutoLoserScreen.tsx` удалён, в меню одна Card «👑 Лох дня».
- [x] **P2.3.verify.** (2026-06-02) `npx tsc --noEmit` чист по затронутым
  файлам (baseline: 2 предсущ. ошибки в `HistoryScreen.tsx` из коммита
  `eba2674` — недоделанная вкладка «Встречи», не наши, пользователь решил не
  трогать). `npm run build` падает на этих же 2 ошибках (strict `tsc -b`-гейт),
  НО `npx vite build` собирается успешно (821 модуль) — Pages билдятся именно
  Vite-бандлером (GH Actions/`dist` в репо нет; так же шипились P9/P10).
- [x] **P2.3.g sync.** (2026-06-02) Backend sync НЕ требуется — правок в
  `backend/` нет. Frontend push в `kickmesc-dotcom/meetup-planner` (= Pages).

### P2.4. ДР-меню — три новые кнопки
Источник: GHG7.txt стр. 39–43.
- [ ] **P2.4.a.** Кнопки: «Креативное поздравление», «Пост от своего имени»,
  «Пост от лица бота», «Назначить встречу».
- [ ] **P2.4.b.** «Пост от своего имени» → форма ввода текста, отправка
  через Telegram User API не реализуема (только UserBot, явно не делаем).
  Уточнить семантику с пользователем перед реализацией — возможно это
  «черновик в копипасту».
- [ ] **P2.4.c.** «Назначить встречу» → прыжок в существующий poll-flow с
  предзаполненным get-together контекстом.
- [ ] **P2.4.d.** Sync.

### P2.5. UI-тогглер `calendar.timeline_enabled` в админке
По выводу INV-1.c — **делаем** (был «опционально»). Дефолт старый/legacy.
- [x] **P2.5.a.** (2026-05-29) Компонент `CalendarSettingsScreen.tsx`
  (Switch + react-query инвалидация под `CalendarView`) уже был написан в
  коммите GHG7 P0.2 (`858c295`), но **не подключён** в `AdminScreen.tsx` —
  был недостижим (orphan). Заврайрено: добавлен `Section`
  `"calendar-settings"`, импорт, роутинг-строка и `Card` «Вид календаря»
  (🆕, subtitle «Новый таймлайн / legacy-вид (по умолчанию legacy)») в
  секцию «📅 Календарь». Сам экран не менялся. tsc по затронутым файлам
  чист (2 ошибки в `HistoryScreen.tsx` — предсущ., не наши).
- [x] **P2.5.b sync** (2026-05-29) Только main (`frontend/.../AdminScreen.tsx`).
  Frontend push в `kickmesc-dotcom/meetup-planner` делает пользователь.

---

## P3 — иммунитет именинника к лох/чухан

Источник: GHG7.txt стр. 47–51.
- [ ] **P3.1.a.** Настройка в админке: режим иммунитета `с_оглашением` /
  `без_оглашения` (default — выбрать по итогам обсуждения).
- [ ] **P3.1.b.** `с_оглашением`: при попадании именинника — оглашение
  «мог бы стать %name%, но иммунитет», задержка 1–2с, реролл. Запись в БД,
  историю и календарь **не** делается ни для именинника, ни для «черновой»
  попытки.
- [ ] **P3.1.c.** `без_оглашения`: именинник исключён из выборки изначально.
- [ ] **P3.1.d.** Дописать в текст поздравления упоминание иммунитета.
- [ ] **P3.1.e.** Тесты: оба режима, граничный кейс «именинников 2 в один
  день».
- [ ] **P3.1.f.** Sync.

---

## P4 — экран приветствия с быстрой инфой

Источник: GHG7.txt стр. 25–31.
- [ ] **P4.1.a.** Welcome-screen с блоками: Чухан недели, Главный лох,
  Лох дня (если не выбран — «не выбран»), Червь-пидор (если есть).
- [ ] **P4.1.b.** Единый настраиваемый формат отображения для всех блоков:
  `name | avatar | name+avatar`, default = `avatar`. Один селектор,
  применяется ко всем блокам сразу.
- [ ] **P4.1.c.** При закрытии welcome — диалог «не показывать снова,
  можно вернуть в настройках профиля». Сохранение в персональных настройках
  юзера.
- [ ] **P4.1.d.** Отдельное меню профиля. Туда переезжают «Топы» (вместо
  кнопки топы в нижнем меню). Команда `/top` ведёт туда же.
- [ ] **P4.1.e.** История лохов/чуханов — внутри меню профиля.
- [ ] **P4.1.f.** Sync.

---

## P5 — реакции бота на медиа (новая подсистема)

Источник: GHG7.txt стр. 21–23, 53–149.

**Решение по хранению (2026-06-03):** НЕ отдельная таблица
`media_reaction_phrases`, а JSON-списки в `admin_config` (ключи
`media_reactions.*`) — паттерн `loser_reasons`/`bot_reactions`: дефолты живут в
коде (`services/media_reactions.py`), в БД пишется только кастомизация. Так нет
лишней миграции и нагрузки на Neon. Архитектура: чистое ядро
`app/services/media_reactions.py` (пулы-дефолты, выбор/подстановка, ролл шанса,
get/set настроек) + грязный handler `app/bot/handlers/media_reactions.py`
(детектор альбомов, серия `asyncio`-тиков, вызовы TG API). **Backend P5 закрыт
целиком; остаётся только админ-UI (frontend) — вынесен в P5.6.**

### P5.1. Хранилища пулов
- [x] **P5.1.a.** (2026-06-03, main `@42dc7b8`) Пулы single/collection фраз +
  emoji whitelist хранятся как JSON в `admin_config`
  (`MEDIA_SINGLE_PHRASES_KEY`/`MEDIA_COLLECTION_PHRASES_KEY`/
  `MEDIA_EMOJI_WHITELIST_KEY`, см. `admin_config.py`). CRUD-эндпоинты:
  `GET/PUT /admin/media-reactions/{single-phrases,collection-phrases,
  emoji-whitelist}` (`routes_admin.py:1153-1207`, `MediaPhrasesOut`,
  дедуп+чистка через `_clean_list` при записи).
- [x] **P5.1.b.** (2026-06-03, main `@42dc7b8`) Seed пулов из GHG7.txt:
  `DEFAULT_SINGLE_PHRASES` (43 фразы, стр. 58–101), `DEFAULT_COLLECTION_PHRASES`
  (34 фразы, стр. 105–140), `DEFAULT_EMOJI_WHITELIST` (12 TG-реакц.-эмодзи).
  Дефолты в коде — подхватываются до первой правки админом (как loser_reasons).
- [x] **P5.1.c sync** (2026-06-03) Закрыт общим sync P5.6.c (один проход
  backend → HF-копия по всем файлам P5).

### P5.2. Детектор медиа-сообщений
- [x] **P5.2.a.** (2026-06-03, main `@<P5-handler>`) `on_media`
  (`handlers/media_reactions.py`) матчит `F.content_type.in_(_MEDIA_CONTENT_TYPES)`
  (photo/video/animation/document/sticker/voice/video_note/audio). Альбом
  собирается по `media_group_id` в `_AlbumBuf` с debounce `_ALBUM_DEBOUNCE_SEC=2с`,
  затем `classify_album(count)`: 2+ → `collection`, иначе `single`. Фильтры:
  только group_chat_id, не-бот, whitelist. on_media завершается `raise
  SkipHandler` (пропагация к chat_capture, как P0.3.e).
- [x] **P5.2.b.** (2026-06-03) In-memory `_recent[chat_id]=(kind,message_id,
  author_name)` + `get_recent(chat_id,kind)` для force-кнопок (P5.5.c). Теряется
  при рестарте Space — приемлемо (эфемерно). `_reacted` set — медиа с уже
  случившейся живой реакцией (через `@message_reaction`-роутер `on_reaction`).
- [x] **P5.2.c sync** (2026-06-03) Закрыт общим sync P5.6.c.

### P5.3. Реакции эмодзи на одиночный мем
- [x] **P5.3.a.** (2026-06-03) Whitelist эмодзи редактируемый в админке
  (см. P5.1.a, `emoji-whitelist` CRUD; UI — P5.6). Дефолт
  `DEFAULT_EMOJI_WHITELIST`.
- [x] **P5.3.b.** (2026-06-03) `_send_emoji_reaction` →
  `bot.set_message_reaction([ReactionTypeEmoji(emoji=...)])`, best-effort
  (неподдерж. эмодзи/сетевые сбои логируются и глотаются). `single_response_mode`
  ∈ {emoji,phrase,both,random_one} управляет, слать ли эмодзи и/или фразу на
  одиночный мем.
- [x] **P5.3.c sync** (2026-06-03) Закрыт общим sync P5.6.c.

### P5.4. Реакции фразами на подборку
- [x] **P5.4.a.** (2026-06-03) Подборка → всегда reply-фразой из `collection`-пула
  (`_do_react` ветка `kind=="collection"`), `%username%` → имя автора через
  `substitute_username`. Одиночный мем — фраза из `single`-пула (если режим
  это предусматривает).
- [x] **P5.4.b sync** (2026-06-03) Закрыт общим sync P5.6.c.

### P5.5. Поведение / шансы / выжидание
- [x] **P5.5.a.** (2026-06-03) Настройки в `admin_config`:
  `mode` ∈ {always,chance,wait_then_chance,never} (дефолт wait_then_chance),
  `chance_base_pct`/`chance_max_pct` (дефолт 10/50), `single_response_mode`,
  master `enabled` + `single_enabled`/`collection_enabled`.
  `get/set_media_reactions_settings` + `GET/PUT /admin/media-reactions/settings`
  (`MediaReactionsSettingsIO`). UI-тумблеры — P5.6.
- [x] **P5.5.b.** (2026-06-03) `wait_then_chance`: серия отложенных проверок
  `WAIT_TICKS_MIN=(5,10,15,30,45,60,90,120,180,260)` мин. На каждом тике: если
  уже была живая реакция (`_reacted`) — молча выходим; иначе ролл `tick_chance`
  (линейный рост base→max по номеру тика) → при успехе реагируем. Режим `chance`
  идёт той же серией, `always`/`never` — без серии (мгновенно/молчим).
- [x] **P5.5.c.** (2026-06-03) Backend готов:
  `POST /admin/media-reactions/force/{kind}` (`routes_admin.py`, `MediaForceOut`)
  → `react_now` на последнем медиа из `get_recent` (404 если нет недавнего/после
  рестарта). Кнопки в самом UI — P5.6.
- [x] **P5.5.d sync** (2026-06-03) Закрыт общим sync P5.6.c.

### P5.6. Backend-консолидация + админ-UI (frontend)
- [x] **P5.6.a.** (2026-06-03) **Backend-консолидация.** Незакоммиченный handler
  (`handlers/media_reactions.py`), регистрация роутера в `dispatcher.py` (после
  bot_reactions, перед chat_capture), `message_reaction` в `allowed_updates`
  вебхука (`main.py` — иначе TG не шлёт апдейты живых реакций), force-эндпоинт
  (`routes_admin.py`) и тесты детектора (`test_media_reactions_detector.py`)
  закоммичены поверх `@42dc7b8`. Прогон pytest: **220 passed** (ядро 12 +
  детектор 8 поверх 200 из P9). `pick_phrase`/`pick_emoji`/`tick_chance`/
  `roll_chance` принимают опц. `rng` для детерминированных тестов.
- [x] **P5.6.b.** (2026-06-03) Админ-UI `MediaReactionsScreen.tsx`: (1) секция
  поведения — master `enabled`, select `mode` (always/chance/wait_then_chance/
  never), при chance/wait — числовые `chance_base_pct`/`chance_max_pct`, select
  `single_response_mode`, тоглы single/collection_enabled; **авто-save** при
  каждом изменении (паттерн BotReactionsScreen). (2) три пула через переиспольз.
  `ReasonsEditor` (single-фразы, collection-фразы, emoji-whitelist; каждый со
  своим save). (3) две force-кнопки → `POST /media-reactions/force/{kind}`,
  алерт по message_id. API-обёртки в `api/admin.ts` (`fetchMediaSettings`/
  `updateMediaSettings`/`fetch|updateMedia{Single|Collection}Phrases`/
  `fetch|updateMediaEmojiWhitelist`/`forceMediaReaction`, типы `MediaMode`/
  `MediaSingleResponseMode`). В `AdminScreen` новая Card «🎭 Реакции на медиа» в
  группе «🤖 Реакции» + Section `media-reactions` + роутинг. `npx tsc --noEmit`
  чист по затронутым (baseline: 2 предсущ. ошибки `HistoryScreen.tsx`). Push в
  `kickmesc-dotcom/meetup-planner` (Pages) — пользователь.
- [x] **P5.6.c sync** (2026-06-03) 8 файлов backend P5
  (`services/media_reactions.py`, `services/admin_config.py`, `routes_admin.py`,
  `dispatcher.py`, `main.py`, `handlers/media_reactions.py`,
  `tests/test_media_reactions.py`, `tests/test_media_reactions_detector.py`) →
  `meetup-planner-backend/` (`diff -q` пуст по всем 8, HF-копия **220 passed**).
  **HF env-напоминание:** новый `allowed_updates` включает `message_reaction` —
  применится при следующем рестарте Space (вебхук переустанавливается в
  `_set_webhook`). Push в HF — пользователь.

---

## P6 — новый генератор фраз с типажами

Источник: GHG7.txt стр. 151–179.

### P6.1. Хранилище персоналий вне git
- [ ] **P6.1.a.** Решить место хранения: HF Space env (PERSONAS_JSON) или
  отдельная таблица в Neon `participant_personas` (uid, persona_text). Учесть
  что проект — открытый git. Рекомендация — Neon, потому что текст длинный
  и редактируется.
- [ ] **P6.1.b.** Сидинг 6 персоналий из GHG7.txt стр. 154–159 — **руками
  пользователя через админку**, не коммитом.
- [ ] **P6.1.c.** Sync.

### P6.2. Генератор v2 (на персоналиях)
- [ ] **P6.2.a.** Алгоритм: выбор участника по весу активности → шаблон
  фразы из его персоналии (грамматические слоты) → склейка. Без LLM.
- [ ] **P6.2.b.** Унаследовать кулдауны и ручной триггер от v1.
- [ ] **P6.2.c.** Sync.

### P6.3. Переключатель v1/v2 в админке
- [ ] **P6.3.a.** Setting `phrase_generator.version` ∈ {`legacy`, `personas`}.
- [ ] **P6.3.b.** Sync.

### P6.4. (отложено) Цитатор реальных сообщений
В этой итерации **не делаем** — слишком большой объём. Только заметка:
требует индекса сообщений в Neon. Перенесено в GHG8/будущий чеклист.

---

## P7 — пул шуток на «мёртвый чат»

Источник: GHG7.txt стр. 200–201.
- [ ] **P7.1.a.** Таблица `dead_chat_phrases` (threshold ∈ {24h, 72h, week,
  month, half_year, year}, text, enabled).
- [ ] **P7.1.b.** Seed: безобидные → философские (см. примеры в GHG7).
- [ ] **P7.1.c.** Scheduler-job раз в час проверяет lastMessageAt чата и
  публикует фразу из пула соответствующего threshold (с anti-spam: один
  пост в threshold-окно).
- [ ] **P7.1.d.** Sync.

---

## P8 — ПРОД-ИНЦИДЕНТ: доставка лоха + частоты (КРИТ, деплой первым)

Диагностика 2026-05-31 (прямой коннект к Neon): бот жив (входящие апдейты
обрабатываются, паузы нет, scheduler пишет proxy.last_error), но автолох
30.05 (rolls 35/36) → loser_outbox `expired` по TimeoutError. Корень: все пути
лоха оборачивают send в `asyncio.wait_for(8.0)`, а рабочая «случайная фраза»
шлёт через тот же bot-синглтон БЕЗ обёртки (таймаут сессии 30с,
`_IPv4AiohttpSession(timeout=30.0)`, dispatcher.py:252). При throttling канала
(РКН) ответ TG 8–30с: фраза доходит, лох режется на 8с. Решение: env-таймаут
LOSER_SEND_TIMEOUT (дефолт 25с) + снижение частоты «пустых» healthcheck.

### P8.1. Env-таймаут отправки лоха в scheduler
- [x] **P8.1.a.** (2026-06-01) `scheduler.py:112` `_AUTOLOSER_SEND_TIMEOUT =
  float(_env_int("LOSER_SEND_TIMEOUT", 25))`. Подхватывают `_announce`
  (autoloser-job) и `_loser_outbox_retry_job`. Дефолт 25с < 30с сессии бота
  (`_IPv4AiohttpSession`): send успевает при throttling канала, не виснет
  дольше сессии. Прежние 8с резали доставку (прод 30.05: rolls 35/36 →
  outbox expired по TimeoutError). Комментарий-обоснование на :105-111.
- [x] **P8.1.b sync** (2026-06-01) `scheduler.py` → `meetup-planner-backend/`
  (diff -q пуст, см. P8.5.c — один общий sync scheduler.py).

### P8.2. Env-таймаут в публичном `/loser/roll`
- [x] **P8.2.a.** (2026-06-01) `routes_meetings.py` — добавлен локальный парсер
  `_loser_send_timeout()` (env `LOSER_SEND_TIMEOUT`, дефолт 25.0, фолбэк на
  мусоре/пустой строке/non-int). `_LOSER_SEND_TIMEOUT` теперь = вызов парсера.
  Использование без изменений (`_announce` → `asyncio.wait_for(timeout=...)`).
  Добавлен `import os`.
- [x] **P8.2.b sync** (2026-06-01) `routes_meetings.py` →
  `meetup-planner-backend/` (diff -q пуст).

### P8.3. Консистентность admin force-reroll (verify-only)
- [x] **P8.3.a.** (2026-06-01) **Проверено.** `routes_admin.py:1318`
  `bot.send_message` идёт БЕЗ `asyncio.wait_for` — ограничен только таймаутом
  самой сессии бота (30с), `_announce` глотает любое исключение
  (`except Exception → log.warning`). То есть admin force-reroll и так не страдал
  от 8с-обрезки. Код НЕ трогаем.

### P8.4. proxy_health: онлайн-статус раз в час
- [x] **P8.4.a.** (2026-06-01) `scheduler.py:103` `PROXY_HEALTH_INTERVAL_SEC`
  дефолт `_env_int(..., 3600)` (было 600). get_me(): 144/сутки → 24/сутки.
  Комментарий-обоснование :99-102. Свежесть индикатора падает до 1ч —
  осознанный компромисс ради бюджета канала.

### P8.5. loser_outbox_retry: 1 мин → 5 мин
- [x] **P8.5.a.** (2026-06-01) `scheduler.py:728` `IntervalTrigger(minutes=1,
  jitter=10)` → `minutes=5, jitter=30`. Шаг ретрая `_AUTOLOSER_RETRY_DELAY` и
  так 5 мин — ежеминутный тик 4 из 5 раз слал «пустой» SELECT в Neon
  (next_retry_at в будущем), минус бюджет Neon compute. Один осмысленный тик на
  окно. Комментарий-обоснование :719-726.
- [x] **P8.5.b.** (2026-06-01) **Зафиксировано (НЕ трогаем):**
  `bot_pause_auto_restore` IntervalTrigger 5мин (scheduler.py:711),
  reminders/birthdays — cron-job'ы (не интервальный спам). Только retry-job был
  избыточно частым.
- [x] **P8.5.c sync** (2026-06-01) `scheduler.py` → `meetup-planner-backend/`
  (diff -q пуст — один файл несёт P8.1+P8.4+P8.5).

### P8.6. Тесты + деплой P8
- [x] **P8.6.a.** (2026-06-01) `tests/test_loser_send_timeout_env.py` — 14
  кейсов: оба парсера (`routes_meetings._loser_send_timeout` float-обёртка и
  `scheduler._env_int` целочисленный) × {не задан→дефолт25, число, 0-граница,
  мусор→фолбэк, float-строка→фолбэк, пустая строка→фолбэк}. Прогон `.venv`
  pytest: **196 passed** (было 182).
- [x] **P8.6.b sync** (2026-06-01) `tests/test_loser_send_timeout_env.py` →
  `meetup-planner-backend/tests/` (diff -q пуст).
- [x] **P8.6.c.** (2026-06-01) **Запушено в HF** ассистентом (git PAT).
  Коммит `GHG7 P8` (`064e0fe`) поверх remote `b467188`. Заодно запушен
  «застрявший» P2.2 (`0f51cae`) — sync в HF-копию был, но не закоммичен.
  Rebase поверх двух HF-web-UI коммитов (`Update loser.py`/`chukhan.py`,
  `b467188`/`e4cbff4`) — их содержимое уже было в main (loser идентичен,
  chukhan отличался хвостовой пустой строкой → выровнено). Также починен
  `.gitignore` (был UTF-16, git его игнорировал → `.venv`/`__pycache__`
  светились untracked; пересохранён UTF-8, `ec0982c`). DEPLOY_NOTES.md про
  env `LOSER_SEND_TIMEOUT`/`PROXY_HEALTH_INTERVAL_SEC` — TODO перед финалом GHG7.

---

## P9 — РАЗДЕЛЕНИЕ СЕМАНТИКИ «Лох дня» (👑) vs «Автолох-дуэль» (🤡)

Маппинг (гард от инверсии): `auto`→👑 «Лох дня» в историю · `manual` (admin
force-reroll, тихий прокрут лоха дня)→👑 в историю · `duel` (NEW: `/loser` +
LoserSheet)→🤡 «Автолох», НЕ в статистику. `LoserRoll.source` — String(16) без
CheckConstraint → 'duel' миграции не требует.

### P9.1. Backend: source='duel' + заголовки
- [x] **P9.1.a.** (2026-06-01) `chat_commands.py` `/loser` → `source="duel"`;
  header 🤡/«Лох дня» → 🤡/«Автолох».
- [x] **P9.1.b.** (2026-06-01) `routes_meetings.py` `/loser/roll` →
  `source="duel"`; `_announce` header 🎲/«Лох дня» → 🤡/«Автолох»;
  `loser_count`→None (duel не идёт в статистику, счётчик не показываем).
  Убран расчёт `counts`/`cnt`; `loser_stats` остаётся используемым в
  `loser_stats_endpoint` — импорт не трогаем.
- [x] **P9.1.c.** (2026-06-01) `routes_admin.py` force-reroll: `source="manual"`
  ОСТАВЛЕН; header 🤡/«Лох дня» → 👑/«Лох дня».
- [x] **P9.1.d.** (2026-06-01) `scheduler.py` (auto): `_announce` И retry-job —
  оба header 🤡/«Автолох сегодня» → 👑/«Лох дня». source остаётся "auto".
- [x] **P9.1.e sync** (2026-06-01) chat_commands, routes_meetings, routes_admin,
  scheduler → HF-копия (diff -q пуст, см. P9.6).

### P9.2. Backend: исключить duel из статистики/титулов
- [x] **P9.2.a.** (2026-06-01) `loser.py` `loser_stats`:
  `where(or_(source!='duel', source IS NULL))`. +импорт `or_`.
- [x] **P9.2.b.** (2026-06-01) `routes_calendar.py` titles_current лох дня:
  +фильтр `or_(source!='duel', source IS NULL)`. main_loser исключает duel
  автоматически через `loser_stats`.
- [x] **P9.2.c.** (2026-06-01) **Verify:** `time_until_next_roll` фильтрует
  `where(LoserRoll.source == source)` → duel получает собственный 12ч-кулдаун
  из коробки. Кода не трогали.
- [x] **P9.2.d sync** (2026-06-01) loser.py, routes_calendar.py → HF-копия.

### P9.3. Backend: 'duel' в calendar marks (verify-only)
- [x] **P9.3.a.** (2026-06-01) **Verify:** `calendar_marks` LEFT JOIN outbox
  прозрачен для duel (duel не пишет в outbox → `LoserOutbox.id IS NULL` →
  проходит). `build_marks` дедупит по (date,uid,source) → duel-марка отдельная.
  Кода не меняли.
- [x] **P9.3.b.** (2026-06-01) docstring `CalendarMark.source`: source ∈
  {auto,manual,duel}|None; auto/manual→👑, duel→🤡.
- [x] **P9.3.c sync** (2026-06-01) routes_calendar.py → HF-копия (с P9.2.d).

### P9.4. Frontend: исправить инверсию + duel
- [x] **P9.4.a.** (2026-06-01) `birthdays.ts`: `CalendarMark.source` и
  `LoserReason.source` → `"auto"|"manual"|"duel"|null`.
- [x] **P9.4.b.** (2026-06-01) `ParticipantRow.tsx`: в ячейках per-source
  иконки — auto/manual/null→👑, duel→🤡, рендерятся массивом `loserIcons`
  (короны, затем клоуны); compactLoser → `{loserIcons[0]}×N`. titleBadges
  (👑 лох дня / 🤡 главный лох) — это титулы, не source, не трогали.
- [x] **P9.4.c.** (2026-06-01) `LoserReasonPopover.tsx`: **инверсия исправлена**.
  `isDuel = source==='duel'` → 🤡 «Автолох» (+rolled_by_name); всё остальное
  (auto/manual/null) → 👑 «Лох дня». Docstring/заголовок/sourceLabel/блок
  rolled_by пересобраны (rolled_by теперь для duel, не manual).
- [x] **P9.4.d.** (2026-06-01) `actions/LoserSheet.tsx` title и
  `actions/ActionBar.tsx` label «🎲 Лох дня» → «🤡 Автолох» (публичная дуэль).
- [x] **P9.4.e.** (2026-06-01) Админ авто-лоха = «Лох дня» 👑:
  `AutoLoserScreen.tsx` (title + toggle-label), `AdminScreen.tsx` Card,
  `IntervalsScreen.tsx` (Block + hint с явным различением 👑/🤡),
  `ScheduledPublicationsScreen.tsx` ToggleBlock. Родовые `SectionGroup "Лох"`
  /`LoserScreen`/`HistoryScreen` (🤡 как обобщённая иконка раздела) — не в
  списке P9.4.e, не трогали.
- [x] **P9.4.f.** (2026-06-01) `npx tsc --noEmit` — чисто по затронутым файлам
  (2 предсущ. ошибки в `HistoryScreen.tsx`, не наши). Frontend push — пользователь.

### P9.5. Unit-тесты P9 (чистые, без БД)
- [x] **P9.5.a.** (2026-06-01) `test_calendar_marks.py::test_loser_auto_and_duel
  _same_day_both_kept` — [(d,uid,'auto'),(d,uid,'duel')]→две марки.
- [x] **P9.5.b.** (2026-06-01) `test_loser_header_mapping.py` (3 кейса):
  👑/«Лох дня», 🤡/«Автолох»+rolled_by без счётчика, контроль печати счётчика
  при заданном loser_count.
- [x] **P9.5.c.** (2026-06-01) Расширен `test_build_marks_still_accepts_source
  _tuples` ('duel'→марка с source='duel'). Прогон pytest: **200 passed**
  (было 196).
- [x] **P9.5.d sync** (2026-06-01) test_calendar_marks.py, test_loser_outbox.py,
  test_loser_header_mapping.py → HF-копия (200 passed и в HF-копии).

---

## P10 — УПРОЩЕНИЕ ИКОНОК-ШАПОК (откат P2.1.b, чисто фронт)

- [x] **P10.1.a.** (2026-06-01) `ParticipantRow.tsx`: массив `titleBadges`
  удалён целиком, заменён двумя флагами `isChukhan`/`isWorm` (по
  `chukhan_user_id`/`worm_user_id`). 🎂/👑/🤡 из шапки убраны — события и так
  видны в ячейках календаря.
- [x] **P10.1.b.** (2026-06-01) Рендер: 💩 — одиночный `<span>` СВЕРХУ по центру
  (`-top-2 left-1/2 -translate-x-1/2 z-20`, плашка `bg-tg-bg rounded-full`), без
  стека/`flex`.
- [x] **P10.1.c.** (2026-06-01) 🪱 — отдельный `<span>` СНИЗУ по центру
  (`-bottom-1 left-1/2 -translate-x-1/2 z-20`, та же плашка), при `isWorm`.
- [x] **P10.1.d.** (2026-06-01) title-атрибут аватарки пересобран из ролей
  💩 «Чухан недели» / 🪱 «Червь-пидор» (IIFE, склейка через `, `).
- [x] **P10.1.e.** (2026-06-01) Греп подтвердил: `loser_today_user_id`/
  `main_loser_user_id`/`birthday_today_user_ids` теперь только в типе
  `CurrentTitles` (birthdays.ts), фронт их НЕ читает. API не трогаем — поля
  оставлены в типе как контракт ответа (+комментарий P10.1.e). Реально
  используются worm/chukhan.
- [x] **P10.1.f.** (2026-06-01) `npx tsc --noEmit` — чисто по затронутым файлам
  (2 предсущ. ошибки в `HistoryScreen.tsx`, не наши). Висячих ссылок на
  `titleBadges` нет. Push в GitHub Pages — выполнен ассистентом (PAT).

  #Добавлено 03.05.26
  1. В понедельник скипнул чухана недели (возможно опять из-за проблем с коннектом) и следующего перенс на следующую неделю, получается задача не выполнена.
  2. В среду я вручную назначил ролл чухана, он скинул только одну часть поста вида: 🎉 Кравченко 🎉 возможно вторая отвалилась потому что у нас не проходит слишком много пакетов подряд. Хотел зайти на neon и поправить вручную, а он недоступен из под двух разных впн. Походу проблема не на нашем конце. Я сохранил лог инцидента в файле incidentlog.txt
  3. Функционал реакции на мемы исправен и в текущем виде работает четко. 
  4. Шапка в виде какашки почему-то имеет черный непрозрачный фон, что немного убивает визуал. На страницах календаря у этого эмодзи нет фона и он не оверлапится с элементами интерфейса.
  5. Я вручную добавил порядка 50-60 причин для лоха и чухана в файле chukhan.py и loser.py потом вручную закинул его на hf - В лохе появились. А в чухане в приложении показывает только 6 причин и они все старые (несмешные, возможно из самого первого билда). Там был косяк с запятой, я его пофиксил и рестартнул спейс - но в приложухе все равно 6 унылых причин. Вручную полез копнуть в неоне и тоже отредачил admin_config для соответствия. Проблема не решилась. После правки неона рестартнул спейс и все равно показывает 6 причин. Я хз где их еще искать.
  6. Сам чеклист надо будет актуализировать чтобы не засорять контекст. Убрать закрытые задачи, оставить то что предстоит сделать.
  7. Чел запостил подборку из двух фото (одно с подписью - описанием) и двух видосов, бот не среагировал, но там стоят стоковые шансы. При попытке вызвать принудительную реакцию на подборку - выдает "не найдено". Дальше пробую реакцию на один мем - долго думает, пишет что отправлено, по факту сообщения в чат нет. Логи закинул в файл memefail.txt - далее рестартнул спейс и подключился с телефона на другой впн (иногда как будто помогает), теперь и на кнопку реакции "на последний мем" - пишет не найдено. Видимо, история хранится в странном формате что после рестарта спейса бот не может видеть сообщения которые висят в чате.
  8. Ни в коем случае не убирай самый первый прокси который добавлен и до сих пор зеленый. Но с остальными надо разобраться, их вроде как придушили, в последнее время вся работа идет через direct. Но суть остается в том что они не работали и не работают. А кнопка "найти живые прокси" выдает сервис временно недоступен - с самого начала и ни разу не работала. Вряд ли мы сможем сейчас это решить.
  9. С прокси сейчас отдельная беда, вроде как РКН научился их вычислять и убивать на корню. В то же время сами прокси возможно имеют защиту от автоматизации (у живого человека если повезет - поработают до блока, а автоматизированные системы типа ботов проверку не проходят). Много раз замечал такое поведение что джобы зависают и не проходят, помогает посвапаться между прокси и директом, и его отпускает на время. Но потом опять залипает, как будто где-то прилетает блок за частые запросы. Иногда видел связь что принудительная отправка сообщения в чат не проходит, но если на телефоне поменять впн подключение, то сообщения идут. А вот с чем связи точно нет, так это если рестартнуть HF-space, в этом случае не бывает отвисаний. Слишком много переменных чтобы точно установить виновника.
  10. Предложи конкретные варианты решения этой проблемы на уровне Python-кода и архитектуры приложения. Меня интересуют следующие направления:
а) Реализация отказоустойчивого механизма (Fallback/Circuit Breaker): Как грамотно переписать асинхронный HTTP-клиент, чтобы при первом же сетевом таймауте или провале селф-теста он автоматически и бесшовно переключал пул на direct (прямое подключение) или ротировал прокси, не дожидаясь, пока зависнет вся очередь APScheduler?
б) Обход TLS Fingerprinting (JA3/JA4): Если прокси блокируют бота за то, что он "бот", как нам подменить TLS-отпечаток в асинхронном клиенте? Напиши пример интеграции более скрытных библиотек (например, curl_cffi вместо стандартного httpx/aiohttp) в контекст Telegram-бота.
в) Оптимизация асинхронных таймаутов: Как правильно сконфигурировать ClientTimeout и настройки пула соединений, чтобы предотвратить 30-секундные зависания фоновых задач?
г) Смена стратегии Webhook -> Long Polling: Если бот сейчас работает на вебхуках, покажи пример кода, как безопасно перевести его на Long Polling с кастомным конфигом прокси/клиента, чтобы Telegram DC сам не пессимизировал доставку апдейтов из-за неотвеченных вебхуков. Только нужна не полная замена, а именно переключаемая опция чтобы сохранить и новый и старый метод, с возможностью переключения на лету.


---

## Отложено явно (НЕ в этой итерации)

- **Бот сам постит мемы.** GHG7.txt стр. 203–204. Пользователь явно пишет
  «Пока не реализуем».
- **Реальный цитатор** (P6.4). Перенесён в GHG8.

---

## D-MEM — обновить память после релиза GHG7

- [x] **D-MEM.** (2026-06-01) Обновлён `project_meetup_planner_deployed.md`:
  дата актуальности → 2026-06-01 (релиз P0–P10 задеплоен), новые env
  `LOSER_SEND_TIMEOUT`/`PROXY_HEALTH_INTERVAL_SEC`, новая таблица `loser_outbox`
  (миграция 0014), уточнён push-доступ ассистента (git PAT пушит в HF и GitHub,
  P8.6.c/P10.1.f) + гард про устаревающий `origin/main` ref (fetch перед
  выводами «ahead N»). Проверка деплоя: `git fetch` обоих remote → HF `cf79c18`
  (P9), Pages `773f688` (P10), локально `0 0` — всё на remote.
