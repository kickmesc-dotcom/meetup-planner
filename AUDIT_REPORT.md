# 🔍 AUDIT_REPORT — «GHG»: Telegram-бот + Mini App + игровая/социальная платформа

Отчёт по мастер-скиллу **PRINCIPAL AUDITOR** (формат A–N), выполнен по
`AUDIT_PLAN.md`. Основа — чтение кода (`meetup-planner-main/backend/**`,
`frontend/src/**`), baseline-прогон тестов и рантайм-проверки обоих хостов.

- Ревизия кода: `backend` `35aee1f`+ (ветка `main`), зеркало `meetup-planner-backend`.
- Baseline (до правок этой партии): backend **989 passed**; frontend `typecheck` OK,
  `vitest` **13 passed**.
- Итог после правок GHG11(5): backend **1003 passed**; `vitest` **24 passed**.
- Прод-ревизии: alembic head `0026_music_track_likes`; `/api/meta` fp `3e372e27a6df`.
- Живые хосты: Amvera `meetup-planner-youmakemefry.waw0.amvera.tech` (build
  `9513529430bd`), HF `fryesw-meetup-planner-backend.hf.space` (build `330a710`) —
  оба отвечают `status:ok` на ОДНУ Neon. `getWebhookInfo` → webhook на Amvera.

Формат находок: `ID · Severity · Component · File · Symbol · Evidence · Why ·
Failure scenario · Fix · Regression test`. Статус `FIXED` — исправлено в этой
партии; `OPEN` — вынесено в `N. PATCH PLAN`.

---

## A. EXECUTIVE SUMMARY

1. **Система в целом крепкая и зрелая.** Разделены `DATA`/`CONFIG`, единая
   «дверь» доставки фич (`delivery.py`), единая чат-дверь (`journal.send_now`),
   server-side верификация initData, secret-token на webhook, идемпотентность XP
   через `xp_grants`, десятки уникальных индексов.
2. **Главный найденный риск — двойной планировщик (H1, `P1`, FIXED).** Amvera и HF
   Space крутят один код против одной Neon; APScheduler стартовал в lifespan
   КАЖДОГО процесса → дубли ежедневных анонсов (автолох/фразы/чухан/ДР/праздники).
   Подтверждено кодом и тем, что оба инстанса живы. Исправлено single-writer-лизом.
3. **Второй инфраструктурный риск — «флап» webhook (F2, `P2`, OPEN).** `_set_webhook`
   зовётся в lifespan каждого хоста; если `PUBLIC_BASE_URL` задан на обоих, webhook
   перепривязывается к тому, кто перезапустился последним. Сейчас указывает на
   Amvera — но гарантии нет, поведение зависит от env. Требует подтверждения.
4. **Откат XP при модерации (H3, `P2`, FIXED).** Админское каскадное удаление
   голосового задания стирало строки, но НЕ отзывало опыт (ручной withdraw из
   мини-аппа откатывал). Теперь откат есть на обоих путях.
5. **AUTH/ADMIN — почти образцово.** Все 150 роутов `routes_admin.py` защищены
   `_ensure_admin` (единственное исключение — читающий `/chukhan/leaderboard`,
   требует лишь аутентификации; F8). initData проверяется HMAC+`compare_digest`.
6. **Порядок DB↔Telegram в основном «сначала БД, потом чат».** Анонсы —
   best-effort (`journal`), потеря анонса не теряет данные; лох использует outbox.
   Хороший паттерн `KEEP`.
7. **Остаются точечные гонки** (F4, F5): голос в номинациях без DB-уникальности,
   дедуп `update_id` отсутствует, `correct_voter_ids` — read-modify-write JSONB.
   Не блокеры, но при росте нагрузки может «уехать» счётчик.
8. **Админ-опасные действия без audit-log** (F7, `P3`): reset XP / restore snapshot /
   clear pool не пишут в `event_log`. Откат — только «вручную».
9. **GHG11(5) расширил одинаковый обзор ленты:** миниатюры участников теперь и у
   лох/чухан/активности фич, а не только у голосовых/музыки.
10. **Тесты:** 1003 backend + 24 frontend, добавлены регрессионные тесты на
    single-writer лиз, откат XP и миниатюры + тесты CTA/вида ленты.
11. **Вердикт:** система МОЖЕТ быть надёжной production-платформой —
    `YES WITH CONDITIONS` (см. раздел M).

### Оценки (обоснование — по разделам ниже)

