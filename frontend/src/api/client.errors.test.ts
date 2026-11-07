// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { looksLikeCode } from "./client";

/**
 * §8: ошибка должна объяснять путь к решению, а не показывать внутренний код.
 * Экраны со своим словарём спрашивают `looksLikeCode`, прежде чем вывести
 * серверный detail как есть.
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
