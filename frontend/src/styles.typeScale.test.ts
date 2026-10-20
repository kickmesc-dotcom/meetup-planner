// @vitest-environment node
/**
 * VISUAL_AUDIT P1.5: типографика живёт только на шкале из DESIGN_SYSTEM §2.
 *
 * До этого прохода размеры задавались как `text-[11px]` (327 раз), `text-[10px]`
 * (86), а местами и `text-[8px]`/`text-[9px]` — ниже минимума 10px. «11px как
 * тело текста» и было главной претензией аудита: описания и подписи вторичных
 * действий читались как мелкий шум.
 *
 * Тест держит два обещания:
 *  - в разметке нет произвольных `text-[Npx]` — только `text-3xs|2xs|xs|sm|...`;
 *  - сами токены объявлены в `tailwind.config.ts` (иначе класс молча не
 *    сгенерируется и текст отрендерится размером родителя).
 *
 * Исходники читаются через `import.meta.glob(?raw)`, а не через `node:fs`:
 * у фронтенда нет `@types/node`, и тест не должен тянуть новую зависимость.
 */
import { describe, expect, it } from "vitest";
// Конфиг читаем текстом (`?raw`): импорт как модуля затянул бы его в проверку
// типов и всплыли бы старые ошибки типизации `themeColor` — к шкале не относится.
import tailwindConfig from "../tailwind.config.ts?raw";

const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const ARBITRARY_SIZE = /text-\[\d+px\]/;

describe("типографическая шкала", () => {
  it("действительно видит исходники (иначе проверка ниже пустая)", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50);
  });

  it("не использует произвольные размеры text-[Npx]", () => {
    const offenders: string[] = [];
    for (const [file, source] of Object.entries(sources)) {
      if (/\.test\./.test(file)) continue;
      source.split("\n").forEach((line, i) => {
        const match = line.match(ARBITRARY_SIZE);
        if (match) offenders.push(`${file}:${i + 1} — ${match[0]}`);
      });
    }
    expect(offenders).toEqual([]);
  });

  it("объявляет токены 3xs/2xs в tailwind.config.ts", () => {
    expect(tailwindConfig).toContain('"3xs"');
    expect(tailwindConfig).toContain('"2xs"');
  });
});
