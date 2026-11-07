/**
 * UI_UX_PRO_MAX §9 `z-index-management`: слои приложения — шкала, а не числа.
 *
 * Зачем страж. Числовой `z-50` рядом с `z-40` выглядит безобидно, но порядок
 * слоёв перестаёт быть проверяемым: следующая шторка получает `z-[60]`, потом
 * `z-[70]`, и однажды лайтбокс оказывается под панелью. Шкала в
 * `tailwind.config.ts` — `z-sheet` (40), `z-overlay` (50), `z-lightbox` (100) —
 * даёт три осмысленных уровня, и этот тест не пускает обратно числовые.
 *
 * Локальные `z-10`/`z-20` разрешены: это порядок внутри одного прокручиваемого
 * контейнера (sticky-строка дня, шапка таблицы), а не слой приложения.
 * `_legacy` не проверяется: эти экраны не подключены к маршрутам.
 */
import { describe, expect, it } from "vitest";

const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const NUMERIC_LAYER = /\bz-(?:40|50|\[100\])\b/g;

describe("шкала слоёв", () => {
  it("в живом коде нет числовых слоёв приложения", () => {
    const offenders = Object.entries(sources)
      .filter(([path]) => !path.includes("_legacy/"))
      .filter(([path]) => !path.includes(".test."))
      .flatMap(([path, raw]) =>
        [...raw.matchAll(NUMERIC_LAYER)].map(
          (match) => `${path.replace(/^\.\//, "")}: ${match[0]}`,
        ),
      );

    expect(offenders).toEqual([]);
  });
});
