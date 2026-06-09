# Meetup Planner — чеклист GHG8

Преемник `CHECKLIST_GHG7.md` (архив релиза P0–P10, задеплоен 2026-06-01).
Здесь — только то, что **предстоит сделать**. Детали закрытых задач GHG8 —
в git history (`git log --grep "GHG8"`) и в секции «Закрыто» внизу.

Single source of truth: `C:\Users\fa1nt\meetup-planner-main` (монорепо
`backend/` + `frontend/`). После правок `backend/` —
`cp backend/* → C:\Users\fa1nt\meetup-planner-backend\` (отдельный git remote →
HF Space). Push в HF/GitHub делает ассистент (git PAT) ИЛИ пользователь —
фиксируется в каждом sync-подэтапе.
⚠️ Push в GitHub через credential.helper=manager ВИСНЕТ (молча, >5 мин) —
пушить с PAT в URL:
`git push https://x-access-token:<PAT>@github.com/kickmesc-dotcom/meetup-planner.git main`.

## Легенда статусов
- `[ ]` — не начато · `[~]` — в работе (обрыв/ожидание) · `[x]` — закрыто

## Правила работы с чеклистом
1. Этапы разбиты на подэтапы `PX.Y` / `PX.Y.a`.
2. После закрытия подэтапа — `[x]` + однострочная пометка
   `(YYYY-MM-DD) <что сделано> — <ключевой файл/коммит>`.
3. Sync `backend/` → `meetup-planner-backend/` — отдельный подэтап с галкой.
4. Обрыв → `[~]` с пометкой, на каком файле/шаге остановились.
5. Investigate-пункты (`INV-N`) не «фиксят», а отвечают на вопрос и порождают
   follow-up подэтапы; закрываются выводом + ссылкой на них.

Состояние прода (2026-06-09): сьют **344 passed**, HF/GitHub — см. отметку
P4.1.f. ⚠️ P14 добавил env `HF_TOKEN` (write-токен HF,
добавить руками в секреты Space — см. DEPLOY_NOTES); без него кнопка рестарта
дизейблится, остальное работает. Прочее — в `admin_config`.

---

## ОТКРЫТО

### Q-NET. Сетевая отказоустойчивость (Q8/Q9/Q10) — архитектура
Контекст: РКН душит прокси, всё идёт через direct; джобы зависают, помогает
свап proxy↔direct или смена VPN на телефоне; рестарт Space «расклинивает».
НЕ трогать первый (зелёный) прокси (Q8). Кнопка «найти живые прокси» никогда
не работала — низкий приоритет (Q8).

> **Статус (2026-06-06):** план готов (ниже), пользователь решил **отложить
> Q-NET** — сначала плановые блоки. Не начинать кодить до согласования.

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
  с тем же путём (направление НЕ меняем — Q8), + лог + admin-алёрт
  (rate-limit как у proxy down). Half-open: после успеха счётчик в 0.
  Состояние — module-level (как `_state` в proxies). Без новых зависимостей.
- **(b) Таймауты/пул** — в `_make_direct_connector`/`_build_session`:
  `keepalive_timeout=15` (дохлые соединения не живут в пуле дольше 15с),
  гранулярный `aiohttp.ClientTimeout(total=25, sock_connect=8)` вместо
  плоских 30с. Опц. env `BOT_FORCE_CLOSE=true` — `force_close` коннектора
  (медленнее, но неубиваемо; выключено по дефолту).
- **(c) curl_cffi** — РЕКОМЕНДАЦИЯ: отклонить. aiogram завязан на
  aiohttp-сессию; подмена транспорта = форк-обёртка над всем Bot API клиентом,
  поломает smart-proxy и (a)/(b). TLS-fingerprint для api.telegram.org —
  гипотеза, факты логов на неё не указывают.
