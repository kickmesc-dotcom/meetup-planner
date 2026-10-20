// @vitest-environment jsdom
/**
 * Поручения из админки: срок задаётся до секунды.
 *
 * Регрессионный тест на конкретную жалобу: «нужен вариант указать своё время
 * дедлайна с точностью до секунд». Проверяем, что введённые секунды не теряются
 * и уходят на сервер в ISO.
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
  createAdminTask,
  fetchAdminEmployees,
  fetchAdminTasks,
  fetchDepartments,
} from "@/api/hr";

vi.mock("@/api/hr", () => ({
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

const createMock = vi.mocked(createAdminTask);

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AdminTasksScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(fetchAdminTasks).mockResolvedValue([]);
  vi.mocked(fetchAdminEmployees).mockResolvedValue([
    {
      id: 5,
      user_id: 5,
      display_name: "Аня",
      telegram_id: 5,
      department_id: 1,
      department_name: "Бар",
      department_emoji: "🍸",
      position: "Бармен",
      badge: null,
      badge_emoji: null,
      role: "employee",
      experience: null,
      onboarding_state: "done",
      is_demo: false,
      is_active: true,
    },
  ]);
  vi.mocked(fetchDepartments).mockResolvedValue([
    { id: 1, name: "Бар", slug: "bar", emoji: "🍸", sort_order: 1 },
  ]);
  createMock.mockReset();
  createMock.mockResolvedValue({} as never);
});
afterEach(cleanup);

describe("AdminTasksScreen: точный дедлайн", () => {
  it("передаёт секунды в ISO и не округляет до минуты", async () => {
    renderScreen();
    // Ждём подразделения: до ответа в `<select>` нет option, и `change` на 1
    // молча сбрасывается в пустую строку — тест падал бы на валидации.
    await screen.findByRole("option", { name: /Бар/ });
    fireEvent.change(screen.getByLabelText(/Что сделать/), {
      target: { value: "Проверить витрину" },
    });
    fireEvent.change(screen.getByLabelText(/Подразделение/), {
      target: { value: "1" },
    });
    fireEvent.change(screen.getByLabelText(/^Дата/), {
      target: { value: "2026-11-01" },
    });
    fireEvent.change(screen.getByLabelText(/^Время/), {
      target: { value: "17:30" },
    });
    fireEvent.change(screen.getByLabelText(/Сек\./), {
      target: { value: "05" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Создать поручение/ }));

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    const body = createMock.mock.calls[0][0];
    expect(body.due_at).toBe(new Date(2026, 10, 1, 17, 30, 5).toISOString());
    expect(body.due_at).toMatch(/:05\.000Z$/);
  });

  it("пустая дата — поручение без срока", async () => {
    renderScreen();
    await screen.findByRole("option", { name: /Бар/ });
    fireEvent.change(screen.getByLabelText(/Что сделать/), {
      target: { value: "Общее" },
    });
    fireEvent.change(screen.getByLabelText(/Подразделение/), {
      target: { value: "1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Создать поручение/ }));
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    expect(createMock.mock.calls[0][0].due_at).toBeNull();
  });
});
