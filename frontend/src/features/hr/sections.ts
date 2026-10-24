import type { Tab } from "@/store/ui";

/**
 * Разделы приложения: ядро и то, что руководитель может убрать.
 *
 * Ядро не выключается: без «Событий», «Задач» и «Чек-листа» приложение
 * превращается в пустой экран, а вернуть их из интерфейса было бы нечем.
 * «Профиль» тоже остаётся всегда — там настройки и выход.
 *
 * Один список на мастер, нижнюю полосу и сайдбар: раньше подписи и порядок
 * пришлось бы держать в трёх местах, и они бы разъехались.
 */
export const CORE_TABS: Tab[] = ["feed", "tasks", "checklist", "profile"];

export interface OptionalSection {
  id: Tab;
  label: string;
  hint: string;
}

export const OPTIONAL_SECTIONS: OptionalSection[] = [
  { id: "shifts", label: "Табель", hint: "График смен: кто когда работает" },
  { id: "team", label: "Команда", hint: "Сотрудники, роли и карточки" },
  { id: "review", label: "Приёмка", hint: "Работы, которые сдал персонал" },
  { id: "reports", label: "Отчёт смены", hint: "Срез дня и выгрузка" },
  { id: "issues", label: "Проблемы", hint: "Журнал сбоев и поломок" },
  { id: "handovers", label: "Передачи смены", hint: "Что важно знать следующей смене" },
  { id: "standards", label: "Стандарты", hint: "Инструкции и тесты по ним" },
  { id: "materials", label: "Материалы", hint: "Меню, график, методички" },
  { id: "links", label: "Ссылки", hint: "Полезные адреса и документы" },
  { id: "calendar", label: "Календарь", hint: "Встречи и отсутствия" },
  { id: "meetings", label: "Встречи и опросы", hint: "Сборы команды и голосования" },
];

/** Виден ли раздел при текущей настройке организации. */
export function sectionEnabled(tab: Tab, sections: readonly string[]): boolean {
  if (CORE_TABS.includes(tab)) return true;
  // Управление — не раздел организации, а права: его решает `isAdmin`.
  if (tab === "admin") return true;
  return sections.includes(tab);
}