- **(d) Webhook ↔ Long Polling** — admin_config `bot.transport` ∈
  {webhook, polling} + переключатель в админке + применение на лету:
  supervisor-задача в lifespan (main.py) — при polling `delete_webhook` +
  `dp.start_polling` фоновой задачей; при webhook — остановка polling +
  `set_webhook` (готовая retry-логика старта есть). FastAPI/Mini App живут
  на 7860 в обоих режимах. Минус: +1 постоянный long-poll коннект.
  Объём — самый большой из четырёх (~средний P-блок).

Рекомендуемый порядок: **b → a → d** (по росту объёма; c — отклонить).

- [ ] **Q-NET.a (10а).** Circuit Breaker / авто-fallback (план (a) выше).
- [ ] **Q-NET.b (10в).** Таймауты и пул соединений (план (b) выше).
- [ ] **Q-NET.c (10б).** TLS fingerprint / curl_cffi — INV-оценка, реализация
  под вопросом (рекомендация — отклонить, см. (c)).
- [ ] **Q-NET.d (10г).** Переключатель Webhook ↔ Long Polling (план (d) выше).
- [ ] **Q-NET.e.** Тесты + sync + DEPLOY_NOTES (новые env/настройки).

### P4. Экран приветствия с быстрой инфой
Источник: GHG7.txt стр. 25–31.
- [x] **P4.1.a.** (2026-06-09) Welcome-баннер над календарём: Чухан недели,
  Главный лох (+счётчик `main_loser_count` в `/titles/current`), Лох дня
  («не выбран» если нет), Червь-пидор (только если есть) —
  `frontend/src/features/welcome/WelcomeBanner.tsx`.
- [x] **P4.1.b.** (2026-06-09) Единый формат `name|avatar|both` (default
  `avatar`), один селектор на все блоки; per-user в admin_config
  (`ui.welcome_format:<tg_id>`, `get/set_ui_welcome_format`), фикс. высота
  ячеек h-10 — дизайн не расползается. PUT `/me/ui-prefs` стал PATCH-подобным
  (`UiPrefsPatch`, оба поля опциональны — совместимо со старым фронтом).
- [x] **P4.1.c.** (2026-06-09) Закрытие баннера — `showConfirm` «не показывать,
  вернуть в настройках профиля (👤)»; пометка — та же per-user `hide_greeting`
  (E7); тогглер «Показывать баннер» — в Профиле.
- [x] **P4.1.d.** (2026-06-09) Вкладка «Топы» → «Профиль» (`ProfileScreen.tsx`:
  шапка, Топы = прежний LeaderboardScreen внутри, История, настройки
  приветствия). Команда `/top` в чате — текстовое зеркало топов
  (`chat_commands.py:on_top`, добавлена в `commands_catalog`).
- [x] **P4.1.e.** (2026-06-09) История в Профиле: лохи (`/api/loser/history`,
  существующий) + чуханы — новый публичный `GET /api/chukhan/history`
  (только posted_at IS NOT NULL, паттерн P11).
- [x] **P4.1.f.** (2026-06-09) Тесты `test_welcome_prefs.py` (12 шт., сьют
  **344 passed**), sync `backend/` → `meetup-planner-backend/`, push HF +
  GitHub/Pages.

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

### P14. Рестарт HF Space из админки + по расписанию (фидбек 07.06.2026)

> **Источник (дословно):** «большинство проблем и зависших состояний в последнее
> время надёжно фиксится только одним способом — принудительный рестарт HF
> Space. Можно ли реализовать такой рестарт по кнопке из админки, а в идеале —
> назначать рестарт как запланированное событие (единоразово или регулярно
> каждые N часов/дней)».

Предварительная оценка реализуемости (2026-06-07, проверить в INV):
- **Вариант A — HF Hub API:** `POST https://huggingface.co/api/spaces/
  fryesw/meetup-planner-backend/restart` с заголовком `Authorization: Bearer
  <HF_TOKEN>` (write-токен). Чистый рестарт «как кнопка Restart в UI». Требует
  новый env-секрет `HF_TOKEN` в Space. Запрос наружу идёт НЕ к telegram —
  РКН-throttling канала TG его не задевает.
