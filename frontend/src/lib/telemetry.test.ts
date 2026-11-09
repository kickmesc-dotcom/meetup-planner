// @vitest-environment jsdom
/**
 * Телеметрия: что именно уходит на сервер и как часто.
 *
 * Проверяем не «fetch вызвался», а обещания, из-за которых модуль и написан:
 * адрес без query, стек без токенов, повторы схлопываются, лимит не даёт
 * устроить поток запросов из цикла перерисовки.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({ getApiBase: () => "https://api.test" }));

import {
  buildReport,
  cleanPath,
  cleanStack,
  installGlobalErrorHandlers,
  reportClientError,
  resetTelemetry,
} from "./telemetry";

const fetchMock = vi.fn();

beforeEach(() => {
  resetTelemetry();
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({ ok: true });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function lastBody(): Record<string, unknown> {
  return JSON.parse(fetchMock.mock.calls.at(-1)?.[1].body as string);
}

describe("чистка данных", () => {
  it("убирает query и якорь из пути", () => {
    expect(cleanPath("/app?access=SECRET#top")).toBe("/app");
    expect(cleanPath("/app")).toBe("/app");
  });

  it("вычищает похожие на токены значения из стека", () => {
    const stack = "at open (https://x.test/app?access=SECRET&token=t0k)";
    expect(cleanStack(stack)).not.toContain("SECRET");
    expect(cleanStack(stack)).not.toContain("t0k");
  });

  it("обрезает слишком длинные поля", () => {
    const report = buildReport("error", new Error("x".repeat(2000)));
    expect(report.message.length).toBe(300);
  });
});

describe("reportClientError", () => {
  it("отправляет отчёт на /api/telemetry с keepalive", () => {
    expect(reportClientError("render", new Error("boom"), "  at Screen")).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.test/api/telemetry");
    expect(init).toMatchObject({ method: "POST", keepalive: true });
    expect(lastBody()).toMatchObject({
      kind: "render",
      message: "boom",
      path: "/",
    });
  });

  it("схлопывает повтор той же ошибки", () => {
    expect(reportClientError("error", new Error("same"))).toBe(true);
    expect(reportClientError("error", new Error("same"))).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("не отправляет больше пяти разных отчётов за сессию", () => {
    for (let i = 0; i < 5; i += 1) {
      expect(reportClientError("error", new Error(`boom-${i}`))).toBe(true);
    }
    expect(reportClientError("error", new Error("boom-6"))).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  it("молчит, если сеть запрещена", () => {
    vi.stubGlobal("fetch", vi.fn(() => {
      throw new TypeError("Failed to fetch");
    }));
    expect(reportClientError("error", new Error("boom"))).toBe(false);
  });
});

describe("глобальные обработчики", () => {
  it("ловят ошибку окна и отклонённый промис", () => {
    installGlobalErrorHandlers();
    const error = new TypeError("Failed to fetch");
    window.dispatchEvent(new ErrorEvent("error", { error, message: error.message }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(lastBody().kind).toBe("error");

    const rejection = new Event("unhandledrejection") as Event & { reason: unknown };
    rejection.reason = new Error("promise failed");
    window.dispatchEvent(rejection);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(lastBody().kind).toBe("rejection");
  });
});