```text
PROJECT HEALTH:      8/10   — зрелая структура, единые абстракции, хорошие индексы
ARCHITECTURE:        8/10   — слои разделены; минус за два инстанса на одной БД
SECURITY:            8/10   — HMAC initData, secret-token, admin-guard; минус: dev-URL, audit-log
DATA INTEGRITY:      7/10   — сильные unique-key; минус: гонки номинаций/update_id, orphan EV
TELEGRAM INTEGRATION:8/10   — allowed_updates, outbox-паттерны; минус: webhook-флап
MINI APP:            8/10   — песочница dev-initData, единый store; минус: HapticFeedback v6
SCHEDULER:           7/10   — 26 джобов, watchdog, retry; минус (был P1) двойной запуск
CONCURRENCY:         6/10   — max_instances внутри процесса; межпроцессных блокировок почти нет
TEST COVERAGE:       8/10   — 1003+24, но нет e2e/cross-channel и scheduler-distributed
OPERABILITY:         7/10   — /api/meta, watchdog, collapse; минус: ручной деплой зеркала
```

---

## B. ACTUAL TECH STACK

| Layer | Actual technology | Version | Evidence | Risk |
|---|---|---|---|---|
| Backend | FastAPI | 0.115.6 | `backend/pyproject.toml` | low |
| Bot | aiogram (webhook) | 3.13.1 | `app/bot/webhook.py`, `app/main.py` | low |
| ORM | SQLAlchemy async | 2.0.36 | `app/db/base.py`, `models.py` | low |
| DB driver | asyncpg | 0.30.0 | `pyproject.toml` | low |
| Migrations | Alembic | 1.13.3 | `alembic/versions/` — 27 ревизий, head `0026_music_track_likes` | low |
| Schemas | Pydantic | 2.9.2 | `app/schemas/*` | low |
| Scheduler | APScheduler AsyncIOScheduler | 3.10.4 | `app/bot/scheduler.py` | **med** (был двойной запуск) |
| Frontend | React + TS + Vite | React 18 / Vite 5 | `frontend/package.json` | low |
| Frontend tests | vitest + jsdom + testing-library | vitest 2 | `frontend/vitest.config.ts` | low |
| DB (prod) | Neon Postgres | server 17.11 | `/api/meta` → `db.provider=neon` | med (free-tier suspend) |
| Hosting | Amvera **и** HF Space | — | оба `/api/meta` `status:ok` | **med** (два писателя) |
| Frontend hosting | Cloudflare Pages | — | аудит-заметки, автопересборка | low |

---

## C. ACTUAL ARCHITECTURE

```text
Telegram
  └─ POST /tg/webhook           (X-Telegram-Bot-Api-Secret-Token)   app/bot/webhook.py
       └─ dp.feed_update → handlers/*                              app/bot/handlers/
Mini App (Cloudflare Pages)
  └─ /api/*   (Authorization: tma <initData>)                      frontend/src/api/client.ts
       └─ CurrentUser = deps.current_user                          app/api/deps.py
            └─ HMAC-verify + whitelist                             app/auth/initdata.py
Бизнес-логика
  └─ services/*  →  services/game/* (экономика, лента, доставка)
Scheduler (в процессе FastAPI, lifespan)
  └─ AsyncIOScheduler  → 26 jobs                                   app/bot/scheduler.py
       ├─ лидер-лиз: admin_config[scheduler.leader]                services/scheduler_leader.py  (GHG11(5))
       ├─ chat: journal.send_now
       └─ app:  delivery.record_feed_event → game_journal(kind=feature)
Feed
  └─ GET /api/game/feed → feed.build_feed()                        services/game/feed.py
DB (Neon) — единый источник истины для ОБОИХ хостов
```

