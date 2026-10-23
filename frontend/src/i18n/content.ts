/**
 * Английские тексты экранов. Ключ — русский оригинал.
 *
 * Почему ключом служит сам русский текст, а не `feed.title`-подобное имя.
 * Экранов 94 и строк в них под две тысячи. Придумывать и поддерживать две
 * тысячи имён — это отдельная работа, которая ничего не даёт человеку: в
 * коде и так видно, что показывается. Зато у такого словаря есть важное
 * свойство: **непереведённая строка не ломается**, она просто остаётся
 * русской (`tx("Текст")` возвращает сам текст, если перевода нет). Поэтому
 * перевод делается по одному экрану, а не «всё или ничего».
 *
 * Что это НЕ отменяет: покрытие проверяется тестом
 * `src/i18n/coverage.test.ts` — каждая строка, обёрнутая в `tx(...)`, обязана
 * иметь перевод здесь, а список ещё не переведённых файлов лежит в тесте и
 * может только сокращаться. Так «переведено» — это проверяемое утверждение,
 * а не обещание.
 *
 * Формат: `"Русский оригинал": "English text"`. Подстановки — `{name}`,
 * одинаковые в обоих языках (см. `tx`).
 */
export const EN_CONTENT: Record<string, string> = {
  // ---------------------------------------------------------------- лента --
  "События смены": "Shift events",
  "Мои действия": "My actions",
  "Моё подразделение": "My department",
  "Всё предприятие": "Whole company",
  "Чужих записей здесь нет.": "No one else's entries here.",
  "Коллеги из других подразделений сюда не попадают.":
    "Colleagues from other departments don't appear here.",
  "Всё, что происходит на смене.": "Everything that happens on shift.",
  "Чек-лист закрыт": "Checklist closed",
  "Пункт чек-листа": "Checklist item",
  "Поручение": "Task",
  "Статус поручения": "Task status",
  "Фотоотчёт": "Photo report",
  "Проблема": "Issue",
  "Без даты": "No date",
  "Лента недоступна": "Feed unavailable",
  "Загружаем правила видимости…": "Loading visibility rules…",
  "{count} новых": "{count} new",
  "Поиск по имени или должности": "Search by name or position",
  "Поиск сотрудника": "Search employee",
  "Фильтр": "Filter",
  "Сбросить фильтры": "Reset filters",
  "Видны только твои действия. Расширенные фильтры доступны руководителю подразделения и управляющему.":
    "You see only your own actions. Advanced filters are available to the department manager and the owner.",
  "Пока тихо": "Quiet for now",
  "Здесь появятся отметки и поручения.":
    "Checklist marks and tasks will appear here.",
  "Предыдущий день": "Previous day",
  "Следующий день": "Next day",
  "Новые события: {count}": "New events: {count}",
  "Новые · {count}": "New · {count}",
  "Убрать фильтр {label}": "Remove filter {label}",
  "Фильтры ленты": "Feed filters",
  "Закрыть фильтры": "Close filters",
  "Фильтры": "Filters",
  "Закрыть": "Close",
  "Подразделение": "Department",
  "Все подразделения": "All departments",
  "Сотрудник": "Employee",
  "Поиск сотрудника в фильтре": "Search employee in filters",
  "Все сотрудники": "All employees",
  "Никого не нашли.": "Nobody found.",
  "Сбросить": "Reset",
  "Готово": "Done",
  "Тестовый сотрудник": "Test employee",
  "тест": "test",

  // --------------------------------------------------------------- задачи --
  "Мои задачи": "My tasks",
  "Привет, {name}": "Hi, {name}",
  "База стандартов": "Standards",
  "Приёмка работ": "Work review",
  "Передача смены": "Shift handover",
  "Что нужно сделать сегодня": "What to do today",
  "задач {count}": "{count} tasks",
  "просрочено {count}": "{count} overdue",
  "Активные": "Active",
  "Все": "All",
  "Смена сегодня": "Shift today",
  "Смена закрыта": "Shift closed",
  "Открыть чек-лист": "Open checklist",
  "Посмотреть чек-лист": "View checklist",
  "Продолжить чек-лист": "Continue checklist",
  "Начать смену": "Start shift",
  "Проблемы": "Issues",
  "открыто {count}": "{count} open",
  "{count} ждут внимания: срок или повтор.":
    "{count} need attention: deadline or repeat.",
  "Все в работе — открой журнал, если нужен статус.":
    "All in progress — open the log if you need a status.",
  "На сегодня всё": "All done for today",
  "Задач нет — можно проверить чек-лист смены.":
    "No tasks — you can go through the shift checklist.",

  // статусы, приоритеты и причины
  "Новое": "New",
  "Принято": "Accepted",
  "В работе": "In progress",
  "На проверке": "On review",
  "На доработке": "Rework",
  "Выполнено": "Done",
  "Просрочено": "Overdue",
  "Не выполнено": "Not done",
  "низкий": "low",
  "обычный": "normal",
  "высокий": "high",
  "Не хватает времени": "Not enough time",
  "Нужна помощь": "Need help",
  "Нет материалов/доступа": "No materials/access",
  "Оборудование не работает": "Equipment is broken",
  "Другое": "Other",

  // карточка поручения
  "без срока": "no deadline",
  "сегодня {time}": "today {time}",
  "завтра {time}": "tomorrow {time}",
  "вчера {time}": "yesterday {time}",
  "смена {date}": "shift {date}",
  "не сегодня · {label}": "not today · {label}",
  "приоритет: {label}": "priority: {label}",
  "фото есть": "photo attached",
  "нужен фотоотчёт": "photo required",
  "с приёмкой": "with review",
  "просрочено": "overdue",
  "сделали {done} из {total}": "{done} of {total} done",
  "Моя часть:": "My part:",
  "Результат:": "Expected result:",
  "Работа сдана — ждёт приёмки руководителя.":
    "Work submitted — waiting for the manager's review.",
  "Принять": "Accept",
  "Начать": "Start",
  "Взять в работу": "Start work",
  "Сдать на проверку": "Submit for review",
  "Отмена": "Cancel",
  "Не успеваю": "I'm running late",
  "Добавить фото": "Add photo",
  "Руководителю отправлено объяснение. Срок отсчитывается заново.":
    "The manager got your explanation. The deadline counts from now.",
  "Причина": "Reason",
  "Когда сможешь закончить (необязательно)": "When can you finish (optional)",
  "Комментарий": "Comment",
  "Что именно мешает?": "What exactly is blocking you?",
  "Отправить руководителю": "Send to manager",
  "Фотоотчёт: сними или выбери фото — поручение закроется само.":
    "Photo report: take or pick a photo — the task will close itself.",
};
