// @vitest-environment node
/**
 * UI_UX_PRO_MAX §7 `breakpoint-consistency`: брейкпоинты — шкала, а не числа
 * по месту.
 *
 * До прохода `sm`/`lg` стояли точечно, а единственная двухколоночная раскладка
 * задач включалась на `xl` (1280): на ноутбуке 1024 она не включалась вовсе.
 * Здесь два обещания:
 *
 *  - в конфиге объявлены только `xs/sm/md/lg` — 375/640/768/1024;
 *  - в разметке нет `xl:`/`2xl:` и произвольных `min-[NNNpx]:`.
 *
 * Ширины контейнеров (`max-w-[560px]`) — не брейкпоинты и остаются.
 */
import { describe, expect, it } from "vitest";
import tailwindConfig from "../tailwind.config.ts?raw";

const sources = import.meta.glob("./**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const UNKNOWN_SCALE = /\b(xl|2xl):/;
const ARBITRARY_MEDIA = /(?:min|max)-\[\d+px\]:/;

describe("шкала брейкпоинтов", () => {
  it("объявляет xs/sm/md/lg и не оставляет xl/2xl", () => {
    expect(tailwindConfig).toMatch(/screens:\s*\{/);
    for (const name of ["xs", "sm", "md", "lg"]) {
      expect(tailwindConfig).toMatch(
        new RegExp(`\\b${name}:\\s*"\\d+px"`),
      );
    }
    expect(tailwindConfig).not.toMatch(/\b(xl|2xl):\s*"/);
  });

  it("не использует xl/2xl и произвольные медиазапросы в разметке", () => {
    const offenders: string[] = [];
    for (const [file, source] of Object.entries(sources)) {
      if (/\.test\./.test(file)) continue;
      source.split("\n").forEach((line, i) => {
        const match = line.match(UNKNOWN_SCALE) ?? line.match(ARBITRARY_MEDIA);
        if (match) offenders.push(`${file}:${i + 1} — ${match[0]}`);
      });
    }
    expect(offenders).toEqual([]);
  });
});
