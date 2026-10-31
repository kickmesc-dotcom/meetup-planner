// @vitest-environment jsdom
/**
 * Страж набора иконок (решение владельца, 31.10.2026).
 *
 * Требование звучит так: в интерфейсе только проверенные open-source SVG с
 * лицензией, разрешающей коммерческое использование, одна библиотека на весь
 * проект, сетка 24×24, тонкий контур, без эмодзи вместо иконок.
 *
 * Тест ловит три способа это правило потерять:
 *
 * 1. **Иконка не рисуется.** `IconName` мог расшириться, а соответствие в
 *    `ICONS` — забыться; TypeScript это поймает только при явном `Record`,
 *    поэтому проверяем фактический SVG: `viewBox`, `aria-hidden`, толщину.
 * 2. **В проект вернулся самодельный SVG.** Один нарисованный вручную значок
 *    рядом с Iconoir выглядит почти так же, но с другой сеткой — и именно так
 *    набор начинает «дрожать». Разрешён ровно один файл: `Icon.tsx`.
 * 3. **Пропало лицензионное уведомление.** MIT требует сохранять текст
 *    лицензии при распространении; без файла уведомлений проект формально
 *    нарушает условия библиотеки.
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Icon, { ICON_NAMES } from "./Icon";
import notices from "../../THIRD_PARTY_NOTICES.md?raw";

// Исходники читаем через Vite (`?raw`), а не `node:fs`: у фронтенда нет
// `@types/node` (так же устроены `emoji.guard.test.ts` и `pwa.test.ts`).
const sources = import.meta.glob("../**/*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("набор иконок: Iconoir, сетка 24×24", () => {
  it("содержит все имена, которые использует интерфейс", () => {
    // Порог, а не точное число: добавление иконки не должно ломать тест,
    // а массовая потеря набора — должна.
    expect(ICON_NAMES.length).toBeGreaterThanOrEqual(45);
  });

  it.each(ICON_NAMES)("«%s» рисует контурную иконку 24×24", (name) => {
    const { container } = render(<Icon name={name} />);
    const svg = container.querySelector("svg");

    expect(svg, `иконка «${name}» не отрисовалась`).not.toBeNull();
    expect(svg!.getAttribute("viewBox")).toBe("0 0 24 24");
    // Декоративная: рядом всегда есть текст или aria-label у кнопки.
    expect(svg!.getAttribute("aria-hidden")).toBe("true");
    // Толщина линии одна на весь набор — иначе иконки в одном ряду «жирнеют».
    expect(svg!.getAttribute("stroke-width")).toBe("1.8");
    expect(svg!.querySelectorAll("path, circle, rect").length).toBeGreaterThan(0);
  });

  it("масштабируется размером, а не классами", () => {
    const { container } = render(<Icon name="check" size={13} />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("width")).toBe("13");
    expect(svg.getAttribute("height")).toBe("13");
  });
});

describe("набор иконок: одна библиотека на проект", () => {
  const withSvg = Object.keys(sources)
    .filter((file) => sources[file].includes("<svg"))
    .sort();

  it("самодельных SVG нет нигде, кроме Icon.tsx", () => {
    // `_legacy` — выключенные экраны старого интерфейса: они не попадают в
    // сборку, и переписывать в них иконки значит править мёртвый код.
    // Пути здесь относительные (`./Icon.tsx`), поэтому сравниваем по имени.
    const offenders = withSvg.filter(
      (file) => !/(^|\/)Icon\.tsx$/.test(file) && !file.includes("/_legacy/"),
    );
    expect(
      offenders,
      "иконки берутся из Iconoir через <Icon>; свой SVG в экране даст другую сетку",
    ).toEqual([]);
  });

  it("никакие иконки не тянутся из другой библиотеки", () => {
    const others = Object.entries(sources)
      .filter(([, src]) =>
        /from\s+["'](?:@?phosphor|@tabler|@iconoir\+|react-icons)/.test(src),
      )
      .map(([file]) => file);
    expect(others, "основной набор — iconoir-react, смешивать нельзя").toEqual(
      [],
    );
  });
});

describe("набор иконок: лицензия", () => {
  it("уведомление об MIT для Iconoir сохранено", () => {
    expect(notices).toContain("Iconoir");
    expect(notices).toMatch(/MIT License/);
    expect(notices).toMatch(/Copyright \(c\) 2021 Daniel Martin/);
  });

  it("SF Symbols явно исключены из веб-версии", () => {
    // Требование владельца: лицензия Apple не покрывает веб-приложение.
    expect(notices).toContain("SF Symbols");
  });
});
