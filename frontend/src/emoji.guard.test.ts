/**
 * VISUAL_AUDIT P1.4: эмодзи в интерфейсе заменены SVG-иконками.
 *
 * Почему страж, а не разовая чистка. Эмодзи возвращаются сами: достаточно
 * скопировать строку из старого экрана или бота. При этом на Windows/iOS/Android
 * один и тот же символ рисуется по-разному (цветной/чёрно-белый, другой размер),
 * и «фирменная» строка разъезжается от устройства к устройству.
 *
 * Правило: в разметке (`*.tsx`) структурные элементы — заголовки, статусы,
 * кнопки, метаданные карточек — используют `<Icon>`. Эмодзи остаются в:
 *  • текстах бота и чата (там живёт собственный язык продукта);
 *  • поздравлениях и игровых формулировках (🎂, 🎉);
 *  • данных: эмодзи ачивок, подразделений, категорий проблем, стандартов —
 *    они приходят из базы или живут в `api/*.ts` как данные, а не как вёрстка.
 *
 * Проверяются ВСЕ `.tsx` вне `_legacy` и тестов: фиксированный список экранов
 * пропускал новые файлы, и эмодзи просачивались через них. Комментарии из
 * проверки исключены: пояснение «раньше тут был ⏰» полезно и не попадает на
 * экран.
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

const SCREENS = Object.keys(sources)
  .filter((file) => file.endsWith(".tsx"))
  .filter((file) => !file.includes(".test."))
  .filter((file) => !file.split("/").includes("_legacy"))
  .sort();

describe("P1.4: разметка без эмодзи", () => {
  it("сканирует все экраны, а не фиксированный список", () => {
    // Если glob сломается, тест ниже пройдёт вхолостую — это защита.
    expect(SCREENS.length).toBeGreaterThan(40);
  });

  it.each(SCREENS)("%s рисует иконки, а не картинки ОС", (file) => {
    const source = sources[file] ?? "";
    expect(source, `не найден исходник ${file}`).not.toBe("");
    const offenders = stripComments(source)
      .map((line, index) => ({ line: line.trim(), number: index + 1 }))
      .filter((row) => PICTURE.test(row.line));
    expect(
      offenders.map((row) => `${file}:${row.number} ${row.line}`),
      "замените эмодзи на <Icon> / <InlineIcon>",
    ).toEqual([]);
  });
});
