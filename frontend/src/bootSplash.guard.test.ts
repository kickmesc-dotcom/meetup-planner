/**
 * Страж заставки первого кадра.
 *
 * Смысл: до того как браузер скачает и разберёт бандл (≈290 kB gzip на мобильном
 * канале), человек не должен видеть пустую белую страницу. В `index.html` лежит
 * статический каркас — имя продукта и блоки будущего экрана, — а `main.tsx` его
 * убирает, когда React готов рисовать.
 *
 * Тест держит три вещи, которые легко потерять при правке разметки:
 *  • заставка есть в собранном HTML (а не только в React-ветке);
 *  • её стили встроены в файл, а не взяты из бандла, — иначе до загрузки CSS
 *    заставка была бы голым текстом;
 *  • она уважает `prefers-reduced-motion` и тёмную тему;
 *  • и её действительно удаляют перед монтированием приложения.
 */
import { describe, expect, it } from "vitest";
import indexHtml from "../index.html?raw";
import mainSource from "./main.tsx?raw";

describe("заставка первого кадра", () => {
  it("встроена в index.html и не требует бандла", () => {
    expect(indexHtml).toContain('id="boot-splash"');
    expect(indexHtml).toContain("SemiTask");
    // Стили — в самом файле: бандл со стилями ещё не пришёл.
    expect(indexHtml).toContain("@media (prefers-color-scheme: dark)");
    expect(indexHtml).toContain("@media (prefers-reduced-motion: reduce)");
    // Внутри #root, иначе React её не заменит и она останется висеть.
    const rootIndex = indexHtml.indexOf('id="root"');
    expect(rootIndex).toBeGreaterThan(-1);
    expect(indexHtml.indexOf('id="boot-splash"')).toBeGreaterThan(rootIndex);
  });

  it("исчезает перед монтированием приложения", () => {
    expect(mainSource).toContain('getElementById("boot-splash")?.remove()');
  });
});
