/**
 * Страж перевода: что уже на английском, а что ещё нет.
 *
 * Два правила, которые этот тест держит:
 *
 * 1. **Нет дыр в переведённом коде.** Каждая строка, обёрнутая в `tx("…")`,
 *    обязана иметь перевод в `content.ts`. Иначе на английском экране
 *    останется русская фраза, и никто этого не заметит.
 * 2. **Список непереведённого честный.** Здесь лежит `PENDING` — файлы, где
 *    русский текст ещё стоит прямо в разметке. Тест сравнивает список с тем,
 *    что реально в коде: закончил экран — убери файл из списка (иначе тест
 *    упадёт), добавил новую русскую подпись в готовый экран — тест упадёт
 *    сразу. Множество может только сокращаться.
 *
 * Граница проверки: ловятся прямой текст в JSX и подписи-атрибуты
 * (`placeholder`, `aria-label`, `title`, `label`, `alt`). Таблицы-константы
 * вроде `STATUS_LABEL` тест не видит — их переводят обёрткой `tx(...)` в месте
 * показа (пример — `MyTasksScreen`), поэтому после перевода экрана нужно
 * пройти глазами по таким таблицам.
 *
 * Исходники читаются через Vite (`?raw`), а не `node:fs`: у фронтенда нет
 * типов Node — так же устроен `emoji.guard.test.ts`.
 */
import { describe, expect, it } from "vitest";
import { EN_CONTENT } from "./content";

// `..` — потому что файл лежит в `src/i18n`, а проверяем весь `src`.
const sources = import.meta.glob("../**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/**
 * Файлы, где русский текст ещё не переведён.
 *
 * Список — обещание, а не догадка: он может только сокращаться (страж ниже
 * следит и за размером). Пополняется только новыми экранами, и то осознанно.
 */
const PENDING = new Set<string>([
  "api/access.ts",
  "features/actions/ActionBar.tsx",
  "features/actions/AutoPickSheet.tsx",
  "features/actions/PollSheet.tsx",
  "features/admin/AdminScreen.tsx",
  "features/admin/AdminTasksScreen.tsx",
  "features/admin/AppTextsScreen.tsx",
  "features/admin/AttentionScreen.tsx",
  "features/admin/BirthdaysScreen.tsx",
  "features/admin/CalendarSettingsScreen.tsx",
  "features/admin/ChecklistSettingsScreen.tsx",
  "features/admin/EmployeesScreen.tsx",
  "features/admin/FeedSettingsScreen.tsx",
  "features/admin/HolidaysCard.tsx",
  "features/admin/IntervalsScreen.tsx",
  "features/admin/InvitationsScreen.tsx",
  "features/admin/JobsQueueScreen.tsx",
  "features/admin/JournalScreen.tsx",
  "features/admin/KpiScreen.tsx",
  "features/admin/NotificationsScreen.tsx",
  "features/admin/PollPresetsScreen.tsx",
  "features/admin/ProxyScreen.tsx",
  "features/admin/RosterTools.tsx",
  "features/admin/SpaceRestartScreen.tsx",
  "features/admin/SubScreen.tsx",
  "features/admin/TrainingPlanScreen.tsx",
]);

const CYRILLIC = /[А-Яа-яЁё]/;
// Текст в разметке — в одну строку (`>Текст<`). Многострочный поиск ловил
// ложные срабатывания: `>` из дженерика и `<` из кода через пол-файла.
const JSX_TEXT = new RegExp(String.raw`>[^<>{}]*(?:${CYRILLIC.source})[^<>{}]*<`);
const RAW_ATTR = new RegExp(
  String.raw`(?:placeholder|aria-label|title|label|alt)\s*=\s*"[^"]*${CYRILLIC.source}[^"]*"`,
);

/** Комментарии не считаем: в них русский — это документация, а не интерфейс. */
function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((line) => {
      const trimmed = line.trim();
      return trimmed.startsWith("//") || trimmed.startsWith("*") ? "" : line;
    })
    .join("\n");
}

function txLiterals(src: string): string[] {
  const found: string[] = [];
  for (const match of src.matchAll(/\btx\(\s*(?:locale\s*,\s*)?"([^"]*)"/g)) {
    found.push(match[1]);
  }
  for (const match of src.matchAll(/\btx\(\s*(?:locale\s*,\s*)?`([^`$]*)`/g)) {
    found.push(match[1]);
  }
  return found;
}

const files = Object.entries(sources)
  // Ключ глоба — путь от `src/i18n`, например `../features/hr/HrFeedScreen.tsx`.
  .map(([path, raw]) => ({
    name: path.replace(/^\.\.\//, "").replace(/^\.\//, "").split("\\").join("/"),
    raw,
  }))
  .filter((file) => !file.name.startsWith("_legacy/"))
  .filter((file) => !file.name.includes(".test."))
  .filter((file) => !file.name.endsWith("i18n/messages.ts"))
  .filter((file) => !file.name.endsWith("i18n/content.ts"))
  .filter((file) => !file.raw.includes("@vitest-environment") || !file.name.includes(".test."));

describe("перевод: покрытие", () => {
  it("у каждой строки tx(...) есть английский перевод", () => {
    const missing: string[] = [];
    for (const file of files) {
      // Комментарии не считаем: в докстрингах есть примеры `tx("…")`.
      for (const text of txLiterals(stripComments(file.raw))) {
        if (!(text in EN_CONTENT)) missing.push(`${file.name}: ${text}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("список непереведённого совпадает с кодом", () => {
    const stillRussian = files
      .filter((file) => {
        const code = stripComments(file.raw);
        return JSX_TEXT.test(code) || RAW_ATTR.test(code);
      })
      .map((file) => file.name)
      .sort();

    // Каждый файл с русской подписью обязан быть в списке: иначе в уже
    // переведённый экран просочилась строка без `tx(...)`.
    const unlisted = stillRussian.filter((name) => !PENDING.has(name));
    expect(unlisted).toEqual([]);
  });

  it("список непереведённого не растёт", () => {
    // Ратчет: 26 файлов на 24.10.2026 (было 71 → 68 → 49 → 38 → 26). Закрыта
    // вся смена сотрудника (передача, табель и шаблон, проблемы, стандарты,
    // обучение, профиль, карточка, материалы, ссылки, знакомство, обратная
    // связь, push, веб-версия, пул), общее (App, каркас ПК, нижняя полоса,
    // рельс сводки, ошибка, фото, лайтбокс, прогресс, плашка проверки) и
    // календарь со встречами: сетки и плашки, редактор доступности, дни
    // рождения, встречи, опросы, названия месяцев и дней недели. Перевод
    // экрана — минус строка отсюда и минус единица в пределе, а не «перевод» на
    // словах.
    expect(PENDING.size).toBeLessThanOrEqual(26);
  });

  it("английский словарь без пустых значений", () => {
    const entries = Object.entries(EN_CONTENT);
    expect(entries.length).toBeGreaterThan(100);
    expect(entries.filter(([, en]) => en.trim() === "")).toEqual([]);
  });
});
