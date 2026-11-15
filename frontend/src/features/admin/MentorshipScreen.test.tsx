// @vitest-environment jsdom
/**
 * Первая неделя новичка (13.11.2026).
 *
 * Экран существует ради одного действия — заметить и назначить наставника.
 * Проверяем, что риск виден, а назначение уходит на сервер с правильным id.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fetchTrainees,
  setTraineeMentor,
  type HrTrainee,
} from "@/api/hrMentorship";
import { fetchEmployeesPool, type HrEmployeeCard } from "@/api/hrOps";
import { useLocale } from "@/i18n";

vi.mock("@/api/hrMentorship", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/hrMentorship")>();
  return {
    ...actual,
    fetchTrainees: vi.fn(),
    setTraineeMentor: vi.fn(),
  };
});
vi.mock("@/api/hrOps", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/hrOps")>();
  return { ...actual, fetchEmployeesPool: vi.fn() };
});

import MentorshipScreen from "./MentorshipScreen";

const TRAINEE: HrTrainee = {
  employee_id: 3,
  name: "Вера",
  position: "Официант",
  department_id: 2,
  department: "Зал",
  hired_on: "2026-11-11",
  days_in_team: 2,
  shifts_week: 0,
  overdue_tasks: 1,
  last_seen_at: null,
  mentor_employee_id: null,
  mentor_name: null,
  at_risk: true,
};

const MENTOR = {
  employee_id: 7,
  display_name: "Борис",
  is_demo: false,
} as HrEmployeeCard;

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MentorshipScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useLocale.setState({ locale: "ru" });
  vi.mocked(fetchTrainees).mockResolvedValue({ window_days: 14, items: [TRAINEE] });
  vi.mocked(fetchEmployeesPool).mockResolvedValue({
    items: [MENTOR],
    trash_days: 30,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("MentorshipScreen", () => {
  it("показывает риск и назначает наставника", async () => {
    vi.mocked(setTraineeMentor).mockResolvedValue({
      ...TRAINEE,
      mentor_employee_id: 7,
      mentor_name: "Борис",
    });

    renderScreen();

    expect(await screen.findByText("Вера")).toBeTruthy();
    expect(screen.getByText("внимание")).toBeTruthy();
    expect(screen.getByText("Требуют внимания: 1. Спросите, всё ли в порядке.")).toBeTruthy();

    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "7" } });

    await waitFor(() =>
      expect(vi.mocked(setTraineeMentor)).toHaveBeenCalledWith(3, 7),
    );
  });

  it("объясняет пустой список", async () => {
    vi.mocked(fetchTrainees).mockResolvedValue({ window_days: 14, items: [] });

    renderScreen();

    expect(
      await screen.findByText("За две недели новых сотрудников не было."),
    ).toBeTruthy();
  });
});
