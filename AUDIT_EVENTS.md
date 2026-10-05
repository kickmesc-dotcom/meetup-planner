# 📡 AUDIT_EVENTS — карта событий системы «GHG»

Приложение к `AUDIT_REPORT.md` (раздел 25 мастер-скилла: EVENT MODEL).
Все строки получены из кода (`backend/app/**`); имена таблиц/констрейнтов —
`backend/app/db/models.py`. Формат: **Producer → Source of truth → Consumers**,
плюс столбцы «идемпотентно?» и «переживает рестарт?».

Обозначения: `EV` = `event_log` (JSONB, без схемы), `GJ` = `game_journal`,
`XP` = `xp_grants`/`xp_daily`, `AC` = `admin_config`.

---

## 1. Входящие события (Telegram → бэкенд)

| Событие | Producer | Source of truth | Consumers | Идемпотентно? | Persistent |
|---|---|---|---|---|---|
| `message` из группы | Telegram → `POST /tg/webhook` | Telegram | handlers, кэш `chat_messages` | **нет** (нет дедупа по `update_id`) | частично (`chat_messages`, `uq_chat_msg`) |
| `callback_query` | Telegram → webhook | Telegram | handlers (inline-кнопки) | **нет** | нет |
| `poll_answer` | Telegram → webhook | Telegram | `poll_votes` (`uq_poll_vote`), `music_game` | да: TG шлёт один апдейт; `music_game.register_guess` дедуп по `correct_voter_ids` | да (`poll_votes`, `music_game_rounds`) |
| `message_reaction` | Telegram → webhook | Telegram | `media_reactions` | **нет** | частично (`game_media_posts`) |
| Mini App API-запрос (`Authorization: tma …`) | фронт → `/api/*` | `initData` (HMAC) + `users.telegram_id` | `deps.current_user` | n/a | нет |

> **Дыра:** дедупликации по `update_id` нет. Telegram при ретраях доставки может
> прислать апдейт дважды — обработчики идемпотентны лишь там, где есть unique-key.
> См. `AUDIT_REPORT.md`, находка **F5**.

## 2. Игровые / социальные события (единая «дверь» доставки)

Доставка централизована: `services/game/delivery.py::route_feature`/`announce`
решает `off / chat / app / both`; `journal.send_now` — единственная чат-дверь.

| Событие | Producer | Source of truth | Consumers | Идемпотентно? | Persistent |
|---|---|---|---|---|---|
| Ачивка выдана | `achievements.grant` | `user_achievements` (`uq_user_achievement`) | лента (`ach:`), анонс `GJ(kind=achievement)`, буфер пула | да (unique `user_id,code`) | да |
| Лох дня (авто) | `scheduler._autoloser_job` → `loser.roll_loser` | `loser_rolls` + `loser_outbox` | чат (outbox), лента (`loser:`), календарь, статистика | **нет** (auto `bypass_cooldown=True`) | да |
| Лох (ручная дуэль) | `ActionBar`/`LoserSheet` → API | `loser_rolls` (`source=duel`) | лента исключает `duel` | кулдаун (не unique) | да |
| Чухан недели | `scheduler` cron → `chukhan.run_chukhan_job` | `weekly_chukhan` (`uq_weekly_chukhan_week`) | чат, лента (`chukhan:`), история | да (одна строка на `week_start`) | да |
| XP начислен | `services/game/xp.award` | `xp_grants` (`ix_xp_grant_key` UNIQUE) + `xp_daily` | профиль, лента уровня, ачивки | да (`(user_id, idem_key)`) | да |
| XP отозван | `xp.revoke` (withdraw голосового; **теперь** и админ-cascade) | `game_profiles.xp`, `xp_daily` | профиль | нет ключа (редкое ручное) | да |
| Голосовое задание | `scheduler`/API → `voice` | `game_voice_tasks` | чат, лента (`voice:`) | создание — не unique | да |
| Сдача варианта | `voice.submit` | `game_voice_submissions` (`uq_game_voice_submission`) | ×XP, чат, лента | да (`task_id,user_id`) | да |
| Отзыв варианта | Mini App → `routes_game.voice_withdraw_api` | `event_log(voice_withdrawn)` + удаление строки | повторная сдача запрещена | по `(task_id,user_id)` | да |
| Лайк варианта | Mini App → `voice.like` | `event_log(voice_like)` | счётчики ленты | toggle по `(submission_id,user_id)` | да |
| Муз. подборка | `music` (админ/publish) | `music_selections` + `music_tracks` | чат, лента (`music:`) | не unique (по публикации) | да |
| Лайк трека | Mini App/чат → `music.like` | `music_track_likes` (`uq_music_track_like`) | топ треков, лента | да | да |
| Раунд муз-гейма | `scheduler.game_music_game_weekly` | `music_game_rounds` | чат-полл, лента (`music_game:`) | `closed_at` ставится один раз | да |
| Догадка в муз-гейме | Telegram `poll_answer` | `music_game_rounds.correct_voter_ids` (JSONB) | ×XP автору/угадавшим, лента | дедуп в списке (read-modify-write) | да |
| Голос в номинациях | Mini App → `nominations.toggle_vote` | `event_log(game_vote)` | итоги «во что сыграем» | **нет DB-unique** (delete+insert в одной TX) | да |
| Передача червя | `worm_transfer` | `worm_assignments` + `event_log(worm_transfer_pending)` + AC | чат (инфо), админка | pending-запись дедуп по активной | да |
| Наказание червя | `/punish` → `achievements` | `event_log(worm_punish)` + `achievement_counters` | ачивки | counter-based | да |

