# 🔍 ПЛАН АУДИТА: «GHG» — Telegram-бот + Mini App + игровая/социальная платформа

Применён мастер-скилл **PRINCIPAL AUDITOR**. Это **план**, а не отчёт: ниже — карта
проекта по факту кода, области аудита с точками входа, фазы работ, формат финальных
находок и критерии готовности. Все утверждения помечены `CONFIRMED` (из кода),
`INFERRED` (следует из архитектуры) и `HYPOTHESIS` (проверить в ходе аудита).

---

## 1. Карта проекта (факт)

### 1.1 Tech stack — `CONFIRMED`

| Слой | Технология | Версия | Доказательство |
|---|---|---|---|
| Backend | FastAPI | 0.115.6 | `backend/pyproject.toml` |
| Bot | aiogram (webhook) | 3.13.1 | `app/bot/webhook.py`, `app/main.py` |
| ORM | SQLAlchemy async | 2.0.36 | `app/db/models.py`, `app/db/base.py` |
| DB driver | asyncpg | 0.30.0 | `pyproject.toml` |
| Миграции | Alembic | 1.13.3 | `backend/alembic/versions/` — **27 ревизий**, head `0026_music_track_likes` |
| Схемы | Pydantic | 2.9.2 | `app/schemas/*` |
| Планировщик | APScheduler (AsyncIOScheduler) | 3.10.4 | `app/bot/scheduler.py` |
| Frontend | React + TS + Vite | — | `frontend/` |
| DB (prod) | Neon Postgres | — | `DATABASE_URL` в секретах |
| Хостинг | Amvera **и** HuggingFace Space | — | один и тот же код зеркала, `tools/`/`DEPLOY_NOTES.md` |
| Фронт-хостинг | Cloudflare Pages | — | автопересборка из монорепо |

### 1.2 Фактические пути исполнения — `CONFIRMED`

```
Telegram
  └─ POST /tg/webhook   (secret-token check)          app/bot/webhook.py
       └─ dp.feed_update → handlers/*                 app/bot/handlers/
Mini App (Cloudflare Pages)
  └─ /api/*  (Authorization: tma <initData>)          frontend/src/api/
       └─ CurrentUser = deps.current_user             app/api/deps.py
            └─ HMAC-verify initData + whitelist       app/auth/initdata.py
Чтение/запись
  └─ services/*  (бизнес-логика)                      app/services/
       └─ services/game/* (игровая экономика)         app/services/game/
Scheduler (в процессе FastAPI, lifespan)
  └─ AsyncIOScheduler  → jobs                        app/bot/scheduler.py
       ├─ chat: journal.send_now
       └─ app:  delivery.record_feed_event → game_journal(kind="feature")
Feed
  └─ GET /api/game/feed → feed.build_feed()           app/services/game/feed.py
```

### 1.3 Инварианты, уже подтверждённые в коде — `CONFIRMED` (кандидаты в «WHAT IS GOOD»)

- **Webhook защищён** secret-token’ом: `app/bot/webhook.py` сверяет `X-Telegram-Bot-Api-Secret-Token`.
- **initData верифицируется server-side** по официальному алгоритму (HMAC `WebAppData` +
  `compare_digest` + окно `max_age_seconds`): `app/auth/initdata.py::parse_and_verify`.
- **Идентичность канонична по `telegram_id`** (unique), не по username: `models.User.telegram_id`.
- **Уникальные ключи там, где нужна защита от дублей**:
  `uq_poll_vote(poll_option_id,user_id)`, `uq_game_voice_submission(task_id,user_id)`,
  `uq_music_track_like(user_id,track_id)`, `uq_user_achievement(user_id,code)`,
  `uq_feedback_meeting_user`, `uq_weekly_chukhan_week`, `uq_game_holiday_md`,
  `ix_xp_grant_key(user_id,idem_key) UNIQUE`.
- **XP идемпотентен** через `idem_key`: `models.XpGrant`, `Index(ix_xp_grant_key, unique=True)`.
- **Scheduler-джобы** объявлены с `max_instances=1`, `coalesce=True`, `misfire_grace_time=3600`
  (`scheduler.py`): защита от наложения и от «пропустил, пока лежал».
- **Транзиентные DB-ошибки** распознаются и ретраятся (`_is_transient_db_error`), логические — нет.
- Есть **watchdog + мастер-кнопка** схлопывания зависших задач (`scheduler.collapse_all_jobs`).
- **774 теста** (988 passed) и настройка pytest; typecheck/build фронта зелёные.
- Разделены `DATA` и `CONFIG`; фичи-флаги централизованы в `services/game/delivery.py`
  (единый `get_feature_mode`, а не разрозненные `if`).

