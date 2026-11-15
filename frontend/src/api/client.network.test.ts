// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

// `client.ts` тянет Telegram WebApp SDK, который на импорте трогает `window`.
// Заглушка та же, что в соседних тестах `api/client.*`: самим SDK здесь нечего
// проверять, а сетевую ветку разбора ошибок — есть что.
vi.mock("@/tg/webapp", () => ({
  getInitData: vi.fn(() => ""),
  getSessionToken: vi.fn(() => null),
  clearSessionToken: vi.fn(),
  getAccessToken: vi.fn(() => null),
  clearAccessToken: vi.fn(),
}));

import { ApiError, api, humanizeApiError, isNetworkError } from "./client";

/**
 * Страж текста ошибки. Причина: обрыв связи приходил в `humanizeApiError`
 * обычным `TypeError` и печатался текстом движка — «Failed to fetch» в Chrome,
 * «Load failed» в Safari. Для человека это английская строка без действия.
 */
function setOnline(value: boolean) {
  Object.defineProperty(navigator, "onLine", {
    configurable: true,
    get: () => value,
  });
}

afterEach(() => {
  setOnline(true);
  vi.unstubAllGlobals();
});

describe("isNetworkError", () => {
  it("узнаёт обрыв связи по тексту разных движков", () => {
    expect(isNetworkError(new TypeError("Failed to fetch"))).toBe(true);
    expect(isNetworkError(new TypeError("Load failed"))).toBe(true);
    expect(isNetworkError(new TypeError("NetworkError when attempting"))).toBe(true);
  });

  it("не считает сетевой ошибкой отказ сервера", () => {
    expect(isNetworkError(new ApiError(503, "unavailable"))).toBe(false);
    expect(isNetworkError(new ApiError(400, "photo_required"))).toBe(false);
    expect(isNetworkError(null)).toBe(false);
  });

  it("без сети считает сетевой любую ошибку", () => {
    setOnline(false);
    expect(isNetworkError(new ApiError(500, "boom"))).toBe(true);
  });
});

describe("api: медленный ответ", () => {
  it("обрывает зависший запрос по таймауту", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            const error = new Error("aborted");
            error.name = "AbortError";
            reject(error);
          });
        }),
      ),
    );

    await expect(
      api("/slow", {}, { timeoutMs: 10 }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("humanizeApiError про связь", () => {
  it("не печатает английский текст движка", () => {
    const text = humanizeApiError(new TypeError("Failed to fetch"));
    expect(text).toContain("Нет связи");
    expect(text).not.toContain("Failed to fetch");
  });

  it("Safari получает тот же понятный текст", () => {
    expect(humanizeApiError(new TypeError("Load failed"))).toContain("Нет связи");
  });

  it("отличает таймаут от отсутствия сети", () => {
    const abort = new Error("aborted");
    abort.name = "AbortError";
    expect(humanizeApiError(abort)).toContain("не ответил вовремя");
  });

  it("без сети говорит про интернет, а не про сервер", () => {
    setOnline(false);
    const text = humanizeApiError(new TypeError("Failed to fetch"));
    expect(text).toContain("Нет интернета");
  });

  it("отказ сервера при живой сети остаётся отказом сервера", () => {
    expect(humanizeApiError(new ApiError(503, "unavailable"))).toContain(
      "Сервис временно недоступен",
    );
  });
});

/**
 * Страж отмены. Причина: `api()` умел принимать `AbortSignal`, но при его
 * передаче отключал собственный таймаут — запрос, который человек «отменил»,
 * всё равно мог висеть вечно, если отмена до `fetch` не дошла. Здесь две
 * вещи сразу: чужой сигнал действительно обрывает запрос и таймаут продолжает
 * работать даже вместе с сигналом.
 */
describe("api: отмена устаревших запросов", () => {
  function hangingFetch() {
    const signals: AbortSignal[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          const signal = init?.signal;
          if (!signal) return;
          signals.push(signal);
          signal.addEventListener("abort", () => {
            const error = new Error("aborted");
            error.name = "AbortError";
            reject(error);
          });
        }),
      ),
    );
    return signals;
  }

  it("обрывает запрос по сигналу вызывающего", async () => {
    const signals = hangingFetch();
    const controller = new AbortController();
    const pending = api("/api/feed", { signal: controller.signal });
    await Promise.resolve();

    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(signals[0]?.aborted).toBe(true);
  });

  it("не отключает таймаут, когда сигнал уже передан", async () => {
    hangingFetch();
    const controller = new AbortController();

    await expect(
      api("/api/feed", { signal: controller.signal }, { timeoutMs: 10 }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});
