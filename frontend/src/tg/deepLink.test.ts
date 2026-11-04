// @vitest-environment jsdom
/**
 * Диплинк из уведомления (MOBILE_PARALLEL, M3).
 *
 * Один разбор на три места: серверная ссылка, `postMessage` из service worker
 * и адрес при запуске. Проверяем то, что ломается незаметно: мусор в `task`
 * не открывает пустой экран, неизвестный раздел не подставляется, а после
 * применения адрес очищается — иначе повторный запуск снова уводит в задачу.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  clearDeepLink,
  deepLinkFromLocation,
  parseDeepLink,
} from "./deepLink";

describe("parseDeepLink", () => {
  it("ведёт к задачам по номеру поручения", () => {
    expect(parseDeepLink("/?task=42")).toEqual({ tab: "tasks", taskId: 42 });
  });

  it("понимает полный адрес от service worker", () => {
    expect(parseDeepLink("https://semitaskbot.pages.dev/?task=7")).toEqual({
      tab: "tasks",
      taskId: 7,
    });
  });

  it("открывает известный раздел", () => {
    expect(parseDeepLink("/?open=checklist")).toEqual({
      tab: "checklist",
      taskId: null,
    });
  });

  it("не открывает неизвестный раздел и мусор вместо номера", () => {
    expect(parseDeepLink("/?open=secret")).toBeNull();
    expect(parseDeepLink("/?task=abc")).toBeNull();
    expect(parseDeepLink("/")).toBeNull();
  });
});

describe("адрес окна", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("читает ссылку из location", () => {
    window.history.replaceState({}, "", "/?task=5");
    expect(deepLinkFromLocation()).toEqual({ tab: "tasks", taskId: 5 });
  });

  it("очищает параметры после применения", () => {
    window.history.replaceState({}, "", "/?task=5");
    clearDeepLink();
    expect(window.location.search).toBe("");
    expect(deepLinkFromLocation()).toBeNull();
  });
});
