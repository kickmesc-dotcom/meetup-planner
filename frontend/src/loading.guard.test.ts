/**
 * Страж загрузки: в экранах не должно быть надписей «Загрузка…».
 *
 * Зачем тест, а не «мы договорились». Медленный контур (холодный старт
 * контейнера, запросы к Neon) уже приводил к тому, что люди видели пустой экран
 * и решали, что приложение сломалось. Договорённость «показываем каркас, а не
 * надпись» проверить глазами нельзя: новых экранов много, и надпись вернётся
 * с первым же «быстрым» местом.
 *
 * Правило (план, раздел 9): загрузка показывается скелетоном той же формы
 * (`components/Skeleton`), текст допустим только для ПРОЦЕССА, который уже
 * начался по действию человека — отправка фото, сохранение. Такие места
 * перечислены в `PROCESS_LABELS` с причиной.
 *
 * Комментарии не считаются: в них русский текст — документация.
 */
import { describe, expect, it } from "vitest";

const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** Процесс, а не загрузка данных: человек нажал — идёт отправка. */
const PROCESS_LABELS = new Map<string, string>([
  ["components/PhotoAttach.tsx", "прогресс отправки фото, а не загрузка экрана"],
]);

// Надписи, которые означают «данные ещё едут»: их место занимает скелетон.
const FORBIDDEN = /(Загрузка…|Загружаю…|Загружаем…|загрузка…|Loading…)/;

/** Где правило не действует и почему. */
const SKIP_DIRS = [
  // Старый контур, в интерфейсе не показывается.
  "_legacy/",
  // Словарь переводов: там строки лежат как данные, а не как разметка экрана.
  "i18n/content.ts",
];

function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .filter((line) => !line.trim().startsWith("//"))
    .join("\n");
}

describe("loading guard", () => {
  it("не оставляет текстовых заглушек загрузки в экранах", () => {
    const offenders: string[] = [];
    for (const [path, raw] of Object.entries(sources)) {
      if (path.includes(".test.")) continue;
      const relative = path.replace(/^\.\//, "");
      if (SKIP_DIRS.some((dir) => relative.startsWith(dir))) continue;
      if (PROCESS_LABELS.has(relative)) continue;
      if (FORBIDDEN.test(stripComments(raw))) offenders.push(relative);
    }
    expect(offenders).toEqual([]);
  });

  it("список исключений не разрастается бессмысленно", () => {
    // Каждое исключение — это возможность для человека снова смотреть на
    // надпись вместо формы, поэтому оно должно быть объяснено в файле.
    for (const [path, reason] of PROCESS_LABELS) {
      expect(reason.length).toBeGreaterThan(10);
      expect(sources[`./${path}`]).toBeTruthy();
    }
  });
});
