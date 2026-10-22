/**
 * VISUAL_AUDIT P1.4: эмодзи в интерфейсе заменены SVG-иконками.
 *
 * Почему страж, а не разовая чистка. Эмодзи возвращаются сами: достаточно
 * скопировать строку из старого экрана или бота. При этом на Windows/iOS/Android
 * один и тот же символ рисуется по-разному (цветной/чёрно-белый, другой размер),
 * и «фирменная» строка разъезжается от устройства к устройству.
 *
 * Правило: в перечисленных экранах (то, что сотрудник видит каждый день)
 * структурные элементы — заголовки, статусы, кнопки, метаданные карточек —
 * используют `<Icon>`. Эмодзи остаются в:
 *  • текстах бота и чата (там живёт собственный язык продукта);
 *  • поздравлениях и игровых формулировках (🎂, 🎉);
 *  • данных с сервера: эмодзи ачивок, подразделений, категорий проблем.
 *
 * Комментарии из проверки исключены: пояснение «раньше тут был ⏰» полезно
 * и не попадает на экран.
 */
import { describe, expect, it } from "vitest";

// Исходники читаем через Vite (`?raw`), а не `node:fs`: у фронтенда нет
// `@types/node`, и страж не должен тянуть новую зависимость ради чтения
// текстовых файлов (так же устроен `styles.typeScale.test.ts`).
const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

function sourceOf(file: string): string {
  return sources[`./${file}`] ?? "";
}

/** Экраны ежедневного контура: их владелец видит первыми. */
const GUARDED = [
  "App.tsx",
  "features/hr/HrFeedScreen.tsx",
  "features/hr/MyTasksScreen.tsx",
  "features/hr/ChecklistScreen.tsx",
  "features/hr/TeamScreen.tsx",
  "features/hr/ReviewScreen.tsx",
  "features/hr/HrProfileScreen.tsx",
  "features/handovers/HandoversScreen.tsx",
  "features/issues/IssuesScreen.tsx",
  "features/shifts/ShiftsScreen.tsx",
  "features/desktop/DesktopShell.tsx",
  "features/desktop/OverviewRail.tsx",
];

// Пиктограммы, символы статусов и variation selector: всё, что рисует ОС,
// а не наш SVG. Кириллица, тире и кавычки под правило не попадают.
const PICTURE =
  /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{23E9}-\u{23FA}\u{FE0F}]/u;

function stripComments(source: string): string[] {
  const withoutBlocks = source.replace(/\/\*[\s\S]*?\*\//g, (block) =>
    block.replace(/[^\n]/g, " "),
  );
  return withoutBlocks
    .split(/\r?\n/)
    .filter((line) => !line.trimStart().startsWith("//"));
}

describe("P1.4: структурный интерфейс без эмодзи", () => {
  it.each(GUARDED)("%s рисует иконки, а не картинки ОС", (file) => {
    const source = sourceOf(file);
    // Если файл переименовали, страж обязан упасть, а не пройти вхолостую.
    expect(source, `не найден исходник ${file}`).not.toBe("");
    const lines = stripComments(source);
    const offenders = lines
      .map((line, index) => ({ line: line.trim(), number: index + 1 }))
      .filter((row) => PICTURE.test(row.line));
    expect(
      offenders.map((row) => `${file}:${row.number} ${row.line}`),
      "замените эмодзи на <Icon> / <InlineIcon>",
    ).toEqual([]);
  });
});
