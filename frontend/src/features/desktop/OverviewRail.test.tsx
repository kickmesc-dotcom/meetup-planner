// @vitest-environment jsdom
/**
 * Рельс сводки на широком экране.
 *
 * Числа обязаны совпадать с правилами «Моих задач»: `on_review` — ещё открытая
 * работа (ждёт приёмки), а не закрытая.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import OverviewRail from "./OverviewRail";
import * as hrApi from "@/api/hr";
import * as issuesApi from "@/api/issues";
import { useUI } from "@/store/ui";

const baseTask = {
  id: 1,
  title: "Поручение",
  description: null,
  expected_result: null,
  scope: "employee" as const,
  department_id: null,
  assignee_employee_id: null,
  due_at: null,
  priority: "normal" as const,
  requires_photo: false,
  comment: null,
  status: "new" as const,
  created_by_employee_id: null,
  created_at: "2026-10-22T09:00:00Z",
  done_at: null,
  is_overdue: false,
  mode: "each" as const,
  shift_date: null,
  requires_review: false,
  my_status: "new" as const,
  my_part: null,
  progress_done: 0,
  progress_total: 1,
};

function renderRail() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <OverviewRail />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.spyOn(hrApi, "fetchChecklist").mockResolvedValue({
    run_id: 1,
    template_id: 1,
    template_title: "Открытие",
    kind: "shift",
    shift_date: "2026-10-22",
    status: "in_progress",
    done: 3,
    total: 7,
    progress_text: "Выполнено 3 из 7",
    items: [],
    needs_hall: false,
    hall_id: 1,
    hall_name: "Первый зал",
  });
  vi.spyOn(hrApi, "fetchTasks").mockResolvedValue([
    baseTask,
    { ...baseTask, id: 2, status: "on_review", my_status: "on_review" },
    { ...baseTask, id: 3, status: "overdue", my_status: "overdue", is_overdue: true },
    { ...baseTask, id: 4, status: "done", my_status: "done" },
  ]);
  vi.spyOn(issuesApi, "fetchIssues").mockResolvedValue({
    scope: "all",
    summary: {
      open: 2,
      in_progress: 0,
      resolved: 0,
      cancelled: 0,
      mine_open: 0,
      attention: 1,
      total_open: 2,
    },
    items: [],
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useUI.setState({ tab: "feed" });
});

describe("OverviewRail", () => {
  it("показывает прогресс смены, поручения и проблемы", async () => {
    renderRail();

    expect(await screen.findByText("3/7")).toBeTruthy();

    const tasksCard = (await screen.findByText("Поручения")).closest("section")!;
    expect(within(tasksCard).getByText("3")).toBeTruthy(); // new + on_review + overdue
    expect(within(tasksCard).getByText("1")).toBeTruthy(); // просрочено

    const issuesCard = screen.getByText("Проблемы").closest("section")!;
    expect(within(issuesCard).getByText("2")).toBeTruthy();
    expect(within(issuesCard).getByText("1")).toBeTruthy();
  });

  it("ведет в чек-лист и задачи по кнопкам", async () => {
    renderRail();
    const link = await screen.findByRole("button", { name: "Мои задачи" });
    link.click();
    expect(useUI.getState().tab).toBe("tasks");
  });
});
