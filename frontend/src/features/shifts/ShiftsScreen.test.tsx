// @vitest-environment jsdom
/**
 * Табель смен: сетка отдела и правка клетки.
 *
 * Проверяем главное: пустая клетка открывает редактор, статус уходит на сервер
 * вместе с часами, а сотруднику без прав показывают read-only объяснение.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ShiftsScreen from "./ShiftsScreen";
import {
  deleteShift,
  fetchShiftWeek,
  moveShift,
  saveShift,
  type ShiftWeek,
} from "@/api/shifts";

vi.mock("@/api/shifts", () => ({
  fetchShiftWeek: vi.fn(),
  saveShift: vi.fn(),
  moveShift: vi.fn(),
  deleteShift: vi.fn(),
}));

const fetchMock = vi.mocked(fetchShiftWeek);
const saveMock = vi.mocked(saveShift);
const moveMock = vi.mocked(moveShift);
const deleteMock = vi.mocked(deleteShift);

function week(canEdit: boolean): ShiftWeek {
  return {
    start: "2026-10-19",
    end: "2026-10-25",
    today: "2026-10-19",
    can_edit: canEdit,
    statuses: [
      { value: "planned", label: "Запланирована", short: "П" },
      { value: "worked", label: "Отработана", short: "Р" },
      { value: "sick", label: "Больничный", short: "Б" },
      { value: "absent", label: "Не пришёл", short: "Н" },
      { value: "dayoff", label: "Выходной", short: "В" },
      { value: "vacation", label: "Отпуск", short: "О" },
    ],
    departments: [{ id: 1, name: "Кухня" }],
    people: [
      {
        employee_id: 5,
        display_name: "Иван Тестов",
        position: "Повар",
        department_id: 1,
        department_name: "Кухня",
      },
    ],
    shifts: [],
  };
}

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ShiftsScreen />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  saveMock.mockReset();
  moveMock.mockReset();
  deleteMock.mockReset();
  saveMock.mockResolvedValue({
    id: 1,
    employee_id: 5,
    day: "2026-10-19",
    status: "sick",
    status_label: "Больничный",
    short: "Б",
    starts_at: null,
    ends_at: null,
    note: null,
    moved_from: null,
    is_training: false,
  });
});
afterEach(cleanup);

describe("ShiftsScreen", () => {
  it("показывает сотрудников отдела и пустые клетки", async () => {
    fetchMock.mockResolvedValue(week(true));
    renderScreen();
    expect(await screen.findByText("Иван Тестов")).toBeTruthy();
    expect(screen.getAllByTitle("Смены нет").length).toBe(7);
  });

  it("сохраняет статус из редактора клетки", async () => {
    fetchMock.mockResolvedValue(week(true));
    renderScreen();
    await screen.findByText("Иван Тестов");
    fireEvent.click(screen.getAllByTitle("Смены нет")[0]);
    fireEvent.click(await screen.findByText("Больничный"));
    fireEvent.click(screen.getByText(/Сохранить/));
    await waitFor(() =>
      expect(saveMock).toHaveBeenCalledWith(
        5,
        expect.any(String),
        expect.objectContaining({ status: "sick" }),
      ),
    );
  });

  it("сотруднику без прав показывает read-only режим", async () => {
    fetchMock.mockResolvedValue(week(false));
    renderScreen();
    await screen.findByText("Иван Тестов");
    fireEvent.click(screen.getAllByTitle("Смены нет")[0]);
    expect(
      await screen.findByText("Править табель может руководитель подразделения."),
    ).toBeTruthy();
    expect(screen.queryByText(/Сохранить/)).toBeNull();
  });
});
