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
 * пропускал новые файлы, и эмодзи просачивались через них.
 *
 * Как читается исходник. Раньше комментарии вырезались регуляркой
 * `/\/\*[\s\S]*?\*\//`, и этого оказалось мало: `/*` внутри обычной строки
 * (`accept="image/*"`) открывал «комментарий», который тянулся до следующего
 * `*\/` на полсотни строк ниже. Весь этот кусок — включая кнопки с `📷` —
 * считался комментарием и не проверялся. Поэтому здесь маленький конечный
 * автомат: он различает код, строки, шаблонные литералы и комментарии, а
 * эмодзи ищет везде, кроме комментариев. Шаблонные подстановки `${…}`
 * возвращают автомат в режим кода, чтобы не пропустить `\`📷 ${label}\``.
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

// Пиктограммы и символы, которые рисует ОС, а не наш SVG. Диапазон начинается
// с 1F000: иначе мимо проходили «служебные» картинки вроде 🆕 (1F195) и 🆓.
// 2300–23FF — часы и таймеры (⌛ ⏰ ⏳), 2600–27BF — знаки и стрелки-эмодзи,
// FE0F — селектор эмодзи-начертания. Кириллица, тире и кавычки не попадают.
const PICTURE =
  /[\u{1F000}-\u{1FAFF}\u{2300}-\u{23FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/u;

type Hit = { line: number; text: string };

/**
 * Ищет эмодзи вне комментариев и возвращает строки с номерами.
 *
 * Автомат намеренно простой: он не разбирает JSX и регулярные литералы, его
 * задача — не спутать строку с комментарием. Регулярки в исходниках фронтенда
 * не содержат `//` и `/*` в опасных местах; если появятся — тест ниже об этом
 * сообщит ложным срабатыванием, а не пропуском.
 */
export function findPictures(source: string): Hit[] {
  const hits: Hit[] = [];
  let i = 0;
  let line = 1;
  let state: "code" | "line" | "block" | "single" | "double" | "template" =
    "code";
  // Глубина шаблонных подстановок: `${ … }` — снова код, `}` возвращает в текст.
  const templateDepth: number[] = [];

  const currentLine = () => {
    const start = source.lastIndexOf("\n", i - 1) + 1;
    let end = source.indexOf("\n", i);
    if (end < 0) end = source.length;
    return source.slice(start, end).trim();
  };
  const at = (offset: number) => source[i + offset] ?? "";

  while (i < source.length) {
    const char = source[i];

    if (char === "\n") {
      if (state === "line") state = "code";
      line++;
      i++;
      continue;
    }

    // Эмодзи ищем в любом состоянии, кроме комментариев: в строке и в
    // шаблонном литерале он тоже попадает на экран.
    if (state !== "line" && state !== "block") {
      const point = source.codePointAt(i)!;
      const symbol = String.fromCodePoint(point);
      if (PICTURE.test(symbol)) {
        hits.push({ line, text: currentLine() });
        i += symbol.length;
        continue;
      }
    }

    switch (state) {
      case "code": {
        if (char === "/" && at(1) === "/") {
          state = "line";
          i += 2;
          continue;
        }
        if (char === "/" && at(1) === "*") {
          state = "block";
          i += 2;
          continue;
        }
        if (char === "'") {
          state = "single";
          i++;
          continue;
        }
        if (char === '"') {
          state = "double";
          i++;
          continue;
        }
        if (char === "`") {
          state = "template";
          i++;
          continue;
        }
        if (char === "}" && templateDepth.length > 0) {
          // Закрылась подстановка `${ … }` — возвращаемся в текст шаблона.
          templateDepth.pop();
          state = "template";
          i++;
          continue;
        }
        i++;
        continue;
      }
      case "line": {
        i++;
        continue;
      }
      case "block": {
        if (char === "*" && at(1) === "/") {
          state = "code";
          i += 2;
          continue;
        }
        i++;
        continue;
      }
      case "single":
      case "double": {
        if (char === "\\") {
          i += 2;
          continue;
        }
        if (
          (state === "single" && char === "'") ||
          (state === "double" && char === '"')
        ) {
          state = "code";
        }
        i++;
        continue;
      }
      case "template": {
        if (char === "\\") {
          i += 2;
          continue;
        }
        if (char === "`") {
          state = "code";
          i++;
          continue;
        }
        if (char === "$" && at(1) === "{") {
          state = "code";
          templateDepth.push(1);
          i += 2;
          continue;
        }
        i++;
        continue;
      }
    }
  }
  return hits;
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
    const offenders = findPictures(source).map(
      (hit) => `${file}:${hit.line} ${hit.text}`,
    );
    expect(
      offenders,
      "замените эмодзи на <Icon> / <InlineIcon>",
    ).toEqual([]);
  });
});

/**
 * Самопроверка стража. Раз он однажды уже молчал на настоящем эмодзи, у него
 * должен быть тест на собственный разбор: комментарии пропускаем, строки,
 * шаблоны и «ловушку» `image/*` — нет.
 */
describe("P1.4: страж видит именно код, а не комментарии", () => {
  it("ловит эмодзи в строке и в шаблонном литерале", () => {
    const source = [
      "const label = `📷 ${compact ? 'Снять' : name}`;",
      'const plain = "⏳ Загружаю…";',
      "const single = '🖼 Галерея';",
    ].join("\n");
    expect(findPictures(source).map((hit) => hit.line)).toEqual([1, 2, 3]);
  });

  it("не считает комментарии разметкой", () => {
    const source = [
      "/** Раньше тут был ⏰ и 🎂. */",
      "// 📷 ушёл в историю",
      "const ok = 1;",
    ].join("\n");
    expect(findPictures(source)).toEqual([]);
  });

  it("не путает `/*` внутри строки с началом комментария", () => {
    // Ровно этот случай прятал кнопки PhotoAttach от проверки.
    const source = [
      '<input accept="image/*" />',
      '<button>📷 Снять</button>',
      "// конец",
    ].join("\n");
    expect(findPictures(source).map((hit) => hit.line)).toEqual([2]);
  });

  it("не считает комментарием `//` внутри строки", () => {
    const source = [
      'const url = "https://example.com/photo";',
      "const icon = '🎯';",
    ].join("\n");
    expect(findPictures(source).map((hit) => hit.line)).toEqual([2]);
  });
});
