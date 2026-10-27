/**
 * Страж скелетонов: мерцание не должно игнорировать «меньше движения».
 *
 * Зачем тест. `animate-pulse` на весь экран — это сотни элементов, которые
 * мигают одновременно. Для человека с вестибулярной чувствительностью (и просто
 * с усталыми глазами в конце смены) это хуже, чем статичный серый блок. Правило
 * простое: каждый `animate-pulse` несёт рядом `motion-reduce:animate-none`.
 *
 * Проверка идёт по строкам, а не по AST: разметка в проекте пишется так, что
 * классы одного элемента лежат на одной строке либо в одном литерале. Единственное
 * исключение — `components/Skeleton.tsx`, где пара собрана в константе `PULSE`
 * и подставляется во все скелетоны сразу.
 *
 * Второе обещание: экран не начинается с подмены всего содержимого. Если
 * скелетон уже стоит на месте заглушки — хорошо; плохо, когда при загрузке
 * пропадает шапка. За этим следит `loading.guard.test.ts` (он запрещает
 * текстовые заглушки), а здесь — только мерцание.
 */
import { describe, expect, it } from "vitest";

const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** Где пара классов собрана в одном месте. */
const PAIRED_ELSEWHERE = new Set(["components/Skeleton.tsx"]);

describe("skeleton guard", () => {
  it("каждое мерцание отключается при prefers-reduced-motion", () => {
    const offenders: string[] = [];
    for (const [path, raw] of Object.entries(sources)) {
      if (path.includes(".test.")) continue;
      const relative = path.replace(/^\.\//, "");
      if (relative.startsWith("_legacy/")) continue;
      if (PAIRED_ELSEWHERE.has(relative)) continue;
      raw.split("\n").forEach((line, index) => {
        if (!line.includes("animate-pulse")) return;
        if (line.includes("motion-reduce:animate-none")) return;
        offenders.push(`${relative}:${index + 1}`);
      });
    }
    expect(offenders).toEqual([]);
  });

  it("исключение действительно держит пару классов в константе", () => {
    const skeleton = sources["./components/Skeleton.tsx"] ?? "";
    expect(skeleton).toContain("const PULSE");
    expect(skeleton).toContain("motion-reduce:animate-none");
  });
});
