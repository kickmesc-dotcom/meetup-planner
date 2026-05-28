# Meetup Planner — чеклист GHG6 (остаток)

Источник: `C:\Users\fa1nt\GHG6.txt`. Дата старта итерации: 2026-05-18.
Single source of truth: `C:\Users\fa1nt\meetup-planner-main` (монорепо `backend/` + `frontend/`).
После каждого блока с правками `backend/` — `cp backend/* → C:\Users\fa1nt\meetup-planner-backend\`
(отдельный git remote → HF Space). Frontend синхронизирует пользователь сам в
`kickmesc-dotcom/meetup-planner` (Pages).

Легенда: `[ ]` — не сделано, `[~]` — в работе, `[x]` — закрыто.

Все закрытые разделы (P0–P3, CL1–CL9, D, E1–E11, F, G1–G3, H, I, J, K, L, M, N1,
а также N2.1–N2.6 — бэк и фронт) выгребены 2026-05-28. Детали — в git log и в
`DEPLOY_NOTES.md`. Здесь только открытые хвосты.

---

## N2 — Пост-фактум 5★ голосование (остаток: только синк)

Бэк (миграция `0013_meeting_feedback.py`, модель `MeetingFeedback`,
`services/meeting_feedback.py`, scheduler-job `JOB_MEETING_FEEDBACK`, handler
`poll_answer.py`, admin-endpoint `/admin/meeting-feedback[/history]`,
admin_config-ключи `meeting_feedback.{enabled,notify_absence,absence_weight_delta}`,
тесты `tests/test_meeting_feedback.py` 14/14 ✅, полный сьют 150/150 ✅) — все
закрыто 2026-05-27/28 в `meetup-planner-main`. Фронт (`api/admin.ts`:
`MeetingFeedbackSettings`/`MeetingFeedbackRow` + `fetchMeetingFeedbackHistory`,
`HistoryScreen.tsx` подключение) — тоже закрыто.

### Sync
- [x] **D-N.** (2026-05-28) Скопированы из `meetup-planner-main/backend/` в
  `meetup-planner-backend/`:
    - `alembic/versions/0013_meeting_feedback.py` (новый)
    - `app/db/models.py` (`MeetingFeedback`)
    - `app/services/meeting_feedback.py` (новый)
    - `app/services/admin_config.py` (N2-ключи)
    - `app/api/routes_admin.py` (`/admin/meeting-feedback*`)
    - `app/bot/scheduler.py` (`JOB_MEETING_FEEDBACK`)
    - `app/bot/handlers/poll_answer.py` (`POLL_KIND_MEETING_FEEDBACK`)
    - `tests/test_meeting_feedback.py` (новый)
  `diff -rq main/backend ↔ backend` чист (кроме `.venv/.git/__pycache__/
  .pytest_cache/.env/.gitignore`). `git status` в HF-клоне показывает ровно
  эти 8 файлов (5 M + 3 ??). Push в HF — за пользователем.
  Frontend (`frontend/src/api/admin.ts`, `frontend/src/features/admin/HistoryScreen.tsx`)
  — пушится пользователем из `meetup-planner-main` в `kickmesc-dotcom/meetup-planner`.

---

## D-MEM — обновить память после релиза

- [ ] **D-MEM.** После реального релиза GHG6 (push backend в HF + push frontend
  в `kickmesc-dotcom/meetup-planner`, проверка прод-хелсчека) — обновить
  `project_meetup_planner_deployed.md`: текущая дата актуальности, упоминание
  N2-флагов в списке HF env (если решим добавлять `MEETING_FEEDBACK_*` как env;
  сейчас они живут только в `admin_config`, env не нужен).
