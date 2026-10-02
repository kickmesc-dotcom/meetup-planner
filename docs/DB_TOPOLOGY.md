# Топология баз данных GHG10 / meetup-planner

**Дата фиксации: 2026-10-02.** Секретов в документе нет: только маскированные
адреса, роли и процедуры. Полные DSN лежат в DPAPI-хранилище `secrets/` (см.
`secrets/README.md`) и в локальном `leltokens2.txt` — оба файла **не публикуются**.

Этот файл — карта на случай «куда мы вообще пишем» и «как догнать отставшую
базу». Историю выбора (Neon vs Amvera) и замеры объёма см. в
[DB_CHOICE.md](DB_CHOICE.md); здесь — только фактическая топология и процедура.

---

## 1. Что реально существует

Трассируются **ровно две** базы. Утверждение «три базы» проверить не удалось:
в `leltokens2.txt` и в `secrets/` только два DSN, третьего нет ни в репозитории,
ни в env (проверено 02.10.2026).

| # | Роль | Маскированный адрес | alembic | Кто пишет |
|---|------|---------------------|---------|-----------|
| 1 | **ПРОД (боевая)** | `ep-cool-union-…neon.tech` (Neon, EU `eu-central-1`) | `0026_music_track_likes` | живой бот на Amvera и на HF |
| 2 | **РЕЗЕРВ (холодный)** | `ep-rapid-butterfly-…neon.tech` (Neon) | `0026_music_track_likes` | никто — держим синхронным вручную |

Важная путаница, из-за которой базы раньше «менялись местами»:

* в `leltokens2.txt` **первым** идёт `ep-rapid-butterfly…`, и он выглядит как
  «основной», хотя исторически это был **мёртвый** резерв (`0017`, июнь 2026);
* боевой `ep-cool-union…` был помечен как «NEON 2 ALTERNATIVE — USE AFTER
  REACHING THE LIMIT».

Сейчас боевой — `ep-cool-union…`: только в нём свежие записи и игровые таблицы.
`/api/meta` у **обоих** хостов рапортовал именно `ep-cool-union-…neon.tech`, то
есть оба хоста пишут в одну базу.

> Оплаченная БД Amvera приложением **не используется**: DSN в env нет, `amvera.yml`
> прямо говорит «вся персистентность — в Neon Postgres».

Как проверить это самостоятельно, не заходя в консоли:

```bash
curl -s https://meetup-planner-youmakemefry.waw0.amvera.tech/api/meta | jq .db
curl -s https://fryesw-meetup-planner-backend.hf.space/api/meta   | jq .db
```

Ожидаемо: `provider=neon`, одинаковый маскированный `host`, `alembic_version`
равен `code.alembic_head`.

---

## 2. Как узнать, кто отстал

`/api/meta` — единственный «паспорт живого контейнера» (секретов не отдаёт):

* `code.alembic_head` — head миграций **в коде** (что контейнер умеет);
* `code.build` — короткий commit sha или хеш исходников (меняется от любой
  правки кода — видно, что деплой доехал, даже если список роутов не менялся);
* `db.alembic_version` — версия миграций **в базе** (что реально применено).

Расхождение диагностируется однозначно:

| `code.alembic_head` | `db.alembic_version` | Что это значит |
|---|---|---|
| `0026` | `0026` | всё в порядке |
| `0026` | `0025` | база **отстала** — нужен `alembic upgrade head` (раздел 3) |
| `0025` | `0026` | контейнер **стар** — пересобрать/задеплоить хост |
| `0026` | `error` | база недоступна из контейнера (проверить DSN/сеть/`DB_SSL`) |

Проверка обоих хостов и локального кода одной командой:

```bash
./meetup-planner-main/backend/.venv/Scripts/python.exe meetup-planner-main/tools/check-hosts.py
```

---

## 3. Процедура догона миграций (не трогая прод)

Догон делается **только для резерва** или для осознанно отставшего хоста. Прод
`ep-cool-union…` без явной задачи не трогаем — он на боевом.

1. **Снять снимок текущего состояния** (что где стоит):
   ```bash
   curl -s https://meetup-planner-youmakemefry.waw0.amvera.tech/api/meta | jq '{code:.code.build, head:.code.alembic_head, db:.db.alembic_version}'
   curl -s https://fryesw-meetup-planner-backend.hf.space/api/meta   | jq '{code:.code.build, head:.code.alembic_head, db:.db.alembic_version}'
   ```
2. **Поднять локальный venv** (Python 3.12) и экспортировать DSN **той базы,
   которую догоняем** — DSN берём из `secrets/`/`leltokens2.txt`, в переписку не
   копируем:
   ```bash
   export PYTHONIOENCODING=utf-8
   export DATABASE_URL='postgresql+asyncpg://…@ep-rapid-butterfly-…neon.tech/…'
   ```
   Если база не требует SSL (не Neon) — добавить `DB_SSL=disable`.
3. **Посмотреть, что применится, ДО применения** (dry-run, ничего не пишет):
   ```bash
   cd meetup-planner-main/backend
   ./.venv/Scripts/python.exe -m alembic current
   ./.venv/Scripts/python.exe -m alembic history --verbose | head -40
   ./.venv/Scripts/python.exe -m alembic upgrade head --sql | head -60
   ```
4. **Применить**:
   ```bash
   ./.venv/Scripts/python.exe -m alembic upgrade head
   ```
5. **Проверить результат** — `alembic current` должен показать head из кода, а
   повторный `/api/meta` этого хоста — совпадение `db.alembic_version` и
   `code.alembic_head`.
6. **Если догон делался у боевого хоста** — перезапустить его, чтобы процесс
   поднялся на новой схеме (см. `docs/deployment.md`), и снова проверить
   `/api/meta`.

Никаких `downgrade` в бою: схема синхронизируется только «вперёд». Обратный
переезд на отставшую базу = снова `alembic upgrade head`.

### Где живут миграции

* `meetup-planner-main/backend/alembic/versions/*.py` — источник правды; при
  старте контейнера Alembic подтягивает схему автоматически (`CMD` в Dockerfile).
* **Новых миграций на момент Э19 нет** — head остаётся `0026_music_track_likes`.
  Это важно: партия Э19 не требует `upgrade` ни на одном хосте.

---

## 4. Полный переезд на другую базу (если понадобится)

Порядок с дампом/restore, переключением env у обоих хостов и проверкой описан в
[DB_CHOICE.md](DB_CHOICE.md), разделы 4–6. Кратко:

1. `pg_dump --no-owner --no-acl --format=custom "$DATABASE_URL_SRC" > meetup-$(date +%F).dump`
2. Создать приёмник, прогнать `alembic upgrade head` (раздел 3).
3. `pg_restore --no-owner --no-acl -d "$DATABASE_URL_DST" meetup-….dump`
4. `DATABASE_URL` меняется у **обоих** хостов (HF + Amvera) — иначе они разъедутся.
5. Перезапуск, `tools/check-hosts.py`, сверка `db.host` и `alembic_version`.
6. Старую базу пометить датой заморозки, не удалять.

---

## 5. Автопроверка расхождения

`tests/test_db_alembic_head.py` сверяет **код-хеш head миграций** с фактическим
`alembic_version` на обеих базах и падает при расхождении. Тест строит ревизии
из локального `alembic/` (без сети) и проверяет консистентность DSN → head.
Живые базы он не опрашивает, если не задан `DB_HEAD_CHECK_DSNS` — так CI не
зависит от доступности Neon.
