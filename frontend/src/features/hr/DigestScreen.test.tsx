// @vitest-environment jsdom
/**
 * Экран «Сводка дня» (план, 8.2).
 *
 * Проверяем обещания, которые даёт руководителю утреннее сообщение и его экран:
 *  • заголовок и объяснение видны до ответа сервера (правило раздела 9), числа
 *    занимают плитки;
 *  • спокойное утро говорит словами, а не нулями без объяснения;
 *  • число ведёт туда, где его разбирают: «просрочено» → поручения.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DigestScreen from "./DigestScreen";
import { fetchDigest } from "@/api/hr";
import { useUI } from "@/store/ui";

vi.mock("@/api/hr", () => ({ fetchDigest: vi.fn() }));
vi.mock("@/tg/webapp", () => ({
  haptic: vi.fn(),
  showAlert: vi.fn(),
}));

const digestMock = vi.mocked(fetchDigest);

function renderScreen() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <DigestScreen onBack={() => undefined} />
    </QueryClientProvider>,
  );
}

const CALM = {
  day: "2026-10-27",
  overdue_tasks: 0,
  overdue_titles: [],
  planned_today: 4,
  not_started: 0,
  open_runs: 0,
  problems_open: 0,
  problems_attention: 0,
  calm: true,
};

beforeEach(() => {
  digestMock.mockReset();
});
afterEach(cleanup);

describe("DigestScreen", () => {
  it("пока данных нет, объясняет экран и держит форму плитками", () => {
    digestMock.mockReturnValue(new Promise(() => undefined));
    renderScreen();

    expect(screen.getByText("Сводка дня")).toBeTruthy();
    expect(screen.getByTestId("digest-skeleton")).toBeTruthy();
    expect(screen.queryByText("Всё спокойно")).toBeNull();
  });

  it("спокойное утро говорит словами, а не пустыми числами", async () => {
    digestMock.mockResolvedValue(CALM);
    renderScreen();

    expect(await screen.findByText("Всё спокойно")).toBeTruthy();
    expect(screen.getByText("Просрочено")).toBeTruthy();
  });

  it("показывает числа и заголовки просроченного", async () => {
    digestMock.mockResolvedValue({
      ...CALM,
      calm: false,
      overdue_tasks: 2,
      overdue_titles: ["Проверить витрину", "Сдать отчёт"],
      not_started: 1,
      problems_open: 3,
      problems_attention: 1,
    });
    renderScreen();

    expect(await screen.findByText("Проверить витрину")).toBeTruthy();
    expect(screen.getByText("Сдать отчёт")).toBeTruthy();
    // Число проблем и срочные подписаны отдельно: «3 открыто, 1 срочная».
    expect(screen.getByText("Проблемы")).toBeTruthy();
    expect(screen.getByText("срочных: 1")).toBeTruthy();
    expect(screen.queryByText("Всё спокойно")).toBeNull();
  });

  it("«Открыть поручения» ведёт в задачи, а не в пустоту", async () => {
    digestMock.mockResolvedValue({
      ...CALM,
      calm: false,
      overdue_tasks: 1,
      overdue_titles: ["Проверить витрину"],
    });
    renderScreen();

    const button = await screen.findByRole("button", { name: "Открыть поручения" });
    fireEvent.click(button);

    await waitFor(() => expect(useUI.getState().tab).toBe("tasks"));
  });
});
