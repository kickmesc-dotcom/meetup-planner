/**
 * Страж имени у иконочных кнопок (этап 2, `docs/AAA_ROADMAP.md`).
 *
 * Зачем тест. `Icon` по умолчанию `aria-hidden` — иконка декоративна, потому
 * что рядом всегда должна быть подпись. Пока подпись есть в тексте кнопки,
 * всё в порядке; как только в кнопке остаётся одна иконка, у неё не остаётся
 * доступного имени, и скринридер объявляет «кнопка» без объяснения. Такие
 * кнопки появляются незаметно: разметку правят ради компактности шапки.
 *
 * Что проверяем. Кнопку, внутри которой нет ничего, кроме иконок (или
 * спиннера), обязаны назвать через `aria-label`, `aria-labelledby` или
 * `title`. Любой другой содержимый узел — текст, `{tx(...)}`, `<span>` —
 * считается подписью и проверку проходит: тест намеренно консервативен, чтобы
 * не давать ложных срабатываний на переводах.
 */
import { describe, expect, it } from "vitest";

const sources = import.meta.glob("./**/*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const BUTTON = /<button\b([^>]*)>([\s\S]*?)<\/button>/g;
const ONLY_ICONS =
  /^(?:\s*<(?:Icon|InlineIcon|Spinner)\b[^>]*\/>\s*)+$/;

function hasAccessibleName(attrs: string): boolean {
  return (
    /\baria-label\s*=/.test(attrs) ||
    /\baria-labelledby\s*=/.test(attrs) ||
    /\btitle\s*=/.test(attrs)
  );
}

describe("имя иконочных кнопок", () => {
  it("видит исходники (иначе проверка ниже пустая)", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(100);
  });

  it("кнопка без текста названа для скринридера", () => {
    const offenders: string[] = [];
    let iconButtons = 0;
    for (const [path, raw] of Object.entries(sources)) {
      if (path.includes(".test.")) continue;
      const relative = path.replace(/^\.\//, "");
      if (relative.startsWith("_legacy/")) continue;
      const withoutComments = raw.replace(/\{\/\*[\s\S]*?\*\/\}/g, "");
      for (const match of withoutComments.matchAll(BUTTON)) {
        const [, attrs, inner] = match;
        if (!ONLY_ICONS.test(inner)) continue;
        iconButtons += 1;
        if (hasAccessibleName(attrs)) continue;
        const line = withoutComments.slice(0, match.index ?? 0).split("\n").length;
        offenders.push(`${relative}:${line}`);
      }
    }
    // Проверка не должна зеленеть на пустом множестве: если разбор перестал
    // находить иконочные кнопки, страж бесполезен, и это отдельная ошибка.
    expect(iconButtons).toBeGreaterThan(10);
    expect(offenders).toEqual([]);
  });
});