## 3. Лента (`game_journal`) — анонсы и «только апп»

| `GJ.kind` | Кто пишет | Когда | Лента? | В чат? |
|---|---|---|---|---|
| `achievement` | `journal.announce` | выдача ачивки | да (`sent_at` может быть now) | по режиму фичи |
| `achievement_pool` | `journal.queue_achievements` | буфер, выплеск расписанием | да | сводкой |
| `holiday` / `event` / `contraband` / `memorial` | `journal.announce` | игровые ивенты | да | по режиму |
| `feature` | `delivery.record_feed_event` | совет/червь/реакции/номинации без своей таблицы | да (`sent_at=now`) | нет (feed-only) |
| `other` | `journal.announce` (fallback) | прочее | нет | по legacy-режиму |

## 4. Календарные / сервисные события

| Событие | Producer | Source of truth | Consumers | Идемпотентно? | Persistent |
|---|---|---|---|---|---|
| Слот доступности | Mini App → `availability` | `availability_ranges` | автоподбор, календарь | по диапазону | да |
| Встреча | API → `meetings` | `meetings` | напоминания, feedback, календарь | не unique | да |
| Напоминание о встрече | `reminders.run_due_reminders` | `meeting_reminders` (`uq_meeting_reminder`) | чат | да (по `meeting_id,offset`) | да |
| Голос в опросе | Mini App/чат → `polls` | `poll_votes` (`uq_poll_vote`) | итоги, календарь | да | да |
| Отзыв о встрече | Mini App → `meeting_feedback` | `meeting_feedback` (`uq_feedback_meeting_user`) | админ-история | да | да |
| ДР-уведомление | `scheduler.birthdays_daily` | `birthday_notifications` (`uq_birthday_notif`) | чат | да (по `user,year,kind`) | да |
| Праздник | `scheduler.game_holidays_daily` | `game_holidays` (`uq_game_holiday_md`) | чат, лента | да | да |
| Модерация ленты (удалить) | Admin → `feed_moderation.delete_item` | `event_log(feed_delete)` | `build_feed` фильтрует | да (повтор — no-op) | да |
| Модерация ленты (скрыть) | участник → `feed_moderation.hide_item` | `event_log(feed_hide)` | `build_feed` для смотрящего | да | да |
| Пауза бота / автопас | `/zaebal`, admin → `bot_pause` | `admin_config` + `bot_pause` | чат | флаг в AC | да |
| Здоровье прокси | `scheduler.proxy_health` (ALWAYS_ON) | `proxy_entries` | алёрты админам | нет | да |
| Рестарт Space | `scheduler.space_restart_tick` | `admin_config` (schedule/last) | HF API | анти-луп 30 мин | да |

## 5. Планировщик — реестр джобов (26 `add_job`, id стабильны)

Инфра-джобы: `bot_pause_auto_restore`, `loser_outbox_retry`, `chukhan_retry`,
`dead_chat_hourly`, `scheduler_watchdog`, `space_restart_tick`, `proxy_health`.
Динамические (из AC, пересобираются `reload_dynamic_jobs`): `meeting_reminders_tick`,
`random_phrases` (+ `:extra:`), `autoloser`, `avatar_sync_daily`, `chukhan_weekly`,
`auto_zaebal`, `birthdays_daily`, `meeting_feedback_daily`, `game_holidays_daily`,
`game_week_activity_weekly`, `game_memes_sweep`, `game_memorial_daily`,
`game_events_hourly`, `game_digest_flush`, `game_achievements_flush`,
`game_voice_tick`, `game_music_weekly`, `game_music_game_weekly`.

> **Single-writer (GHG11(5)):** все джобы поднимает ровно один инстанс — владелец
> лиза `admin_config[scheduler.leader]` (`services/scheduler_leader.py`).

## 6. Дыры идемпотентности (сводно)

1. **Telegram `update_id` не дедуплицируется** → повторный апдейт может продублировать
   действие, где нет unique-key (P2/P3, см. F5 в отчёте).
2. **`game_vote` (номинации)** — нет DB-уникальности `(nomination_id, user_id)`,
   delete+insert в одной TX уязвим к гонке (F4).
3. **`correct_voter_ids` (муз-гейм)** — read-modify-write JSONB; дубль `poll_answer`
   может вставить игрока дважды (F5).
4. **Автолох** идёт `bypass_cooldown=True`; идемпотентность обеспечивается только
   single-writer'ом, а не уникальностью в БД (после GHG11(5) — ок; при двух
   лидерах давал бы два ролла в одном окне).
