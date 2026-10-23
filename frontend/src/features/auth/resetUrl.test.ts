// @vitest-environment jsdom
/**
 * Ссылка сброса пароля: `/reset?token=…`.
 *
 * Правило, которое защищает этот тест: токен принимается ТОЛЬКО на странице
 * сброса. Иначе любой `?token=` (например, из чужой ссылки на главную) открывал
 * бы форму смены пароля, и человек вводил бы туда новый пароль по чужой указке.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { clearResetTokenFromUrl, resetTokenFromUrl } from "./resetUrl";

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("resetTokenFromUrl", () => {
  it("берёт токен со страницы сброса", () => {
    expect(
      resetTokenFromUrl("https://app.example/reset?token=abc123"),
    ).toBe("abc123");
  });

  it("прощает косую черту в конце адреса", () => {
    expect(resetTokenFromUrl("https://app.example/reset/?token=abc123")).toBe(
      "abc123",
    );
  });

  it("не берёт токен с других страниц", () => {
    expect(resetTokenFromUrl("https://app.example/?token=abc123")).toBeNull();
    expect(
      resetTokenFromUrl("https://app.example/profile?token=abc123"),
    ).toBeNull();
  });

  it("без токена страница сброса не открывается", () => {
    expect(resetTokenFromUrl("https://app.example/reset")).toBeNull();
    expect(resetTokenFromUrl("https://app.example/reset?token=%20")).toBeNull();
  });

  it("на мусорном адресе не падает", () => {
    expect(resetTokenFromUrl("not a url")).toBeNull();
  });
});

describe("clearResetTokenFromUrl", () => {
  it("убирает одноразовую ссылку из адресной строки", () => {
    window.history.replaceState(null, "", "/reset?token=abc123");
    clearResetTokenFromUrl();
    expect(window.location.pathname).toBe("/");
    expect(window.location.search).toBe("");
  });
});
