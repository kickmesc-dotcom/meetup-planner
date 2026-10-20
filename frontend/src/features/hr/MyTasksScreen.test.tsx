// @vitest-environment jsdom
/**
 * VISUAL_AUDIT P2.12 и P2.13: главный экран смены.
 *
 * Пустое состояние не должно отправлять в «События» — они и так в нижней
 * полосе; оно ведёт к главному делу смены, чек-листу. Имя сотрудника больше
 * не повторяется: приветствие + плашка, без третьей подписи рядом.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MyTasksScreen from "./MyTasksScreen";
import {
  fetchChecklist,
  fetchEmployee,
  fetchTasks,
  type HrEmployee,
} from "@/api/hr";
import { fetchIssues } from "@/api/issues";
import { useUI } from "@/store/ui";

vi.mock("@/api/hr", () => ({
  fetchEmployee: vi.fn(),
  fetchTasks: vi.fn(),
  fetchChecklist: vi.fn(),
  runTaskAction: vi.fn(),
  attachTaskPhoto: vi.fn(),
  reportTaskIssue: vi.fn(),
  TASK_MODE_LABEL: {
    one_of: "один за всех",
    each: "каждый сам",
    parts: "части работы",
  },
}));
vi.mock("@/api/issues", () => ({ fetchIssues: vi.fn() }));
vi.mock("@/api/texts", () => ({
  useAppText: (_key: string, fallback: string) => fallback,
}));
vi.mock("@/tg/webapp", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/tg/webapp")>();
  return {
    ...actual,
    haptic: vi.fn(),
    showAlert: vi.fn().mockResolvedValue(undefined),
  };
});

const employeeMock = vi.mocked(fetchEmployee);
const tasksMock = vi.mocked(fetchTasks);
const checklistMock = vi.mocked(fetchChecklist);
const issuesMock = vi.mocked(fetchIssues);

const EMPLOYEE = {
  id: 1,
  user_id: 1,
  display_name: "Сергей",
  telegram_id: 1,
  department_id: null,
  department_name: null,
  position: null,
  badge: "Управляющий",
  badge_emoji: "🧭",
  role: "admin",
  experience: null,
  onboarding_state: "done",
  learning_mode: false,
  is_aup: true,
  is_admin: true,
  is_staff: true,
  is_active: true,
  is_demo: false,
} as HrEmployee;

function checklist(status: "in_progress" | "done") {
  return {
    run_id: 1,
    template_id: 1,
    template_title: "Открытие — Первый зал",
    kind: "shift",
    shift_date: "2026-10-21",
    status,
    done: status === "done" ? 3 : 1,
    total: 3,
    progress_text: "Выполнено 1 из 3",
    items: [],
    hall_id: 1,
    hall_name: "Первый зал",
    needs_hall: false,
  } as Awaited<ReturnType<typeof fetchChecklist>>;
}

function renderScreen() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MyTasksScreen />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  employeeMock.mockReset();
  tasksMock.mockReset();
  checklistMock.mockReset();
  issuesMock.mockReset();
  employeeMock.mockResolvedValue(EMPLOYEE);
  tasksMock.mockResolvedValue([]);
  checklistMock.mockResolvedValue(checklist("in_progress"));
  issuesMock.mockResolvedValue({
    scope: "all",
    summary: {
      open: 0,
      in_progress: 0,
      resolved: 0,
      cancelled: 0,
      mine_open: 0,
      attention: 0,
      total_open: 0,
    },
    items: [],
  });
});

afterEach(() => {
  cleanup();
  useUI.setState({ tab: "tasks" });
});

describe("MyTasksScreen (P2)", () => {
  it("ведёт из пустого состояния в чек-лист, а не в «События»", async () => {
    renderScreen();

    expect(await screen.findByText("На сегодня всё")).toBeTruthy();
    // Дубля имени нет: только приветствие, плашка рядом.
    expect(screen.getByText("Привет, Сергей")).toBeTruthy();
    expect(screen.queryByText("Сергей")).toBeNull();
    // «События» дублировали нижнюю полосу — кнопки больше нет.
    expect(screen.queryByRole("button", { name: "События" })).toBeNull();

    // Подпись отличается от кнопки в карточке прогресса («Открыть чек-лист»):
    // два одинаковых действия на одном экране — тот же шум, что и повтор имени.
    fireEvent.click(screen.getByRole("button", { name: "Продолжить чек-лист" }));
    expect(useUI.getState().tab).toBe("checklist");
  });

  it("после закрытой смены зовёт посмотреть чек-лист", async () => {
    checklistMock.mockResolvedValue(checklist("done"));
    renderScreen();

    const button = await screen.findByRole("button", {
      name: "Посмотреть чек-лист",
    });
    fireEvent.click(button);
    expect(useUI.getState().tab).toBe("checklist");
    // Секция прогресса тоже честно говорит, что смена закрыта.
    await waitFor(() => expect(screen.getByText("Смена закрыта")).toBeTruthy());
  });
});
