// @vitest-environment jsdom
/**
 * Недельная сводка «что мешало смене» (13.11.2026).
 *
 * Экран отвечает не на «как прошла смена», а на «что повторяется», поэтому
 * проверяем три слоя: числа, категории и конкретные проблемы с возрастом.
 * Отдельно — пустая неделя: она должна объяснять себя, а не показывать ноль
 * без слов.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fetchWeekSummary, type HrWeekSummary } from "@/api/hr";
import { useLocale } from "@/i18n";

vi.mock("@/api/hr", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/hr")>();
  return { ...actual, fetchWeekSummary: vi.fn() };
});

import WeekSummaryScreen from "./WeekSummaryScreen";

const DATA: HrWeekSummary = {
  start: "2026-11-07",
  end: "2026-11-13",
  issues_new: 7,
  issues_closed: 5,
  issues_open: 3,
  tasks_done: 12,
  tasks_done_late: 2,
  tasks_overdue_open: 1,
  categories: [
    { category: "equipment", count: 4 },
    { category: "guest", count: 2 },
  ],
  blockers: [
    {
      issue_id: 1,
      title: "Течёт кран",
      category: "equipment",
      status: "open",
      created_at: "2026-11-12T10:00:00+05:00",
      resolved_at: null,
      age_hours: 30,
    },
    {
      issue_id: 2,
      title: "Гость ждал счёт",
      category: "guest",
      status: "resolved",
      created_at: "2026-11-08T10:00:00+05:00",
      resolved_at: "2026-11-08T12:00:00+05:00",
      age_hours: 2,
    },
  ],
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <WeekSummaryScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useLocale.setState({ locale: "ru" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("WeekSummaryScreen", () => {
  it("показывает числа, категории и проблемы с возрастом", async () => {
    vi.mocked(fetchWeekSummary).mockResolvedValue(DATA);

    renderScreen();

    // Ждём именно данные: заголовок статичен и найдётся и без ответа.
    expect(await screen.findByText("Чаще всего мешало")).toBeTruthy();
    expect(screen.getByText("7")).toBeTruthy(); // новые проблемы
    expect(screen.getByText("3")).toBeTruthy(); // открыто сейчас
    expect(screen.getByText("Чаще всего мешало")).toBeTruthy();
    expect(screen.getByText("Оборудование")).toBeTruthy();
    expect(screen.getByText("Гость")).toBeTruthy();
    expect(screen.getByText("Течёт кран")).toBeTruthy();
    // Открытая проблема показывает, сколько висит; закрытая — что закрыта.
    expect(screen.getByText(/висит 30 ч/)).toBeTruthy();
    expect(screen.getByText(/закрыта/)).toBeTruthy();
    expect(
      screen.getByText("Сделано поручений: 12, из них с опозданием — 2."),
    ).toBeTruthy();
  });

  it("объясняет пустую неделю, а не рисует пустоту", async () => {
    vi.mocked(fetchWeekSummary).mockResolvedValue({
      ...DATA,
      issues_new: 0,
      issues_closed: 0,
      issues_open: 0,
      categories: [],
      blockers: [],
    });

    renderScreen();

    expect(
      await screen.findByText("За неделю проблем не заводили — хороший знак."),
    ).toBeTruthy();
    expect(screen.queryByText("Чаще всего мешало")).toBeNull();
  });
});