- **Вариант B — суицид процесса:** `os._exit(1)` после отдачи HTTP-ответа —
  HF перезапускает упавший контейнер. Без токена и внешних запросов, но
  рестарт «грязный» (без graceful shutdown) и полагается на политику
  авторестарта HF. Годится как фолбэк, если A не сработает.
- Связь с Q-NET: рестарт лечит симптом (дохлый keep-alive-пул), Q-NET-план
  лечит причину. Не конкурируют — P14 дешёвый и нужен уже сейчас.

- [x] **P14-INV.** (2026-06-07) **Выбран вариант A — подтверждён живым тестом**
  (2 рестарта прода с согласия пользователя): `POST huggingface.co/api/spaces/
  fryesw/meetup-planner-backend/restart`, Bearer hf-токен → HTTP 200, stage
  `RUNNING_BUILDING`, контейнер пересоздан. Замеры: (1) **даунтайм HTTP/Mini App
  ≈ 0** — поллинг `/healthz` каждые 2с в течение 240с не поймал ни одного
  обрыва, HF переключает трафик бесшовно; (2) **вебхук переустановился сам**
  retry-логикой `_register_telegram_metadata_with_retry`: попытки 1–5 —
  Request timeout (РКН душит свежий канал к TG), попытка 6 — `webhook.set` OK;
  **полная боеготовность бота через ~6.5 мин** после рестарта; (3) scheduler-
  джобы после подъёма живые. ⇒ Для P14.1 нужен env `HF_TOKEN` (write) в Space.
  Для P14.3 анти-луп: кламп «не чаще раза в 30 мин» обоснован — первые ~7 мин
  после рестарта исходящие к TG деградированы.
- [x] **P14.1.a.** (2026-06-08) `POST /admin/space/restart` (202 до рестарта,
  лог `space_restart.requested`) + `GET/PUT /admin/space/restart-settings`;
  ядро — новый `app/services/space_restart.py` (вариант A, HF Hub API).
  Без `HF_TOKEN` эндпоинт отвечает 503, кнопка дизейблится.
- [x] **P14.1.b.** (2026-06-08) `SpaceRestartScreen.tsx` — кнопка с showConfirm
  + алёрт «бот молчит ~5–7 мин»; Card в секции «Прокси» (AdminScreen).
- [x] **P14.2.a.** (2026-06-08) `space_restart.schedule` (off|once|interval) +
  job `space_restart_tick` (IntervalTrigger 5 мин, паттерн
  bot_pause_auto_restore); once → off коммитится ДО вызова HF API; якорь
  `space_restart.last_restart_at` (пишется и при ручном).
- [x] **P14.2.b.** (2026-06-08) UI расписания в том же `SpaceRestartScreen`
  (сегмент off/once/interval, datetime-local, слайдер 1–168ч,
  «следующий рестарт: …» из `next_restart_at`).
- [x] **P14.3.** (2026-06-08) Анти-луп 30 мин (`MIN_RESTART_INTERVAL` в
  `should_fire`, действует и после ручного), кламп every_hours 1..720 в
  parse_schedule/сеттере, лог `space_restart.scheduled_fired`.
- [x] **P14.4.** (2026-06-08) `tests/test_space_restart.py` (20 тестов:
  parse/клампы/next/should_fire/анти-луп), сьют **332 passed**; sync в
  `meetup-planner-backend/`; DEPLOY_NOTES — секция про env `HF_TOKEN`
  (write-токен, добавить руками в секреты Space).

### P2.1.c. Клик по иконке-шапке → попап-история номинации (низкий приоритет)
- [ ] **P2.1.c.** Требует истории по ролям (для чухана — leaderboard, для
  червя/ДР API истории пока нет).

