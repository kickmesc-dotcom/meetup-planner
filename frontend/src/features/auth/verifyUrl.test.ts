// @vitest-environment jsdom
/**
 * Ссылка подтверждения почты: `/verify?token=…`.
 *
 * Правило то же, что у сброса пароля: токен принимается ТОЛЬКО на странице
 * подтверждения. Иначе случайный `?token=` на любой странице запускал бы
 * подтверждение адреса — и человек подтверждал бы чужую почту.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { clearVerifyTokenFromUrl, verifyTokenFromUrl } from "./verifyUrl";

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("verifyTokenFromUrl", () => {
  it("берёт токен со страницы подтверждения", () => {
    expect(verifyTokenFromUrl("https://app.example/verify?token=abc123")).toBe(
      "abc123",
    );
  });

  it("прощает косую черту в конце адреса", () => {
    expect(verifyTokenFromUrl("https://app.example/verify/?token=abc123")).toBe(
      "abc123",
    );
  });

  it("не берёт токен с других страниц", () => {
    expect(verifyTokenFromUrl("https://app.example/?token=abc123")).toBeNull();
    expect(verifyTokenFromUrl("https://app.example/reset?token=abc123")).toBeNull();
  });

  it("без токена страница не открывается", () => {
    expect(verifyTokenFromUrl("https://app.example/verify")).toBeNull();
    expect(verifyTokenFromUrl("https://app.example/verify?token=%20")).toBeNull();
  });

  it("на мусорном адресе не падает", () => {
    expect(verifyTokenFromUrl("not a url")).toBeNull();
  });
});

describe("clearVerifyTokenFromUrl", () => {
  it("убирает одноразовую ссылку из адресной строки", () => {
    window.history.replaceState(null, "", "/verify?token=abc123");
    clearVerifyTokenFromUrl();
    expect(window.location.pathname).toBe("/");
    expect(window.location.search).toBe("");
  });
});
