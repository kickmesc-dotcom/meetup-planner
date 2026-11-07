// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { ApiError, humanizeApiError, looksLikeCode } from "./client";

/**
 * §8: ошибка должна объяснять путь к решению, а не показывать внутренний код.
 *
 * Проверяем два уровня. `looksLikeCode` — точечный страж для экранов со своим
 * словарём. `humanizeApiError` — общий путь: даже если экран не знает кода,
 * человек не должен увидеть `unknown_something_42`.
 */
describe("looksLikeCode", () => {
  it("узнаёт технический код", () => {
    expect(looksLikeCode("org_not_found")).toBe(true);
    expect(looksLikeCode("already_in_branch")).toBe(true);
    expect(looksLikeCode(" domain_taken ")).toBe(true);
  });

  it("не принимает человеческую фразу", () => {
    expect(looksLikeCode("Нет связи с сервером. Проверь интернет.")).toBe(false);
    expect(looksLikeCode("")).toBe(false);
    expect(looksLikeCode("Org not found")).toBe(false);
  });
});

describe("humanizeApiError", () => {
  it("переводит известный серверный код", () => {
    expect(humanizeApiError(new ApiError(401, "invalid_credentials"))).toBe(
      "Неверная почта или пароль.",
    );
  });

  it("не отдаёт человеку неизвестный код", () => {
    expect(humanizeApiError(new ApiError(400, "some_unknown_code"))).toBe(
      "Не получилось. Попробуем ещё раз?",
    );
  });

  it("человеческую фразу с сервера оставляет как есть", () => {
    const phrase = "Нет связи с сервером. Проверь интернет.";
    expect(humanizeApiError(new ApiError(400, phrase))).toBe(phrase);
  });
});
