// @vitest-environment jsdom
/**
 * Лента восстанавливает вчерашний срез фильтров.
 *
 * Руководитель смотрит один и тот же отдел и те же типы событий каждый день;
 * без сохранения он каждое утро заново открывал лист фильтра и ставил те же
 * галочки, а до этого смотрел на всю ленту. Здесь проверяем, что сохранённый
 * срез уходит в запрос сразу, а «Сбросить фильтры» его вычищает.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import HrFeedScreen from "./HrFeedScreen";
import {
  fetchDepartmentOverview,
  fetchDepartments,
  fetchEmployee,
  fetchEmployeeCard,
  fetchFeedFilters,
  fetchHrFeed,
  type HrEmployee,
} from "@/api/hr";
import { useLocale } from "@/i18n";

vi.mock("@/api/hr", () => ({
  fetchHrFeed: vi.fn(),
  fetchFeedFilters: vi.fn(),
  fetchEmployeeCard: vi.fn(),
  fetchEmployee: vi.fn(),
  fetchDepartments: vi.fn(),
  fetchDepartmentOverview: vi.fn(),
  countOpenTasks: vi.fn(() => 0),
}));

vi.mock("@/api/kudos", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/kudos")>();
  return {
    ...actual,
    fetchKudosWeek: vi.fn().mockResolvedValue({
      since: "2026-10-26",
      until: "2026-11-01",
      top: [],
      received: 0,
      given: 0,
      my_place: null,
      today_left: 5,
      max_per_day: 5,
      can_thank: 0,
    }),
    fetchKudosPeople: vi.fn().mockResolvedValue([]),
  };
});

const feedMock = vi.mocked(fetchHrFeed);
const filtersMock = vi.mocked(fetchFeedFilters);
const meMock = vi.mocked(fetchEmployee);

function renderFeed() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <HrFeedScreen />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useLocale.setState({ locale: "ru" });
  window.localStorage.clear();
  meMock.mockResolvedValue({ id: 1 } as unknown as HrEmployee);
  feedMock.mockResolvedValue({ scope: "all", can_filter: true, items: [] });
  filtersMock.mockResolvedValue({
    scope: "all",
    can_filter: true,
    departments: [
      { id: 2, name: "Бар", slug: "bar", emoji: null, sort_order: 0 },
    ],
    employees: [
      { id: 5, department_id: 2, display_name: "Аня", position: null, badge: null },
    ],
    kinds: ["task_status", "kudos"],
  } as unknown as Awaited<ReturnType<typeof fetchFeedFilters>>);
  vi.mocked(fetchDepartments).mockResolvedValue([]);
  vi.mocked(fetchEmployeeCard).mockResolvedValue({} as never);
  vi.mocked(fetchDepartmentOverview).mockResolvedValue({} as never);
});

afterEach(cleanup);

describe("HrFeedScreen: сохранённые фильтры", () => {
  it("сразу подставляет вчерашний срез в запрос", async () => {
    window.localStorage.setItem(
      "semitask.feed.filters.v1:1",
      JSON.stringify({ employeeId: 5, departmentId: 2, kinds: ["task_status"] }),
    );
    renderFeed();

    await waitFor(() =>
      expect(feedMock).toHaveBeenCalledWith(
        expect.objectContaining({
          employeeId: 5,
          departmentId: 2,
          kinds: ["task_status"],
        }),
      ),
    );
  });

  it("«Сбросить фильтры» очищает и запрос, и хранилище", async () => {
    window.localStorage.setItem(
      "semitask.feed.filters.v1:1",
      JSON.stringify({ employeeId: 5, departmentId: 2, kinds: ["task_status"] }),
    );
    renderFeed();

    fireEvent.click(await screen.findByText("Сбросить фильтры"));

    await waitFor(() =>
      expect(feedMock).toHaveBeenCalledWith(
        expect.objectContaining({
          employeeId: null,
          departmentId: null,
          kinds: undefined,
        }),
      ),
    );
    await waitFor(() => {
      const stored = JSON.parse(
        window.localStorage.getItem("semitask.feed.filters.v1:1") ?? "{}",
      );
      expect(stored).toEqual({ employeeId: null, departmentId: null, kinds: [] });
    });
  });
});
