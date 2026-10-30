// @vitest-environment jsdom
/**
 * Установленный режим (M2, `docs/MOBILE_PARALLEL.md`).
 *
 * Тест держит два правила, которые иначе тихо ломаются при правках:
 *  • браузер на компьютере — не приложение: подсказка там не показывается,
 *    и полноэкранный режим (F11) за приложение не считается;
 *  • подсказка показывается один раз и не возвращается после «Понятно».
 */
import { afterEach, describe, expect, it } from "vitest";
import {
  isStandalone,
  markStandaloneHintSeen,
  shouldShowStandaloneHint,
} from "./standalone";

type FakeMediaQuery = {
  matches: boolean;
  media: string;
  onchange: null;
  addListener: () => void;
  removeListener: () => void;
  addEventListener: () => void;
  removeEventListener: () => void;
  dispatchEvent: () => boolean;
};

/** Подменяет `matchMedia`: совпадение только у запрошенных режимов. */
function mockDisplayMode(matching: string[]): void {
  window.matchMedia = ((query: string) => {
    const result: FakeMediaQuery = {
      matches: matching.includes(query),
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    };
    return result;
  }) as unknown as typeof window.matchMedia;
}

/** iOS Safari: `navigator.standalone`, медиазапросов нет вовсе. */
function mockIosStandalone(value: boolean): void {
  Object.defineProperty(window.navigator, "standalone", {
    configurable: true,
    value,
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (window as any).matchMedia;
}

afterEach(() => {
  localStorage.clear();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (window as any).matchMedia;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (window.navigator as any).standalone;
});

describe("isStandalone", () => {
  it("обычная вкладка браузера — не приложение", () => {
    mockDisplayMode([]);
    expect(isStandalone()).toBe(false);
  });

  it("домашний экран Android: display-mode standalone", () => {
    mockDisplayMode(["(display-mode: standalone)"]);
    expect(isStandalone()).toBe(true);
  });

  it("iOS: navigator.standalone без поддержки matchMedia", () => {
    mockIosStandalone(true);
    expect(isStandalone()).toBe(true);
  });

  it("полноэкранный режим на компьютере (F11) приложением не считается", () => {
    mockDisplayMode(["(display-mode: fullscreen)"]);
    expect(isStandalone()).toBe(false);
  });
});

describe("подсказка о режиме приложения", () => {
  it("в браузере не показывается никогда", () => {
    mockDisplayMode([]);
    expect(shouldShowStandaloneHint()).toBe(false);
  });

  it("в приложении показывается один раз", () => {
    mockDisplayMode(["(display-mode: standalone)"]);
    expect(shouldShowStandaloneHint()).toBe(true);

    markStandaloneHintSeen();

    expect(shouldShowStandaloneHint()).toBe(false);
  });

  it("стоимость: отметка не зависит от режима запуска", () => {
    // Человек открыл приложение, вошёл и закрыл. Отметка уже стоит, поэтому
    // в следующий запуск подсказки нет — но вход остаётся приложением.
    mockDisplayMode(["(display-mode: standalone)"]);
    markStandaloneHintSeen();
    expect(shouldShowStandaloneHint()).toBe(false);
    expect(isStandalone()).toBe(true);
  });
});
