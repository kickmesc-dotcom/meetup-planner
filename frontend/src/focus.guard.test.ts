/**
 * Страж клавиатурного фокуса в формах.
 *
 * Зачем тест. Фокус — правило, которое тихо отменяется одной строкой. Здесь это
 * уже случилось: глобальное `:focus-visible` рисовало кольцо всем элементам, а
 * следующее правило гасило его полям ввода «чтобы не было второго кольца».
 * В итоге единственным индикатором оставалась перекраска рамки в 1px — а у
 * полей без рамки (`outline-none` без `focus:border-*`) не оставалось ничего.
 * Для клавиатуры это невидимый фокус: Telegram Desktop и Android с внешней
 * клавиатурой — реальные поверхности приложения.
 *
 * Поэтому проверяем три вещи:
 *  1. в `styles.css` у полей есть именно кольцо, а не `outline: none`;
 *  2. в разметке нет `focus:outline-none` — этот вариант перебивает общее
 *     правило по специфичности, и поле снова остаётся без индикатора;
 *  3. файл стилей вообще подключён, иначе всё вышеперечисленное не доедет.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import mainSource from "./main.tsx?raw";

const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

describe("фокус в полях ввода", () => {
  it("видит стили и исходники (иначе проверки ниже пустые)", () => {
    expect(css.length).toBeGreaterThan(1000);
    expect(Object.keys(sources).length).toBeGreaterThan(50);
    expect(mainSource).toContain('import "./styles.css"');
  });

  it("поле получает кольцо фокуса, а не только перекраску рамки", () => {
    const block = css.match(/input:focus-visible[\s\S]{0,600}?\}/);
    expect(block).not.toBeNull();
    expect(block?.[0]).toContain("outline: 2px solid");
    expect(block?.[0]).not.toContain("outline: none");
  });

  it("в разметке нет `focus:outline-none`: он перебивает общее кольцо", () => {
    const offenders: string[] = [];
    for (const [path, raw] of Object.entries(sources)) {
      if (path.includes(".test.")) continue;
      const relative = path.replace(/^\.\//, "");
      if (relative.startsWith("_legacy/")) continue;
      raw.split("\n").forEach((line, index) => {
        if (line.includes("focus:outline-none")) {
          offenders.push(`${relative}:${index + 1}`);
        }
      });
    }
    expect(offenders).toEqual([]);
  });
});
