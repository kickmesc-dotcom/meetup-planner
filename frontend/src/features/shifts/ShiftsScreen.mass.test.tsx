// @vitest-environment jsdom
/**
 * Табель: кнопка «Шаблон недели» и то, что она реально отправляет.
 *
 * Лист проверен отдельно; здесь — связка: кнопка видна только тому, кто может
 * править, открывает лист, а «Применить» уходит в массовую ручку именно с теми
 * людьми и датами, которые выбраны, и показывает результат числами.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ShiftsScreen from "./ShiftsScreen";
import { addDays, mondayOf, toIso } from "./shiftDates";
import {
  bulkSaveShifts,
  clearShiftCells,
  copyShiftWeek,
  fetchShiftWeek,
  type ShiftWeek,
} from "@/api/shifts";

vi.mock("@/api/shifts", () => ({
  fetchShiftWeek: vi.fn(),
  saveShift: vi.fn(),
  moveShift: vi.fn(),
  deleteShift: vi.fn(),
  bulkSaveShifts: vi.fn(),
  copyShiftWeek: vi.fn(),
  clearShiftCells: vi.fn(),
}));

const showAlert = vi.fn().mockResolvedValue(undefined);
const showConfirm = vi.fn().mockResolvedValue(true);
vi.mock("@/tg/webapp", () => ({
  haptic: vi.fn(),
  showAlert: (...args: unknown[]) => showAlert(...args),
  showConfirm: (...args: unknown[]) => showConfirm(...args),
}));

const weekMock = vi.mocked(fetchShiftWeek);
const bulkMock = vi.mocked(bulkSaveShifts);
const copyMock = vi.mocked(copyShiftWeek);
const clearMock = vi.mocked(clearShiftCells);

// Экран открывается на текущей неделе, поэтому ожидания считаются от неё, а
// не от захардкоженной даты: тест не должен ломаться на следующей неделе.
const MONDAY = mondayOf(new Date());
const MONDAY_ISO = toIso(MONDAY);
const PREV_MONDAY_ISO = toIso(addDays(MONDAY, -7));

function week(canEdit: boolean): ShiftWeek {
  return {
    start: MONDAY_ISO,
    end: toIso(addDays(MONDAY, 6)),
    today: MONDAY_ISO,
    can_edit: canEdit,
    statuses: [
      { value: "planned", label: "Запланирована", short: "П" },
      { value: "worked", label: "Отработана", short: "О" },
    ],
    departments: [],
    people: [
      {
        employee_id: 5,
        display_name: "Алина",
        position: "Официант",
        department_id: 1,
        department_name: "Зал",
      },
    ],
    shifts: [],
  };
}

function renderScreen() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ShiftsScreen />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  weekMock.mockReset();
  bulkMock.mockReset();
  copyMock.mockReset();
  clearMock.mockReset();
  showAlert.mockClear();
  showConfirm.mockClear();
  bulkMock.mockResolvedValue({ saved: 2, skipped: 1 });
  copyMock.mockResolvedValue({ saved: 3, skipped: 0 });
  clearMock.mockResolvedValue({ removed: 1 });
});

afterEach(cleanup);

describe("ShiftsScreen: массовое планирование", () => {
  it("не показывает шаблон сотруднику без прав", async () => {
    weekMock.mockResolvedValue(week(false));
    renderScreen();

    await screen.findByText("Алина");
    expect(
      screen.queryByRole("button", {
        name: /Шаблон недели и массовые правки/,
      }),
    ).toBeNull();
  });

  it("открывает лист и отправляет выбранные дни в массовую ручку", async () => {
    weekMock.mockResolvedValue(week(true));
    renderScreen();

    fireEvent.click(
      await screen.findByRole("button", {
        name: /Шаблон недели и массовые правки/,
      }),
    );
    expect(screen.getByRole("dialog", { name: "Шаблон недели" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Пн" }));
    fireEvent.click(screen.getByRole("button", { name: /Применить/ }));

    await waitFor(() => expect(bulkMock).toHaveBeenCalledTimes(1));
    expect(bulkMock).toHaveBeenCalledWith({
      employee_ids: [5],
      days: [MONDAY_ISO],
      status: "planned",
      starts_at: null,
      ends_at: null,
      note: null,
      overwrite: false,
    });

    // Результат показывается числами, а не «готово»: менеджер должен видеть,
    // сколько клеток осталось занятым.
    await waitFor(() =>
      expect(showAlert).toHaveBeenCalledWith("Записано смен: 2 · пропущено занятых: 1"),
    );
  });

  it("копирует прошлую неделю с тем же выбором людей", async () => {
    weekMock.mockResolvedValue(week(true));
    renderScreen();

    fireEvent.click(
      await screen.findByRole("button", {
        name: /Шаблон недели и массовые правки/,
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Ср" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Скопировать прошлую неделю" }),
    );

    await waitFor(() => expect(copyMock).toHaveBeenCalledTimes(1));
    expect(copyMock).toHaveBeenCalledWith({
      from_start: PREV_MONDAY_ISO,
      to_start: MONDAY_ISO,
      employee_ids: [5],
    });
  });
});
