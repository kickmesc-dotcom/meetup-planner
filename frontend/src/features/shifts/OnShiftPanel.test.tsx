// @vitest-environment jsdom
/**
 * Панель «Сейчас на смене» (13.11.2026).
 *
 * Проверяем то, ради чего она существует: людей группируют по отделам и видно,
 * до скольки каждый. И то, чего быть не должно: пустая панель не занимает
 * место, а ошибка запроса не ломает экран графика.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fetchOnShift, type OnShiftNow } from "@/api/shifts";
import { useLocale } from "@/i18n";

vi.mock("@/api/shifts", () => ({ fetchOnShift: vi.fn() }));

import OnShiftPanel from "./OnShiftPanel";

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <OnShiftPanel />
    </QueryClientProvider>,
  );
}

const NOW: OnShiftNow = {
  now: "2026-11-13T14:00:00+05:00",
  today: "2026-11-13",
  on_shift: 2,
  items: [
    {
      employee_id: 1,
      display_name: "Пётр",
      position: "Официант",
      department_id: 7,
      department_name: "Зал",
      starts_at: "10:00",
      ends_at: "18:00",
      state: "on_shift",
    },
    {
      employee_id: 2,
      display_name: "Анна",
      position: "Повар",
      department_id: 8,
      department_name: "Кухня",
      starts_at: "09:00",
      ends_at: "17:00",
      state: "on_shift",
    },
    {
      employee_id: 3,
      display_name: "Игорь",
      position: "Бармен",
      department_id: 7,
      department_name: "Зал",
      starts_at: "16:00",
      ends_at: "23:00",
      state: "upcoming",
    },
  ],
};

beforeEach(() => {
  useLocale.setState({ locale: "ru" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("OnShiftPanel", () => {
  it("группирует по отделам и показывает время до конца", async () => {
    vi.mocked(fetchOnShift).mockResolvedValue(NOW);

    renderPanel();

    expect(await screen.findByTestId("on-shift-panel")).toBeTruthy();
    expect(screen.getByText("2 в смене")).toBeTruthy();
    expect(screen.getByText("Зал")).toBeTruthy();
    expect(screen.getByText("Кухня")).toBeTruthy();
    // Один отдел — один заголовок, люди внутри него.
    expect(screen.getByText(/Пётр/)).toBeTruthy();
    expect(screen.getByText(/до 18:00/)).toBeTruthy();
    expect(screen.getByText(/Игорь/)).toBeTruthy();
  });

  it("молчит, когда сегодня никто не в графике", async () => {
    vi.mocked(fetchOnShift).mockResolvedValue({ ...NOW, on_shift: 0, items: [] });

    renderPanel();
    await waitFor(() => expect(fetchOnShift).toHaveBeenCalled());
    expect(screen.queryByTestId("on-shift-panel")).toBeNull();
  });

  it("не ломает график при ошибке запроса", async () => {
    vi.mocked(fetchOnShift).mockRejectedValue(new Error("network"));

    renderPanel();
    await waitFor(() => expect(fetchOnShift).toHaveBeenCalled());
    expect(screen.queryByTestId("on-shift-panel")).toBeNull();
  });
});
