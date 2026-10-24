// @vitest-environment jsdom
/**
 * Дашборд подразделения: состав, статусы и граница видимости.
 *
 * Проверяем ровно то, что можно сломать незаметно:
 *  • сотрудник видит коллег и статусы (смена, чек-лист, поручения);
 *  • личная отметка «последний вход» показывается только когда сервер
 *    разрешил (`show_presence`), а не потому что поле пришло;
 *  • тап по человеку открывает карточку, а не «ничего».
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DepartmentScreen from "./DepartmentScreen";
import {
  fetchDepartmentOverview,
  fetchEmployeeCard,
  type DepartmentOverview,
} from "@/api/hr";

vi.mock("@/api/hr", () => ({
  fetchDepartmentOverview: vi.fn(),
  fetchEmployeeCard: vi.fn(),
}));

const overviewMock = vi.mocked(fetchDepartmentOverview);
const cardMock = vi.mocked(fetchEmployeeCard);

function view(overrides: Partial<DepartmentOverview> = {}): DepartmentOverview {
  return {
    department_id: 7,
    department_name: "Кухня",
    department_emoji: "👨‍🍳",
    can_manage: true,
    show_presence: true,
    on_shift: 1,
    overdue: 1,
    people: [
      {
        employee_id: 1,
        display_name: "Пётр",
        badge: "Су-шеф",
        badge_emoji: "🍳",
        position: "Су-шеф",
        role: "employee",
        is_demo: false,
        is_self: false,
        shift_status: "worked",
        checklist_done: 3,
        checklist_total: 8,
        tasks_open: 2,
        tasks_overdue: 1,
        last_seen_at: new Date(Date.now() - 5 * 60_000).toISOString(),
        profile_public: true,
      },
      {
        employee_id: 2,
        display_name: "Алина",
        badge: null,
        badge_emoji: null,
        position: null,
        role: "employee",
        is_demo: false,
        is_self: true,
        shift_status: null,
        checklist_done: 0,
        checklist_total: 0,
        tasks_open: 0,
        tasks_overdue: 0,
        last_seen_at: null,
        profile_public: true,
      },
    ],
    ...overrides,
  };
}

function renderScreen(data: DepartmentOverview = view()) {
  overviewMock.mockResolvedValue(data);
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <DepartmentScreen departmentId={data.department_id} onClose={() => {}} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("DepartmentScreen", () => {
  it("показывает состав отдела, чек-лист и просрочку", async () => {
    renderScreen();

    expect(await screen.findByText("Пётр")).toBeTruthy();
    expect(screen.getByText("Алина")).toBeTruthy();
    expect(screen.getByText("Смена закрыта")).toBeTruthy();
    expect(screen.getByText("Чек-лист 3/8")).toBeTruthy();
    expect(screen.getByText(/просрочено 1/)).toBeTruthy();
    expect(screen.getByText("ты")).toBeTruthy();
  });

  it("показывает последний вход, когда сервер разрешил", async () => {
    renderScreen();
    expect(await screen.findByText(/Вход: 5 мин назад/)).toBeTruthy();
  });

  it("сотруднику без права наблюдения время входа не показывается", async () => {
    renderScreen(view({ can_manage: false, show_presence: false }));
    expect(await screen.findByText("Пётр")).toBeTruthy();
    expect(screen.queryByText(/Вход:/)).toBeNull();
  });

  it("тап по человеку открывает карточку", async () => {
    cardMock.mockResolvedValue({
      employee_id: 1,
      display_name: "Пётр",
      department_id: 7,
      department_name: "Кухня",
      position: "Су-шеф",
      badge: "Су-шеф",
      badge_emoji: "🍳",
      role: "employee",
      role_label: "Сотрудник",
      is_demo: false,
      is_self: false,
      can_manage: true,
      profile_open: true,
      can_view: true,
      show_last_seen: true,
      show_last_media: true,
      can_toggle_last_seen: true,
      can_toggle_last_media: true,
      last_seen_at: null,
      last_media: null,
      xp: 0,
      rank_title: "Стажёр",
      rank_emoji: "🌱",
      week_xp: 0,
      week_place: null,
      week_total: 0,
      checklist_items: 3,
      tasks_done: 0,
      shifts_done: 1,
      activity: [],
    });
    renderScreen();

    fireEvent.click(await screen.findByText("Пётр"));
    expect(await screen.findByText("Опыт")).toBeTruthy();
  });
});
