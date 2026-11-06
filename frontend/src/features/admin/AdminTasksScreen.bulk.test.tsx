// @vitest-environment jsdom
/**
 * Массовое закрытие поручений: итог числами.
 *
 * Регрессия на смысл пункта: «готово» на пачке из четырнадцати поручений ничего
 * не говорит, если два не закрылись. Проверяем, что выбранные id уходят одной
 * ручкой и человек видит «Отмечено 2 из 2», а при отказе — ещё и число отказов.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AdminTasksScreen from "./AdminTasksScreen";
import {
  closeAdminTasksBulk,
  fetchAdminEmployees,
  fetchAdminTasks,
  fetchDepartments,
  type HrAdminTask,
} from "@/api/hr";
import { showAlert } from "@/tg/webapp";

vi.mock("@/api/hr", () => ({
  closeAdminTasksBulk: vi.fn(),
  createAdminTask: vi.fn(),
  fetchAdminEmployees: vi.fn(),
  fetchAdminTasks: vi.fn(),
  fetchDepartments: vi.fn(),
  setAdminTaskStatus: vi.fn(),
}));

vi.mock("@/tg/webapp", () => ({
  haptic: vi.fn(),
  showAlert: vi.fn(),
  showConfirm: vi.fn(async () => true),
}));

const bulkMock = vi.mocked(closeAdminTasksBulk);
const alertMock = vi.mocked(showAlert);

function task(id: number, title: string): HrAdminTask {
  return {
    id,
    title,
    scope: "employee",
    department_id: null,
    assignee_employee_id: 5,
    due_at: null,
    priority: "normal",
    requires_photo: false,
    status: "new",
    created_by_employee_id: 9,
    created_at: "2026-11-06T09:00:00Z",
    done_at: null,
    is_overdue: false,
    assignee_ids: [5],
    mode: "one_of",
    shift_date: null,
    requires_review: false,
    progress_done: 0,
    progress_total: 1,
    assignments: [],
    photos: [],
    weekdays: null,
    schedule_label: "",
  };
}

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AdminTasksScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(fetchAdminEmployees).mockResolvedValue([]);
  vi.mocked(fetchDepartments).mockResolvedValue([]);
  vi.mocked(fetchAdminTasks).mockResolvedValue([
    task(1, "Сменить фильтр"),
    task(2, "Проверить сроки"),
  ]);
  bulkMock.mockReset();
  alertMock.mockReset();
});

afterEach(cleanup);

describe("AdminTasksScreen: закрыть пачкой", () => {
  it("отправляет выбранные поручения одной ручкой и показывает числа", async () => {
    bulkMock.mockResolvedValue({ requested: 2, closed: 2, failed: [] });
    renderScreen();

    fireEvent.click(
      await screen.findByRole("checkbox", { name: "Выбрать «Сменить фильтр»" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Выбрать «Проверить сроки»" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Зачесть выбранные" }));

    await waitFor(() => expect(bulkMock).toHaveBeenCalledTimes(1));
    expect(bulkMock).toHaveBeenCalledWith({ task_ids: [1, 2] });
    await waitFor(() =>
      expect(alertMock).toHaveBeenCalledWith("Отмечено 2 из 2"),
    );
  });

  it("договаривает, сколько не закрылось", async () => {
    bulkMock.mockResolvedValue({
      requested: 2,
      closed: 1,
      failed: [{ task_id: 2, reason: "bad_transition:done->done" }],
    });
    renderScreen();

    fireEvent.click(
      await screen.findByRole("checkbox", { name: "Выбрать «Сменить фильтр»" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Выбрать «Проверить сроки»" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Зачесть выбранные" }));

    await waitFor(() =>
      expect(alertMock).toHaveBeenCalledWith(
        "Отмечено 1 из 2 · не удалось: 1",
      ),
    );
  });
});