### 1.4 Что уже выглядит как архитектурный риск — `HYPOTHESIS` (проверяется в фазах 1–2)

| # | Гипотеза | Почему подозрительно |
|---|---|---|
| H1 | **Двойной запуск планировщика** на двух хостах (Amvera и HF Space — один код) | APScheduler стартует в lifespan каждого процесса. Если оба инстанса живы и оба получают тик — дубли ежедневных анонсов (лох/чухан/фразы). Нужно понять, кто реально «прод», и кто держит webhook |
| H2 | **Cross-channel голосование** (чат vs мини-апп) | Уникальный ключ есть у `PollVote`/`MusicTrackLike`, но у **номинаций** (`game_nominations`) и у голосования муз-гейма нужно проверить DB-уровень, а не только UI |
| H3 | **Откат XP при удалении контента** | `voice.py` ведёт «могилку» `voice_withdrawn`, но откатывает ли XP каскадное удаление (`feed_moderation`)? Награда за удалённую сдачу не должна оставаться |
| H4 | **Порядок «чат-сообщение vs commit»** | Часть путей шлёт в чат до/после записи в БД (`journal.send_now`). Нужен аудит «UI says success / DB failed» и «chat says success / DB failed» |
| H5 | **Кэш настроек планировщика** | `reload_dynamic_jobs` вызывается при смене конфига; проверить, что воркеры не работают на старом снапшоте (`admin sees changed / worker uses old`) |
| H6 | **Race в schedule-задачах без распределённой блокировки** | `max_instances=1` защищает внутри процесса, но не между инстансами (см. H1) |
| H7 | **Feed orphan при удалении источника** | `feed_moderation` каскадно чистит `journal:`/`voice:`/…, но календарные маркеры и `event_log`-источники (`voice_like`, `advice`) могут оставить хвосты |
| H8 | **Admin-dangerous действия без аудита** | `reset XP / snapshot / restore / clear pool` — проверить наличие audit-log и подтверждений на backend, а не только кнопки в UI |

---

## 2. Области аудита и конкретные точки входа

Порядок — как требует скилл: **DATA → AUTH → STATE → EVENTS → CONCURRENCY → SCHEDULER → TELEGRAM**, и только потом UX.

### 2.1 AUTH / TRUST BOUNDARY
- `app/api/deps.py::current_user`, `app/auth/initdata.py::parse_and_verify` — replay-защита
  (`max_age`), отсутствие доверия к телу запроса для `user_id`.
- Все `/api/admin/*` — каждый dangerous endpoint должен звать `_ensure_admin`/`_game_gate`
  (проверить перечнем, нет ли пропусков).
- `frontend/src/tg/webapp.ts::getInitData()` — **dev-оверрайд `?initData=`**. Убедиться, что он
  не даёт обойти прод-авторизацию (только при пустом `WebApp.initData`).

### 2.2 ECONOMY (XP / achievements / awards)
- `services/game/xp.py`, `awards.py`, `achievements.py` (1322 стр.), `levels.py`.
- Инварианты: награда не дважды; откат при удалении/модерации; overflow; отрицательный XP;
  prestige; manual admin set/add.
- `achievements_catalog.py` + счётчики первых/юбилейных событий (first vs ×10).

### 2.3 SCHEDULER
- `app/bot/scheduler.py` — реестр job’ов, `_RUNNING_SINCE`, `collapse_all_jobs`,
  `reload_dynamic_jobs`, транзиентные ретраи.
- Сценарии: рестарт `17:59→18:00`, простой `17:50→DOWN→18:10`, DST/таймзоны
  (`scheduler_tz`, `VOICE_TZ_OFFSET_HOURS`), `random once-per-day` vs `per-tick chance`.

### 2.4 EVENTS / FEED
- `services/game/delivery.py` (единый resolver режимов), `journal.py`, `feed.py`,
  `feed_moderation.py`, `record_feed_event`.
- Event-model table (Event / Producer / Source of truth / Consumers / Idempotent? / Persistent?).

### 2.5 CROSS-CHANNEL (главный тест скилла)
- Сценарий «проголосовал в чате → открыл мини-апп»: `routes_game.py` / `routes_polls.py` /
  `nominations.py` / `music_game.py`.
- Порядок DB↔Telegram на обеих сторонах.

### 2.6 MEDIA (voice / music)
- `services/game/voice.py`, `music.py`, `music_game.py`; `handlers/voice_tasks.py`,
  `handlers/music.py`.
