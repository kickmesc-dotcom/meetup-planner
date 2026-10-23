// @vitest-environment jsdom
/**
 * Ссылка-приглашение: `/invite?token=…`.
 *
 * Правило то же, что у сброса пароля: токен принимается только на своей
 * странице, иначе любой `?token=` открывал бы присоединение к чужой
 * организации.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { clearInviteTokenFromUrl, inviteTokenFromUrl } from "./inviteUrl";

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("inviteTokenFromUrl", () => {
  it("берёт токен со страницы приглашения", () => {
    expect(
      inviteTokenFromUrl("https://app.example/invite?token=abc123"),
    ).toBe("abc123");
  });

  it("прощает косую черту в конце адреса", () => {
    expect(inviteTokenFromUrl("https://app.example/invite/?token=abc123")).toBe(
      "abc123",
    );
  });

  it("не берёт токен с других страниц", () => {
    expect(inviteTokenFromUrl("https://app.example/?token=abc123")).toBeNull();
    expect(
      inviteTokenFromUrl("https://app.example/reset?token=abc123"),
    ).toBeNull();
  });

  it("без токена страница приглашения не открывается", () => {
    expect(inviteTokenFromUrl("https://app.example/invite")).toBeNull();
    expect(inviteTokenFromUrl("https://app.example/invite?token=%20")).toBeNull();
  });

  it("на мусорном адресе не падает", () => {
    expect(inviteTokenFromUrl("not a url")).toBeNull();
  });
});

describe("clearInviteTokenFromUrl", () => {
  it("убирает одноразовую ссылку из адресной строки", () => {
    window.history.replaceState(null, "", "/invite?token=abc123");
    clearInviteTokenFromUrl();
    expect(window.location.pathname).toBe("/");
    expect(window.location.search).toBe("");
  });
});
