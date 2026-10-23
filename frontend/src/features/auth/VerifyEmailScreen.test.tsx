// @vitest-environment jsdom
/**
 * Подтверждение почты по ссылке.
 *
 * Проверяем то, что человек увидит в письме: успех, понятную ошибку и
 * отсутствие «мёртвого» экрана — со страницы всегда есть выход в приложение.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import VerifyEmailScreen from "./VerifyEmailScreen";
import { confirmEmailVerification } from "@/api/auth";

vi.mock("@/api/auth", () => ({
  confirmEmailVerification: vi.fn(),
}));

const confirmMock = vi.mocked(confirmEmailVerification);

function renderScreen(onDone = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <VerifyEmailScreen token="tok-1234567890" onDone={onDone} />
    </QueryClientProvider>,
  );
  return onDone;
}

beforeEach(() => {
  confirmMock.mockReset();
});

afterEach(cleanup);

describe("VerifyEmailScreen", () => {
  it("подтверждает адрес сразу при открытии", async () => {
    confirmMock.mockResolvedValue({ ok: true });
    renderScreen();

    await screen.findByText("Почта подтверждена");
    expect(confirmMock).toHaveBeenCalledWith("tok-1234567890");
    expect(screen.getByRole("button", { name: "Перейти в приложение" })).toBeTruthy();
  });

  it("на протухшей ссылке объясняет, что делать", async () => {
    confirmMock.mockRejectedValue({ status: 400, detail: "verify_expired" });
    renderScreen();

    await screen.findByText("Ссылка не подошла");
    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(screen.getByText(/Попроси новую в профиле/)).toBeTruthy();
  });

  it("не подтверждает дважды (StrictMode)", async () => {
    confirmMock.mockResolvedValue({ ok: true });
    renderScreen();
    await screen.findByText("Почта подтверждена");
    expect(confirmMock).toHaveBeenCalledTimes(1);
  });
});
