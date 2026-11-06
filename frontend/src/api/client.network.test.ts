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

import { ApiError, humanizeApiError, isNetworkError } from "./client";

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
