# CI: что проверяется и как включить блокировку мёржа

Шаг 5.1 плана (`B2B_PLATFORM_PLAN.md`). Файл workflow — `.github/workflows/ci.yml`,
он запускается на каждый пуш в `main` и на каждый pull request.

## Что именно проверяется

| Джоб | Команды | Что ловит |
| --- | --- | --- |
| Backend (pytest) | `pip install -e ".[dev]"`, `pytest -q` | регрессии в API, сервисах, миграциях (сверка схемы с моделями) и правах |
| Frontend | `npm ci`, `npm run typecheck`, `vitest run`, `npm run build` | ошибки типов, падение экранов, забытые переводы, сборку и чанки |

Почему те же команды, что локально. Любая «особая» команда в CI через месяц
расходится с рабочей машиной, и зелёный CI перестаёт что-либо значить. Здесь
исключений нет, кроме двух вынужденных:

* `maxForks=2` у vitest — на 2 vCPU раннере без ограничения прогон падает по
  таймаутам (воспроизводится и локально);
* `npm ci` вместо `npm install` — lock-файл должен быть источником правды.

Линтер (`eslint`) в CI не входит: в проекте нет `eslint.config.*`, и команда
падает на конфиге, а не на коде. Появится конфиг — шаг добавляется в тот же
workflow.

## Красный CI блокирует мёрж

GitHub не включает это по умолчанию: workflow зелёный или красный, но кнопка
«Merge» остаётся доступной. Правило включается в настройках репозитория и
требует прав администратора — это действие владельца, а не кода.

Через веб-интерфейс:

1. Settings → Branches → Add branch protection rule.
2. Branch name pattern: `main`.
3. Включить **Require status checks to pass before merging**.
4. В списке проверок выбрать `Backend (pytest)` и `Frontend (types, tests, build)`.
5. Включить **Require branches to be up to date before merging** — иначе
   зелёная проверка на старом коммите пропустит конфликт с новым `main`.
6. (по желанию) **Do not allow bypassing the above settings** — тогда правило
   действует и для администраторов.

Через `gh` (у владельца должен быть токен с правом `admin:repo`):

```bash
gh api -X PUT repos/kickmesc-dotcom/meetup-planner/branches/main/protection \
  -f "required_status_checks[strict]=true" \
  -f "required_status_checks[contexts][]=Backend (pytest)" \
  -f "required_status_checks[contexts][]=Frontend (types, tests, build)" \
  -f "enforce_admins=true" \
  -f "required_pull_request_reviews[required_approving_review_count]=0" \
  -f "restrictions="
```

Проверить, что правило включено:

```bash
gh api repos/kickmesc-dotcom/meetup-planner/branches/main/protection \
  --jq '.required_status_checks.contexts'
```

## Как посмотреть результат последнего прогона

```bash
gh run list --branch main --limit 5
gh run view <id> --log-failed
```

Без `gh`: вкладка Actions в репозитории. Каждый прогон привязан к коммиту,
поэтому по номеру коммита видно, чем именно он был проверен.