Ключевая особенность: два процесса (Amvera, HF) на одну БД. Это и создаёт риск
H1 (решается single-writer'ом) и F2 (webhook ownership).

---

## D. FEATURE MATRIX

`Chat`/`App` = куда уходит активность; `Sched` = есть ли джоб; `XP` = начисляет
опыт; `Events` = как попадает в ленту. Режимы управляются `delivery.py`
(`off/chat/app/both`) + master-свитчеры (`general`, `achievements`).

| Feature | Chat | App | Sched | DB state | XP | Events | Risk |
|---|---|:---:|:---:|---|:---:|---|:---|
| Планер встреч | ✔ | ✔ | reminders | `meetings`, `meeting_reminders` | meeting/availability | chat+app | низкий |
| Опросы | ✔ | ✔ | — | `polls`, `poll_votes` | — | chat+app | низкий |
| Лох (ручной/авто) | ✔ | ✔ | `autoloser` | `loser_rolls`, `loser_outbox` | became_loser | chat(лента) | **med** (H1 был) |
| Чухан недели | ✔ | ✔ | `chukhan_weekly` | `weekly_chukhan` | became_chukhan | chat+app | низкий |
| Фразы / zaebal | ✔ | ✔ | `random_phrases`, `auto_zaebal` | `chat_messages`, AC | — | chat | med (H1) |
| Случайные события | ✔ | ✔ | `game_events_hourly` | `game_prompts`, `event_log` | event | chat+app | низкий |
| Магический шар | ✔ | ✔ | — | `game_prompts`/AC; `event_log` | — | app (feed) | низкий |
| Червь | ✔ | ✔ | — | `worm_assignments`, EV | — | chat+app | низкий |
| Контрабанда | ✔ | ✔ | — | `event_log` | contraband | chat+app | низкий |
| Поминовения | ✔ | ✔ | `game_memorial_daily` | `event_log` | — | chat+app | низкий |
| Мёртвый чат | ✔ | ✔ | `dead_chat_hourly` | `chat_messages` | — | app | низкий |
| Голосовые задания | ✔ | ✔ | `game_voice_tick` | `game_voice_tasks/submissions` | voice/voice_best | chat+app | **med** (H3 был) |
| Музыкальная предложка | ✔ | ✔ | `game_music_weekly` | `music_selections/tracks` | music | chat+app | низкий |
| Мьюзик-гейм | ✔ | ✔ | `game_music_game_weekly` | `music_game_rounds` | music_author/guess | chat+app | **med** (F5) |
| Номинации | ✔ | ✔ | — | `game_nominations`, EV | — | app (feed) | **med** (F4) |
| Реакции (бот/медиа/чат) | ✔ | ✔ | — | `game_media_posts`, EV | — | app | низкий |
| Ачивки | ✔ | ✔ | `game_achievements_flush` | `user_achievements`, `xp_*` | achievement | chat/app/both | низкий |
| Дни рождения | ✔ | ✔ | `birthdays_daily` | `birthdays`, `birthday_notifications` | birthday | chat | низкий |
| Праздники | ✔ | ✔ | `game_holidays_daily` | `game_holidays` | holiday | chat+app | низкий |
| Прокси | — | admin | `proxy_health` | `proxy_entries` | — | — | низкий |
| Рестарт Space | — | admin | `space_restart_tick` | AC | — | — | низкий |

---

## E. WHAT IS ALREADY GOOD (KEEP)

Не критика, а явные сильные решения — их менять НЕ нужно:

- **Единая модель доставки** `services/game/delivery.py`: одна функция
  `get_feature_mode`, чистые предикаты `chat_enabled/app_enabled/is_active`,
  `route_feature` как единственный маршрутизатор. Убирает разъехавшиеся `if`.
- **Единая чат-дверь** `services/game/journal.py::send_now` + правило «анонс —
  украшение, не работа»: сбой TG не теряет данные и возвращает `False`.
- **Идемпотентность XP:** `xp_grants` с UNIQUE `(user_id, idem_key)` — повторный
  тик/апдейт не начисляет дважды. Это ровно тот паттерн, что требует скилл.
- **Правильные DB-constraints:** `uq_poll_vote`, `uq_game_voice_submission`,
  `uq_music_track_like`, `uq_user_achievement`, `uq_weekly_chukhan_week`,
  `uq_game_holiday_md`, `uq_meeting_reminder`, `uq_birthday_notif`, `uq_chat_msg`.
- **Outbox для лох-постов** (`loser_outbox`, `FOR UPDATE SKIP LOCKED`, retry job) —
  доставка восстанавливается после сбоя канала, календарь не рисует фантомов.
- **Watchdog + master-collapse** (`scheduler.collapse_stale_jobs/_all_jobs`) —
  зависшая задача не блокирует следующие запуски.
- **Транзиентные retry** (`_is_transient_db_error`): DNS/сокет/таймаут гасятся
  без маскировки логических ошибок.
- **Server-side AUTH:** HMAC `WebAppData` + `compare_digest` + окно `max_age`
  (`auth/initdata.py`); идентичность по `users.telegram_id`; whitelist.
- **Webhook secret-token** и корректный `allowed_updates` (включая
  `message_reaction`) — без него реакций бы просто не было.
- **Единый `admin_config`** как KV для настроек и ad-hoc маркеров (модерация ленты,
  лиз лидерства) — расширяемо без миграций.
- **Observability:** структурированные логи (`job_fired/job_done/job_failed`,
  `webhook.set`, `db.engine_created`), `/api/meta` как паспорт контейнера.
- **Тесты:** 1003 backend + 24 frontend, `asyncio_mode=auto`, фейковые сессии
  повторяют строгость реальной БД (`tests/game_fakes.py`).

---

## F. CRITICAL FINDINGS

Severity: `P0` blocker/data-loss/security · `P1` critical before prod · `P2` serious
bug · `P3` medium · `P4` minor.

### F1 — Двойной запуск планировщика (H1). `P1` · `FIXED`

- **File:** `backend/app/main.py` (lifespan), `backend/app/bot/scheduler.py`
  (`start_scheduler`).
- **Symbol:** `lifespan` → `start_scheduler(get_bot())`; `AsyncIOScheduler`.
- **Evidence:** `lifespan` безусловно стартовал `AsyncIOScheduler` в каждом
  процессе; никакой leader/advisory-lock в коде НЕ было (`grep advisory|leader|`
  `primary_instance → пусто`). Оба хоста живы на одну Neon (`/api/meta` обоих =
  `status:ok`, fp `3e372e27a6df`). `max_instances=1`/`coalesce` действуют только
  ВНУТРИ процесса.
- **Why it is a problem:** два независимых планировщика стреляют одни и те же
  cron-времена; `_autoloser_job` идёт с `bypass_cooldown=True`, `random_phrases`,
  `chukhan`, `birthdays`, `holidays` не имеют кросс-процессной защиты → дубли
  постов в групповой чат.
- **Failure scenario:** обоим хостам прилетает 18:00 Мск → каждый делает свой
  ролл → в чате два разных «👑 Лох дня» с разными людьми; вечером две случайные
  фразы; в понедельник — потенциально два пика чухана (частично спасает
  `uq_weekly_chukhan_week`, но чат-пост мог уйти дважды до commit-конфликта).
- **Fix (robust):** single-writer-лиз лидерства в `admin_config`
  (`services/scheduler_leader.py`): `acquire_or_renew` через `SELECT … FOR UPDATE`,
  heartbeat каждые `SCHEDULER_LEASE_RENEW_SECONDS` (60с), TTL
  `SCHEDULER_LEASE_TTL_SECONDS` (300с). Планировщик поднимает только лидер;
  потеряв лиз — гасит свои джобы. Фейловер: если лидер умер, второй забирает лиз
  после истечения TTL. Гейт включается в `lifespan` (`arm_leader_gate`);
  kill-switch `SCHEDULER_LEADER_DISABLED=true` возвращает прежнее поведение.
- **Regression test:** `tests/test_scheduler_leader.py` — 9 тестов (чистое решение,
  acquire/renew, отказ второму, failover после TTL, release, гейт не-лидера).

### F2 — «Флап» владельца webhook между двумя хостами. `P2` · `OPEN`

- **File:** `backend/app/main.py` (`_set_webhook`, `_register_telegram_metadata_with_retry`).
- **Symbol:** `_set_webhook()` — `bot.set_webhook(url=f"{settings.public_base_url}/tg/webhook")`.
- **Evidence:** `_set_webhook` вызывается в lifespan КАЖДОГО хоста; url берётся из
  `PUBLIC_BASE_URL` (default `""`). Есть операторский инструмент
  `tools/switch-db.py webhook amvera|hf`, т.е. переключение осознанно ручное.
  Сейчас `getWebhookInfo` → Amvera. `NOT PROVEN — needs runtime verification`:
  задан ли `PUBLIC_BASE_URL` на HF Space (если да — webhook «уезжает» на того,
  кто перезапустился последним).
- **Why it is a problem:** если webhook привязан к «спящему» HF Space (free-tier),
  апдейты могут теряться на время засыпания/пробуждения.
- **Failure scenario:** HF Space просыпается и делает `set_webhook` на себя →
  через минуту засыпает → Telegram шлёт апдейты в недоступный URL, сообщения
  копятся в `pending_update_count`.
- **Fix (minimal):** задать `PUBLIC_BASE_URL` ТОЛЬКО на каноническом хосте (Amvera)
  и оставить HF без него (тогда `_set_webhook` там логирует `skip_no_public_base_url`);
  либо добавить env `TG_WEBHOOK_DISABLE=true` на второй хост. Проверить фактом
  `getWebhookInfo` после рестарта обоих.
- **Regression test:** операторский смоук — `getWebhookInfo.url` после рестарта
  обоих хостов должен остаться на каноническом.

### F3 — Опыт не откатывался при админском удалении голосового задания (H3). `P2` · `FIXED`

- **File:** `backend/app/services/game/feed_moderation.py` (`_cascade_delete`),
  `routes_game.voice_withdraw_api`, `services/game/awards.py::revoke_voice`.
- **Symbol:** `_cascade_delete(prefix="voice")`.
- **Evidence:** ручной withdraw из мини-аппа зовёт `awards.revoke_voice`
  (`routes_game.py:1173`), а админский каскад удалял `game_voice_submissions` и
  `game_voice_tasks` БЕЗ отката — `revoke_voice` имел единственного вызывающего
  (тот самый withdraw-эндпоинт).
- **Why it is a problem:** награда за удалённый контент остаётся на игроке;
  поведение двух путей удаления расходится (inconsistent rollback).
- **Failure scenario:** админ убирает из ленты голосовое задание → участники
  сохраняют +50 XP и ачивку «подал голос» за несуществующий вариант.
- **Fix (minimal):** в voice-ветке каскада собрать сдачи ДО удаления, отозвать XP
  (`awards.revoke_voice`) с учётом режима `first_only` (только первому) и отметить
  `voice_withdrawn`, чтобы пересозданное задание не дало второй XP.
- **Regression test:** `tests/test_game_ghg11_3.py` —
  `test_cascade_delete_voice_revokes_xp_all` и `..._first_only_revokes_first`.

### F4 — Голос в номинациях без DB-уникальности (H2). `P3` · `OPEN`

- **File:** `backend/app/services/game/nominations.py`.
- **Symbol:** `toggle_vote` — `sa_delete(EventLog where game_vote/user)` затем
  `session.add(EventLog(kind=game_vote))` в одной транзакции.
- **Evidence:** `event_log` не имеет уникального индекса на
  `(kind, payload->>'nomination_id', payload->>'user_id')`; логика «один голос»
  держится только на предварительном `my_vote` SELECT.
- **Why it is a problem:** классический read-modify-write без блокировки.
- **Failure scenario:** двойной тап/повторный запрос в один момент → оба видят
  «голоса нет» → два INSERT → счётчик номинации завышен на 1.
- **Fix:** уникальный partial-индекс в Postgres
  `CREATE UNIQUE INDEX … ON event_log ((payload->>'user_id'), (payload->>'nomination_id')) WHERE kind='game_vote'`
  (или отдельная таблица `game_votes` с `uq(nomination_id,user_id)`).
- **Regression test:** параллельные `toggle_vote` для одного юзера → ровно 1 голос.

### F5 — Нет дедупа `update_id`; муз-гейм read-modify-write JSONB. `P3` · `OPEN`

- **File:** `backend/app/bot/webhook.py`, `services/game/music_game.py::register_guess`.
- **Symbol:** `dp.feed_update`; `round.correct_voter_ids = voters`.
- **Evidence:** webhook проверяет secret-token, но не хранит
  обработанные `update_id`; `register_guess` читает список, проверяет
  `user_id in voters`, добавляет и commit'ит.
- **Why it is a problem:** Telegram может доставить апдейт повторно (ретраи);
  JSONB-мутация ловится только логикой в памяти.
- **Failure scenario:** повторный `poll_answer` → игрок дважды в
  `correct_voter_ids` → дубль в миниатюрах ленты (XP‑итог считается по списку
  без `set()`).
- **Fix:** кэш `update_id` (Redis/таблица с TTL) ИЛИ идемпотентный ключ;
  в `register_guess` дедуп множеством и запись atomic `UPDATE … jsonb`.
- **Regression test:** два одинаковых `poll_answer` → одна запись в списке.

### F6 — Orphan-записи `event_log` при каскадном удалении. `P4` · `OPEN`

- **File:** `services/game/feed_moderation.py`.
- **Symbol:** `_cascade_delete`.
- **Evidence:** при удалении голосового задания стираются submissions/task,
  но остаются `EventLog` с `kind in (voice_like, voice_withdrawn, voice_task_mode)`,
  ссылающиеся на исчезнувшие id; `feed_delete/feed_hide` тоже накапливаются.
- **Why it is a problem:** не влияет на ленту (фильтр по `item_id`), но таблица
  `event_log` растёт мусором; долгосрочно — стоимость хранения/скорость выборок.
- **Failure scenario:** много удалений → тысячи неиспользуемых строк.
- **Fix:** в `_cascade_delete` подчищать `EventLog` по `payload`-идентификаторам
  удаляемых сущностей (best-effort), либо периодический GC-job.
- **Regression test:** после удаления voice-задания нет EV с его `submission_id`.

### F7 — Админ-опасные действия без audit-log (H8). `P3` · `OPEN`

- **File:** `backend/app/api/routes_admin.py`, `services/game/achievements.py`,
  `services/phrase_snapshot.py`.
- **Symbol:** `reset XP` / `snapshot restore` / `clear random-phrases pool`.
- **Evidence:** эти ручки меняют состояние, но не пишут в `event_log` (сравните с
  `worm_punish`, `feed_delete` — там запись есть).
- **Why it is a problem:** нет следа «кто и что стёр»; спорный инцидент не разобрать.
- **Failure scenario:** случайный reset XP → никаких доказательств, откат только
  из бэкапа БД.
- **Fix:** писать `EventLog(kind="admin_action", actor_user_id, payload={...})` на
  каждую мутирующую admin-ручку (можно декоратором `_ensure_admin` + лог).
- **Regression test:** вызов reset XP создаёт ровно одну запись `admin_action`.

### F8 — Единственный неохраняемый admin-роут. `P4` · `OPEN (likely by design)`

- **File:** `backend/app/api/routes_admin.py`.
- **Symbol:** `GET /chukhan/leaderboard` (`chukhan_leaderboard`) — `_: CurrentUser`
  без `_ensure_admin`.
- **Evidence:** перечень 150 роутов против `_ensure_admin`/`_game_gate` — только
  этот не имеет admin-guard (остальные защищены).
- **Why it is a problem:** формально это «admin-неймспейс», но данные — публичный
  топ; утечки нет (требуется аутентификация). Скорее naming-нюанс.
- **Failure scenario:** не наблюдаю злоупотребления; любой вошедший видит топ чуханов.
- **Fix:** либо оставить как есть (документировать «public under /admin»), либо
  перенести в `routes_game` (или добавить `_ensure_admin`, если топ только для админа).
- **Regression test:** тест-перечень «все мутирующие /admin-ручки зовут `_ensure_admin`».

### F9 — dev-лазейка `?initData=` в URL. `P4` · `OPEN (by design)`

- **File:** `frontend/src/tg/webapp.ts::getInitData`.
- **Symbol:** `new URLSearchParams(window.location.search).get("initData")`.
- **Evidence:** ветка срабатывает ТОЛЬКО когда `WebApp.initData` пуст (вне TG),
  backend всё равно проверяет HMAC (`auth/initdata.py`).
- **Why it is a problem:** не даёт обойти прод-авторизацию, но initData оседает в
  истории браузера/логах при ручном смоуке.
- **Failure scenario:** оператор смоукает через URL → токен в истории; кто получил
  строку — может обратиться к API до протухания `auth_date`.
- **Fix:** оставить поддержку, но рекомендовать `sessionStorage.devInitData`
  (уже поддержан) вместо `?initData=`.
- **Regression test:** тест `getInitData()` при непустом `WebApp.initData` игнорит URL.

### F10 — Стабильность `/api/meta` fingerprint. `P4` · `OPEN (operability)`

- **File:** `backend/app/api/routes_meta.py`.
- **Symbol:** `fingerprint`.
- **Evidence:** отпечаток не меняется, если правки не добавляют/удаляют роуты
  (обе ревизии GHG11(4.1) и текущая имеют fp `3e372e27a6df`).
- **Why it is a problem:** проверка выкладки только по fp даёт ложное «не доехало».
- **Failure scenario:** правка логики без новых роутов → fp тот же → оператор
  думает, что деплой не прошёл.
- **Fix:** добавить в `/api/meta` `build` (уже есть — git-хэш/env) как основной
  маркер выкладки; в `DEPLOY_NOTES` проверять `code.build`, а не только fp.
- **Regression test:** не требуется (документационно-операционное).

---

## G. DATA INTEGRITY FINDINGS

| # | Тип | Где | Статус |
|---|---|---|---|
| G1 | duplicate rewards | XP идемпотентен (`xp_grants` UNIQUE) | **OK / KEEP** |
| G2 | duplicate events | номинации `game_vote` — нет DB-unique (F4) | OPEN |
| G3 | duplicate events | `update_id` не дедуплицируется (F5) | OPEN |
| G4 | race condition | муз-гейм `correct_voter_ids` JSONB RMW (F5) | OPEN |
| G5 | rollback | XP за удалённое голосовое не откатывался (F3) | **FIXED** |
| G6 | orphan records | `EventLog` voice_like/withdrawn/mode при каскаде (F6) | OPEN |
| G7 | inconsistent counters | автолох `bypass_cooldown` — два ролла при двух лидерах (F1) | **FIXED** (single-writer) |
| G8 | duplicate execution | scheduler стартовал дважды (F1) | **FIXED** |
| G9 | missing transaction | `voice.submit` — commit сдачи, затем XP (инвариант `awards`) | **OK / KEEP** (низкий риск: сбой XP после commit логируется) |
| G10 | invalid states | режимы `off/chat/app/both` — единый resolver, конфликты исключены | **OK / KEEP** |

Вывод: тяжёлых потерь данных нет. Все найденные проблемы — либо гонки (F4/F5),
либо остаточные записи (F6), либо уже исправленный rollback (F3).

---

## H. TELEGRAM / MINI APP PROTOCOL FINDINGS

- `POST /tg/webhook` проверяет `X-Telegram-Bot-Api-Secret-Token` (`app/bot/webhook.py`)
  — `KEEP`. Но нет дедупа `update_id` (F5).
- `allowed_updates` корректно включает `message_reaction` (без него реакции не
  приходили бы). `drop_pending_updates=False` — обновления не теряются при
  перепривязке webhook; но именно из-за F2 они могут «застрять» в
  `pending_update_count`.
- Исходящие TG-вызовы обёрнуты в `wait_for`/таймауты (`LOSER_SEND_TIMEOUT=25с`,
  `_IPv4AiohttpSession` 30с) — не виснут вечно. `429/retry_after` — есть
  `telegram_retry_after:*` в `humanizeApiError`.
- Mini App: `initData` верифицируется server-side; клиент шлёт
  `Authorization: tma <initData>` (`api/client.ts`). `KEEP`.
- Исходящее медиа (voice) тянется блобом с `Authorization` — не публичный URL.
  `KEEP`.
- Замечание: `HapticFeedback` требует TG ≥ 6.1 — в тестовом окружении логирует
  «not supported», в бою ок (мягкая деградация).

---

## I. SECURITY FINDINGS (red-team)

| Вектор | Проверка | Итог |
|---|---|---|
| Подделка `user_id` в теле запроса | `deps.current_user` берёт юзера из initData, не из body | **KEEP** |
| Replay initData | окно `max_age_seconds` в `parse_and_verify` | **KEEP** |
| Подмена HMAC | `compare_digest`, ключ `HMAC("WebAppData", BOT_TOKEN)` | **KEEP** |
| Фейковый webhook-запрос | secret-token обязателен | **KEEP** |
| IDOR в `/api/admin/*` | все мутирующие ручки зовут `_ensure_admin` | **KEEP** (кроме F8, читающий) |
| dev-`?initData=` | только при пустом TG initData + HMAC на бэке | **KEEP**, рекомендация (F9) |
| Отсутствие audit-log | reset XP / restore snapshot / clear pool | **F7 OPEN** |
| Утечка секретов | DSN/токен не логируются (`_mask`, `db.engine_created` без пароля) | **KEEP** |

Red-team не нашёл обхода границы доверия Telegram↔Mini App. Основная претензия —
отсутствие следа для destructive-админ-действий (F7), а не дыра доступа.

---

## J. SCHEDULER FINDINGS

- **duplicate executions:** был главный дефект (F1) — два процесса. `FIXED`
  single-writer-лизом.
- **missed events:** `misfire_grace_time=3600` покрывает рестарт/лаг; ретрай
  транзиентных БД-ошибок (`_SCHEDULER_DB_RETRY_ATTEMPTS`). `KEEP`.
- **restart behavior:** `reload_dynamic_jobs` пересобирает из AC; после F1 —
  только у лидера.
- **timezone/DST:** `SCHEDULER_TZ` (default `Europe/Moscow`), `DateTrigger fallback`;
  DST у Cron не дублирует запуск, но `DateTrigger` на следующий день может
  сместиться на час — `NOT PROVEN — нужен runtime-тест на границе DST`.
- **concurrency:** `max_instances=1` + watchdog `collapse_stale_jobs` (STALE 900с).
- **distributed execution:** решено лизом (TTL 300с, renew 60с, failover).

---

## K. UX / PRODUCT LOGIC FINDINGS

- Лента: единый `store.ui` (`feedAnchor`, `pendingAdminSection`); deep-link
  открывает нужный подраздел/блок (`FeedScreen` эффект, `AdminScreen` эффект). `KEEP`.
- Компактный/классический вид — один флаг `feed.view_compact` на всех. `KEEP`;
  в GHG11(5) миниатюры распространены на лох/чухан/активность фич.
- Невозможные состояния флагов исключены: `delivery` — единый resolver, master
  показывает `custom` при разъезде. `KEEP`.
- Модерация: «Скрыть у себя» всем + «Удалить» админу, откат через плашку; при
  hard-delete плашка честно пишет «удалено из базы». `KEEP`.
- Destructive-действия в админке подтверждаются через `showConfirm`, но без
  audit-log (F7).

---

## L. QUICK WINS

1. `PUBLIC_BASE_URL` только на каноническом хосте → снимает F2 (конфиг, без кода).
2. Уникальный partial-индекс для `game_vote` → закрывает F4 (одна миграция).
3. `EventLog(kind="admin_action")` на destructive admin-ручки → F7.
4. `set()`-дедуп в `register_guess` → F5 (одна строка).
5. GC/подчистка `EventLog` voice_* при каскаде → F6.
6. В `DEPLOY_NOTES` сверять `code.build`, а не только `fingerprint` → F10.
7. Перенести/задокументировать `/chukhan/leaderboard` → F8.

---

## M. PRE-RELEASE BLOCKERS

```text
DO NOT RELEASE UNTIL:
1. Подтверждён один владелец webhook (F2): после рестарта ОБОИХ хостов
   getWebhookInfo.url указывает на канонический хост (Amvera).
2. Развёрнут single-writer лиз (F1) и проверено, что планировщик стартует
   ровно на одном инстансе (лог scheduler.leader_acquired на одном хосте).
3. Откат XP при удалении голосового (F3) — уже в коде; прогон
   tests/test_game_ghg11_3.py зелёный.
```

F4–F10 — не блокеры релиза (фиксятся пост-фактум по плану N).

---

## N. PATCH PLAN

### Phase 1 — Critical / security / integrity
- **F1** single-writer лиз (DONE) + runtime-проверка failover на двух хостах.
- **F3** откат XP при админ-cascade (DONE).
- **F2** закрепить одного владельца webhook (env/конфиг) — до следующего деплоя.

### Phase 2 — Architecture / reliability
- **F4** уникальность голоса в номинациях (миграция + partial index).
- **F5** дедуп `update_id` + идемпотентный `register_guess`.
- Убрать двойной источник истины (опционально: явный `SCHEDULER_ROLE` в env).

### Phase 3 — UX / cleanup
- **F7** audit-log для destructive admin-действий.
- **F6** подчистка orphan `EventLog`.
- **F8**/F9 — нормализация неймспейса/смоука.

### Phase 4 — Nice-to-have
- **F10** операционный маркер выкладки (`code.build`).
- DST-тест `DateTrigger`; e2e-тест cross-channel (чат→мини-апп).

---

## FAILURE SIMULATION

| Кейс | Текущее поведение | Ожидаемое | Gap | Fix |
|---|---|---|---|---|
| Telegram 429/5xx | `humanizeApiError`, outbox retry | без дублей | нет дедупа `update_id` | F5 |
| Telegram timeout send | `wait_for(25с)`, outbox pending | повтор через 5мин | ок | KEEP |
| DB timeout/DNS-блип | `_is_transient_db_error` + retry | не ронять прогон | ок | KEEP |
| Рестарт посреди job | `coalesce=True`, misfire 3600 | догон/пропуск без дублей | ок | KEEP |
| duplicate update/callback | повторное выполнение | идемпотентно | нет `update_id`-дедупа | F5 |
| partial upload (voice) | blob с `Authorization` | не публичный | ок | KEEP |
| stale state (смена настроек) | `reload_dynamic_jobs` на PUT | джоб пересобран | только у лидера (by design) | KEEP |
| double-click (номинации) | два INSERT возможны | один голос | нет DB-unique | F4 |
| два хоста одновременно | дубли анонсов | один писатель | был P1 | F1 FIXED |

---

## BACKWARD COMPATIBILITY

- Схема БД в этой партии **не менялась** (0 миграций): лиз живёт в существующем
  `admin_config`, head остаётся `0026_music_track_likes`. Прод-Neon дрейфа не даёт
  (`test_db_alembic_head.py`).
- Kill-switch `SCHEDULER_LEADER_DISABLED=true` возвращает прежнее поведение
  «каждый сам себе планировщик» — для одиночного хоста без общей БД.
- Лента: поле `detail.participants` добавлено мягко; фронт читает его опционально.
- `/api/game/feed`: контракт `FeedOut` не менялся (только наполнение `detail`).

---

## ФИНАЛЬНЫЕ 4 ВОПРОСА

**1. Что хорошо?** Единая доставка (`delivery`/`journal`), server-side AUTH
(HMAC+whitelist), идемпотентность XP через `xp_grants`, десятки правильных
unique-индексов, outbox-паттерны, watchdog и транзиентные retry, 1003+24 тестов.

**2. Где ошибки?** Два инстанса на одну БД (F1 — исправлен, F2 — открыт),
откат XP при модерации (F3 — исправлен), гонки номинаций/апдейтов (F4/F5),
orphan `event_log` (F6), нет audit-log (F7).

**3. Что фиксить сейчас?** Phase 1 отчёта: подтвердить владельца webhook (F2) и
развернуть single-writer лиз (F1) — оба про «один активный писатель».

**4. Что проверить перед релизом?** Логи обоих хостов: `scheduler.leader_acquired`
ровно на одном; `getWebhookInfo.url` на каноническом; `pending_update_count=0`.

### Может ли эта система надёжно существовать как production-платформа?

```text
YES WITH CONDITIONS
```

Условия: (1) single-writer лиз развёрнут и подтверждён; (2) webhook закреплён за
одним хостом; (3) устранены гонки F4/F5 перед ростом нагрузки. При этих условиях
система зрелая и надёжная: сильные инварианты уже есть, риски — точечные.




