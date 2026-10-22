// @vitest-environment jsdom
/**
 * «Веб-версия» в профиле: ссылка показывается один раз, отзыв — по кнопке.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WebVersionCard from "./WebVersionCard";
import * as accessApi from "@/api/access";

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
});