- Lifecycle: submit → XP → delete → rollback (H3); лимиты размера/MIME; доступ к аудио
  (`fetchVoiceAudioUrl` — blob c `Authorization`).

### 2.7 CALENDAR / MEETINGS
- `services/auto_pick.py`, `reminders.py`, `routes_meetings.py`, `routes_calendar.py`,
  `services/ical.py`; timeline/tz/пересечения/границы месяца-года.

### 2.8 ADMIN
- `routes_admin.py` (4777 стр.) — все dangerous-ручки, `admin_config.py` (schema-validation),
  `phrase_snapshot.py` (snapshot/restore), `space_restart.py`, `proxies.py`.

### 2.9 OBSERVABILITY / OPS
- structlog, request/job-id, health (`/api/meta`), graceful shutdown (`shutdown_scheduler`).

---

## 3. Фазы работ

> Каждый шаг фазы = «набор фактов → находка → доказательство». Без доказательства — `NOT PROVEN`.

### Phase 0 — Recon & Baseline (0.5 дня)
1. Собрать полную карту роутов и job’ов; сверить `/api/meta` (routes/api_routes/fingerprint) обоих хостов.
2. Прогнать `pytest`, `typecheck`, `vitest`, `build` — зафиксировать baseline (уже: 988/7/OK).
3. Зафиксировать «кто прод»: какой хост держит webhook (`getWebhookInfo`), живёт ли второй инстанс.

### Phase 1 — Critical (DATA / AUTH / INTEGRITY) — приоритет наивысший
4. Проверка H1 (двойной планировщик) → решить: single-writer lock или отключить scheduler на втором хосте.
5. Проверка H3 (откат XP при удалении) на всех путях удаления.
6. Проверка H4 (порядок chat vs DB) для всех «says success» путей.
7. Полный перечень admin-ручек против `_ensure_admin` (поиск пропущенной защиты).
8. Проверка dev-оверрайда initData на прод-безопасность.

### Phase 2 — Concurrency / Scheduler / Events
9. Таблица событий с колонкой «idempotent?» (по `idem_key`/unique constraints).
10. Проверка H2 (номинации/муз-гейм) на DB-уровне.
11. Failure-simulation: 429/5xx Telegram, DB timeout, рестарт посреди job, double-click, duplicate update.
12. Проверка H5 (кэш настроек) и H6 (распределённая блокировка).

### Phase 3 — Product/UX + Backward-compat
13. Проверка невозможных/противоречивых состояний флагов (`OFF + achievements MINIAPP` и т.п.).
14. BC: старые config-ключи, старые counters, миграция legacy-режимов.

### Phase 4 — Cleanup / Nice-to-have
15. Findings P3/P4, quick wins.

---

## 4. Формат финального отчёта (по скиллу)

Разделы A–N: Executive Summary (+ оценки X/10), Actual Tech Stack, Architecture,
Feature Matrix, What Is Good, **Critical Findings** (P0–P4 с ID/Severity/Component/File/Symbol/
Evidence/Failure/Fix/Regression test), Data Integrity, Telegram protocol, Security (red-team),
Scheduler, UX, Quick Wins, Pre-release blockers, Patch Plan (Phase 1–4).

Для **каждой** находки обязательна цепочка:

```
FINDING → FILE → SYMBOL → BUG → IMPACT (реальный сценарий) → FIX (minimal + robust) → TEST
```

Отдельно — **failure simulation** (Telegram timeout/429/5xx, DB timeout, restart, duplicate
update/callback, partial upload, stale state), где для каждого кейса:
`Current behavior → Expected → Gap → Fix`.

Финал: ответ на 4 вопроса (что хорошо / где ошибки / что фиксить сейчас / что проверить перед
релизом) и вердикт `YES / YES WITH CONDITIONS / NO` для «может ли это быть надёжной production-платформой».

---

## 5. Критерии готовности плана

- [ ] Каждая находка подтверждена `file:line` и именем функции (`CONFIRMED`), либо помечена `NOT PROVEN — needs runtime verification`.
- [ ] Нет бездоказательных «переписать на X» — для нормальных мест явно `KEEP` + почему.
- [ ] Есть regression-test-предложение на каждую P0–P2 находку.
- [ ] Pre-release blockers выписаны отдельным списком «DO NOT RELEASE UNTIL…».

## 6. Приложения к плану (артефакты)

- `AUDIT_PLAN.md` (этот файл).
- Будущий `AUDIT_REPORT.md` — результат фаз 1–3.
- При необходимости — `AUDIT_EVENTS.md` (таблица событий) и `AUDIT_SCHEDULER.md` (карта job’ов).
