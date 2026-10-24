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

  // ------------------------------------------------------------ чек-лист --
  "Чек-лист смены": "Shift checklist",
  "Чек-лист": "Checklist",
  "Открытие": "Opening",
  "Закрытие": "Closing",
  "Первый день": "First day",
  "Сегодня работаешь:": "You're working today:",
  "сменить": "change",
  "В каком зале работаешь?": "Which hall are you working in?",
  "У каждого зала свой чек-лист открытия. Выбор запомнится на сегодня — сменить можно в любой момент.":
    "Each hall has its own opening checklist. Your choice is kept for today — you can change it at any time.",
  "Залы не заведены. Попроси руководителя добавить их в разделе «Чек-листы».":
    "No halls yet. Ask your manager to add them under “Checklists”.",
  "выбран": "selected",
  "выбрать": "select",
  "Смена закрыта. Спасибо за работу!": "Shift closed. Thanks for your work!",
  "Смена открыта. Хорошей смены!": "Shift opened. Have a good shift!",
  "закрытия смены": "for closing the shift",
  "открытия зала": "for opening the hall",
  "первого дня": "for the first day",
  "Попроси руководителя назначить шаблон {variant}.":
    "Ask your manager to assign a checklist template {variant}.",
  "Не сегодня — {label}": "Not today — {label}",
  "по расписанию": "on schedule",
  "Пункт закрывается фотоотчётом": "This item closes with a photo report",
  "Отметить пункт": "Mark item",
  "(опц.)": "(optional)",
  "фотоотчёт приложен": "photo attached",
  "нужен фотоотчёт: снимок с камеры или из галереи":
    "photo required: take one or pick from the gallery",
  "Снять отчёт": "Take report photo",
  "закрыто в {time}": "closed at {time}",
  "Заметка": "Note",
  "Например: инвентарь в порядке, не хватило 2 упаковок":
    "For example: stock is fine, but 2 packs were missing",
  "Сохранить заметку": "Save note",

  // ---------------------------------------------------------- отчёт смены --
  "Отчёт смены": "Shift report",
  "Назад в профиль": "Back to profile",
  "Срез на дату": "Snapshot by date",
  "Дата смены": "Shift date",
  "Все отделы": "All departments",
  "Видно все отделы": "All departments visible",
  "Видно своё подразделение": "Own department visible",
  "людей {count}": "people: {count}",
  "Смен начато": "Shifts started",
  "из {count}": "of {count}",
  "Смен закрыто": "Shifts closed",
  "чек-лист на 100%": "checklist at 100%",
  "Поручений": "Tasks",
  "выполнено {count}": "{count} done",
  "сдано, но не принято": "submitted, not accepted",
  "за эту смену": "this shift",
  "Пробелы стандартов": "Standards gaps",
  "обязательные не сданы": "required not passed",
  "Сейчас в работе": "In progress now",
  "{tasks} поручений · {issues} проблем": "{tasks} tasks · {issues} issues",
  "Новых проблем за смену: {count}": "New issues this shift: {count}",
  "По отделам": "By department",
  "Обязательные стандарты": "Required standards",
  "только пробелы": "gaps only",
  "Обязательных стандартов пока нет — отметь их в базе стандартов.":
    "No required standards yet — mark them in the standards base.",
  "Все обязательные стандарты сданы.": "All required standards passed.",
  "{count} чел.": "{count} people",
  "Смены {started}/{employees} · закрыто {done}":
    "Shifts {started}/{employees} · closed {done}",
  "поручений {count}": "tasks {count}",
  "на проверке {count}": "on review {count}",
  "проблем {count}": "issues {count}",
  "пробелов {count}": "gaps {count}",
  "обязательный": "required",
  "Не сдали: {names}": "Not passed: {names}",
  "Только {name}": "Only {name}",
  "Файл готов: {name}": "File is ready: {name}",
  "Не получилось скачать файл — попробуй ещё раз.":
    "Couldn't download the file — please try again.",

  // ------------------------------------------------------------- команда --
  "Команда": "Team",
  "Назад": "Back",
  "Сводка смены": "Shift summary",
  "все подразделения": "all departments",
  "моё подразделение": "my department",
  "Смена начата": "Shift started",
  "Закрыто": "Closed",
  "Требует внимания": "Needs attention",
  "и ещё {count}": "and {count} more",
  "Подразделения": "Departments",
  "Подразделений пока нет.": "No departments yet.",
  "Сотрудники": "Employees",
  "Найти человека или должность": "Find a person or position",
  "Поиск по сотрудникам": "Search employees",
  "Сотрудников пока нет.": "No employees yet.",
  "Последние действия": "Recent activity",
  "Рабочие часы и уведомления": "Work hours and notifications",
  "смена закрыта": "shift closed",
  "не закрыта вовремя": "not closed on time",
  "в работе": "in progress",
  "не начинал": "not started",
  "закрыто {count}": "closed {count}",
  "Открыть карточку": "Open card",
  "Загружаем…": "Loading…",
  "Сохранить часы": "Save hours",
  "Алерты только в рабочее время": "Alerts during work hours only",
  "Вторая ступень: пинг админам": "Second level: ping admins",
  "Если руководитель молчит": "If the manager stays silent",
  "Порог второй ступени, часы": "Second level threshold, hours",
  "{hours} ч": "{hours} h",
  "Напоминать в каждой смене": "Remind on every shift",
  "Мьют до {when}": "Muted until {when}",
  "Мьют выключен": "Mute is off",
  "24ч": "24h",
  "3 дня": "3 days",
  "7 дней": "7 days",
  "30 дней": "30 days",
  "Снять": "Clear",
  "Ночью уведомления не уходят в чат, но копятся в приложении — утренний разбор не потеряется.":
    "At night notifications don't go to chat but pile up in the app — the morning review won't be lost.",
  "Сбрасывать нечего — всё уже закрыто.": "Nothing to reset — everything is already closed.",
  "Удалить {tasks} поручений и {issues} проблем?":
    "Delete {tasks} tasks and {issues} issues?",
  "Точно? Действие необратимо. Завершённые поручения и история останутся.":
    "Are you sure? This cannot be undone. Completed tasks and history stay.",
  "Удалено: поручений {tasks}, проблем {issues}.":
    "Deleted: {tasks} tasks, {issues} issues.",
  "Данные изменились, пока ты подтверждал. Открой сброс заново.":
    "The data changed while you were confirming. Open the reset again.",
  "Опасная зона": "Danger zone",
  "Убирает незакрытые поручения и открытые проблемы. Завершённые задачи, KPI и история сдач остаются; тестовый пул сбрасывается отдельно.":
    "Removes open tasks and open issues. Completed tasks, KPIs and submission history stay; the test pool is reset separately.",
  "Считаем…": "Counting…",
  "Сбросить текущую работу": "Reset current work",
};
