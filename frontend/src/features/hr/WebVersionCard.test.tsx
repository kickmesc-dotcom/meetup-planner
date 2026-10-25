// @vitest-environment jsdom
/**
 * «Веб-версия» в профиле: ссылка показывается один раз, отзыв — по кнопке.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WebVersionCard from "./WebVersionCard";
import * as accessApi from "@/api/access";

// Подпись Telegram есть только в мини-аппе: снаружи карточка скрыта, потому что
// ручка выпуска ссылок отвечает 403 без `initData`.
let initData: string | null = "hash=rehearsal";
vi.mock("@/tg/webapp", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/tg/webapp")>();
  return { ...actual, getInitData: () => initData };
});

function renderCard() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <WebVersionCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  initData = "hash=rehearsal";
  vi.spyOn(accessApi, "fetchAccessLinks").mockResolvedValue([]);
  vi.spyOn(accessApi, "createAccessLink").mockResolvedValue({
    id: 5,
    url: "https://app.example.com/?access=sweb_abc",
    expires_at: "2026-11-21T00:00:00Z",
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("WebVersionCard", () => {
  it("после выпуска показывает ссылку и предупреждает, что она одноразовая", async () => {
    renderCard();
    fireEvent.click(
      await screen.findByRole("button", { name: /Создать ссылку/ }),
    );

    expect(
      await screen.findByText("https://app.example.com/?access=sweb_abc"),
    ).toBeTruthy();
    expect(screen.getByText(/работает как пароль/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Скопировать" })).toBeTruthy();
    expect(accessApi.createAccessLink).toHaveBeenCalledTimes(1);
  });

  it("без выданных ссылок не рисует список", async () => {
    renderCard();
    await screen.findByRole("button", { name: /Создать ссылку/ });
    expect(screen.queryByText("Отозвать")).toBeNull();
  });

  it("вне Telegram карточки нет: ссылку выпускают только из мини-аппа", () => {
    initData = null;
    renderCard();
    expect(screen.queryByTestId("web-version-card")).toBeNull();
    expect(screen.queryByRole("button", { name: /Создать ссылку/ })).toBeNull();
  });
});