## Отложено явно (НЕ в этой итерации)
- **Бот сам постит мемы.** GHG7.txt стр. 203–204 — «Пока не реализуем».
- **Реальный цитатор** (P6.4 из GHG7) — требует индекса сообщений в Neon.

---

## ЗАКРЫТО (однострочники; детали — в git log и архивных версиях этого файла)

GHG7-релиз (P0–P10, до этого чеклиста): см. `CHECKLIST_GHG7.md` (архив).

- [x] **Q-INV-1/Q5.** (2026-06-05) Причины чухана «6 старых»: невалидный JSON в
  `admin_config` молча фолбэчил на дефолты. Фикс: кнопка «↩ Сбросить к дефолтам»
  + `GET /admin/chukhan-reasons/raw` диагностика + лог fallback_default.
  HF `8fc7230`, Pages `78f4af4`.
- [x] **Q-FIX.** (2026-06-05) `chukhan.py:147` — пропущенная запятая в
  `CHUKHAN_TAGLINES` (implicit string concatenation), запятая добавлена в main,
  web-UI-коммит `e594e79` смёрджен.
- [x] **Q4.** (2026-06-05) Чёрный фон 💩/🪱-бейджей → drop-shadow без плашки
  (`ParticipantRow.tsx`), Pages `78f4af4`.
- [x] **Q-INV-2/Q7.** (2026-06-06) Медиа-реакции: send без таймаута висел 30с
  (фикс — `asyncio.wait_for` 25с) + `_recent` терялся при рестарте (фикс —
  persist в `admin_config[media_reactions.recent_media]` + фолбэк в force +
  человчный 404). HF `a4c74fa`. Сьют 247.
- [x] **Q-INV-3/Q2/Q1 = P11.** (2026-06-04/05) Отказоустойчивость чухан-поста:
  таймаут send 25с, удаление огрызка дроби при фейле, пик НЕ откатывается +
  `retry_undelivered_chukhan` (job 30мин + on-startup), фильтр
  `posted_at IS NOT NULL` в calendar/titles. HF `8fc7230`, Pages `78f4af4`.
- [x] **P13.** (2026-06-05/06) Рекурси-вес рандом-фраз: «порог+плато»
  (карантин 18ч, вес 0.05) в обоих композерах, настройки в admin_config +
  «🕰 Карантин свежести» в админке. Без новых запросов к Neon. Сьют 234.
  HF `2f4e04e`, Pages `5cbbbc3`.
- [x] **P2.4.** (2026-06-06) ДР-меню: 4 кнопки в `BirthdayPopover` («пост от
  бота»/«от своего имени» с подписью, `POST /api/birthdays/{id}/greeting/post`),
  poll-пресет «Собираемся на ДР {имя}?». Сьют 262. HF `8eef976`, Pages `bd455c3`.
- [x] **P3.** (2026-06-06/07) Иммунитет именинника к лоху/чухану:
  `birthdays.immunity_mode` ∈ {announce, silent} (default announce),
  `services/birthday_immunity.py` (`resolve_immune_pick`, оглашение «мог бы
  стать %name%, но ДР»), встроено во все 4 точки публикации + чухан; строка
  про иммунитет в поздравлении; чипы в `BirthdaysScreen`. Сьют 274.
  HF `2c13d2c`, Pages `3f01ab1`.
- [x] **P7.** (2026-06-07) Пул шуток на «мёртвый чат»: `services/dead_chat.py`
  (пороги 24h…год, фразы/метка/анти-спам в admin_config, активность =
  текст+медиа c троттлингом 15мин), job `dead_chat_hourly`, тогглер
  «🪦 Пинок мёртвого чата». Сьют 312. HF `d7c5c20`, Pages `4db9223`.
- **Q3/Q6/Q8/Q9.** Подтверждение работы мемов / актуализация чеклиста
  (этот файл) / прокси-констрейнты и диагностика — учтены в Q-NET.
