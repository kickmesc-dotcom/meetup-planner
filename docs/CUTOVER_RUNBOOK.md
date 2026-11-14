# Переключение базы Neon → Amvera: рунбук

Дата: **13.11.2026**. Операционная версия плана `docs/INFRA_CHOICE.md` §7.
Рассчитан на одно окно 20–30 минут; простой — до минуты на смену переменной.
Репетиция на копии данных пройдена: `docs/CUTOVER_REHEARSAL.md`.

**Зачем сейчас.** Neon израсходовал 80 из 100 CU-часов за две недели ноября при
сбросе квоты 1 декабря. При текущем темпе лимит кончится раньше, и API начнёт
отдавать 503.

---

## 0. Перед окном (10 минут)

- [ ] Убедиться, что лишние хосты не пишут в боевую базу: HF Space
      `fryesw/meetup-planner-backend` остановлен, проекты Amvera `semitask` и
      `semitaskbot` остановлены. Два живых хоста на одной базе — источник
      расхождений, а не страховка.
- [ ] Снять свежий дамп и проверить его:

```bash
cd meetup-planner-main
backend/.venv/Scripts/python.exe tools/backup-db.py dump
backend/.venv/Scripts/python.exe tools/backup-db.py verify backups/<штамп>
```

- [ ] Прогнать репетицию на этом же дампе — она должна быть зелёной:

```bash
backend/.venv/Scripts/python.exe tools/db-rehearsal.py cutover backups/<штамп>
```

Ждём `✅ ПЕРЕЕЗД ОБРАТИМ`. Если красная — переезд не начинать.

## 1. Создать Managed PostgreSQL в Amvera

Amvera → проект `meetup-planner` → PostgreSQL: регион **Warsaw-0** (там же, где
приложение), тариф «Начальный», диск 1 ГБ. Записать DSN: хост, порт, база,
пользователь, пароль.

Проверить, что база доступна снаружи (с неё будем заливать дамп):

```bash
cd meetup-planner-main/backend
DATABASE_URL='postgresql+asyncpg://<user>:<pass>@<host>:<port>/<db>' \
  .venv/Scripts/python.exe -m alembic current
```

Подключение прошло, если команда не упала (версия пустая — база новая). Ошибка
SSL — добавить `DB_SSL=disable` и повторить.

## 2. Залить данные (порядок важен)

Схема доводится до **ревизии дампа**, а не до `head`: иначе колонки, добавленные
позже, заполнятся значением по умолчанию раньше настоящих данных. Ровно на этом
спотыкалась первая репетиция (`organizations.media_key`, миграция `0075`).

```bash
cd meetup-planner-main/backend
export NEW_DSN='postgresql+asyncpg://<user>:<pass>@<host>:<port>/<db>'

# 1) схема на ревизию дампа (сейчас 0074_org_branches; смотреть в manifest.json)
DATABASE_URL="$NEW_DSN" .venv/Scripts/python.exe -m alembic upgrade 0074_org_branches

# 2) данные
DATABASE_URL="$NEW_DSN" .venv/Scripts/python.exe ../tools/backup-db.py restore ../backups/<штамп> --yes

# 3) сверка с дампом — до догона миграций
.venv/Scripts/python.exe ../tools/db-rehearsal.py check ../backups/<штамп> --dsn "$NEW_DSN"

# 4) догон миграций до head
DATABASE_URL="$NEW_DSN" .venv/Scripts/python.exe -m alembic upgrade head
DATABASE_URL="$NEW_DSN" .venv/Scripts/python.exe -m alembic current
```

**Пройдено, если:** `check` дал «совпало» по каждой таблице, а `alembic current`
показывает тот же head, что `/api/meta` → `code.alembic_head`.

## 3. Переключить приложение

Amvera → `meetup-planner` → Переменные → `DATABASE_URL` = новый DSN →
перезапуск контейнера. Если подключение падает на SSL — добавить `DB_SSL=disable`
(режим явный, см. `DB_CHOICE.md` §5); при самоподписанном сертификате —
`DB_SSL_VERIFY=off`.

Контейнер сам применяет миграции при старте (`app/db/migrate`) под
advisory-lock, поэтому ручной `alembic upgrade` здесь — страховка, а не
обязанность.

## 4. Приёмка на живом контуре

| Проверка | Команда / действие | Критерий |
|---|---|---|
| Жив | `curl -s -o /dev/null -w '%{http_code}' .../healthz` | 200 |
| База отвечает | `curl -s .../readyz` | `{"db":"ok"}` и **ms заметно меньше 200** |
| Куда смотрим | `curl -s .../api/meta` | `provider` = `amvera` (или `other`), версия = `head` |
| Вход | почта/пароль или Telegram | лента открылась |
| Задачи | «Мои задачи» → открыть | данные на месте |
| Чек-лист | «Смена» → отметить пункт | сохраняется |
| Бот | `getWebhookInfo` в Telegram | `pending_update_count: 0`, ошибок нет |
| Фоновые задачи | логи Amvera | строки `scheduler.job_fired` |
| Планировщик | `curl .../api/meta` → `scheduler.lease` | `renew_seconds` 600, `ttl_seconds` 1200 |

Главная проверка переезда — **время `/readyz`**: было ~577 мс до Neon, база рядом
с приложением должна отвечать в разы быстрее. Если цифра не упала, база не там,
где думали.

## 5. Откат (одно действие)

Вернуть прежний `DATABASE_URL` в переменных Amvera и перезапустить контейнер.
Neon не трогаем сутки — это и есть окно отката.

Честная оговорка: откат возвращает состояние **на момент переключения**. Записи,
сделанные после переключения в новую базу, в Neon не попадут — их придётся
переносить вручную или принять потерю. Поэтому переключение лучше делать в
тихое окно, когда сотрудники не работают.

## 6. Сутки после

- [ ] Сверить размеры и ключевые счётчики: `users`, `checklist_items`, `tasks` —
      против Neon (`db-rehearsal.py check` по старому DSN на том же дампе).
- [ ] Убедиться, что `/readyz` стабилен, а в логах нет `readyz.db_timeout`.
- [ ] Проверить, что ежедневный бэкап (`backup.yml`) теперь снимает новую базу —
      иначе точка отката осталась в прошлом.
- [ ] Только после этого остановить Neon (проект не удалять ещё неделю).

## 7. Документация

Обновить `DB_CHOICE.md`, `DEPLOY_NOTES.md`, `docs/deployment.md`,
`docs/MANUAL_ACCEPTANCE.md` и пункт этапа 9 в `docs/AAA_ROADMAP.md`: нигде не
должно остаться «боевая база — Neon».
