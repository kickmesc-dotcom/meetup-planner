/**
 * Страж узбекского пакета (план, 8.3).
 *
 * Зачем тест. Узбекский — единственный язык, который переведён НЕ полностью, и
 * именно такому языку нужны границы, иначе «частично» быстро станет «кое-как»:
 *
 *  • ключ с опечаткой молча не сработает — на экране останется русский текст,
 *    и никто не заметит (сравнение с EN_CONTENT ловит опечатку сразу);
 *  • забытая кириллица в значении — это русская строка, выданная за перевод;
 *  • потерянный плейсхолдер (`{count}`) даёт текст без числа, который
 *    выглядит правдоподобно — самая неприятная из ошибок перевода;
 *  • число строк не должно уменьшаться: список экранов может только расти.
 *
 * Чего тест НЕ требует: перевести всё. Русский — запасной вариант, и
 * непереведённая строка читается. Поэтому здесь пол, а не потолок.
 */
import { describe, expect, it } from "vitest";
import { EN_CONTENT } from "./content";
import { UZ_CONTENT } from "./content.uz";
import { en, ru, uz } from "./messages";

const CYRILLIC = /[А-Яа-яЁё]/;

/**
 * Сколько строк уже переведено. Число — не цель, а защита от отката: новый
 * экран переводится вместе с экраном, и эта граница поднимается тогда же.
 */
// 29.10.2026: 107 → 166. Закрыт весь экран «Профиль» (скриншот владельца:
// переключатель на UZ, а тело карточки русское) плюс подписи кнопки перевода
// данных из плана 11. Граница поднята вместе с переводом, а не заранее.
const MIN_CONTENT_LINES = 160;

function placeholders(text: string): string[] {
  return [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
}

describe("узбекский словарь интерфейса", () => {
  it("покрывает те же ключи, что русский", () => {
    expect(Object.keys(uz).sort()).toEqual(Object.keys(ru).sort());
  });

  it("не содержит пустых строк", () => {
    const empty = Object.entries(uz)
      .filter(([, value]) => !value.trim())
      .map(([key]) => key);
    expect(empty).toEqual([]);
  });

  it("написан латиницей, а не русским текстом", () => {
    // «Русский» и «English» — названия языков в переключателе, они так и
    // должны остаться: человек ищет свой язык на своём языке.
    const offenders = Object.entries(uz)
      .filter(([key]) => key !== "locale.ru" && !["locale.label"].includes(key))
      .filter(([, value]) => CYRILLIC.test(value))
      .map(([key]) => key);
    expect(offenders).toEqual([]);
  });

  it("сохраняет подстановки русского оригинала", () => {
    for (const [key, value] of Object.entries(ru)) {
      expect({ key, vars: placeholders(uz[key as keyof typeof uz]) }).toEqual({
        key,
        vars: placeholders(value),
      });
    }
  });

  it("английский и узбекский не разъехались по количеству", () => {
    expect(Object.keys(en).length).toBe(Object.keys(uz).length);
  });
});

describe("узбекский словарь экранов", () => {
  it("каждый ключ существует в английском словаре — иначе опечатка", () => {
    const unknown = Object.keys(UZ_CONTENT).filter((key) => !(key in EN_CONTENT));
    expect(unknown).toEqual([]);
  });

  it("не содержит пустых строк", () => {
    const empty = Object.entries(UZ_CONTENT)
      .filter(([, value]) => !value.trim())
      .map(([key]) => key);
    expect(empty).toEqual([]);
  });

  it("не оставляет русских значений", () => {
    const offenders = Object.entries(UZ_CONTENT)
      .filter(([, value]) => CYRILLIC.test(value))
      .map(([key]) => key);
    expect(offenders).toEqual([]);
  });

  it("сохраняет подстановки оригинала", () => {
    for (const [key, value] of Object.entries(UZ_CONTENT)) {
      expect({ key, vars: placeholders(value) }).toEqual({
        key,
        vars: placeholders(key),
      });
    }
  });

  it("не сокращает уже переведённое", () => {
    expect(Object.keys(UZ_CONTENT).length).toBeGreaterThanOrEqual(
      MIN_CONTENT_LINES,
    );
  });
});
