// @vitest-environment jsdom
/**
 * 11promt-TEACHER §4.2 и §11.
 *
 * Проверяем два обещания нового кабинета:
 *  - на входе есть ответ «что мне сейчас нужно сделать?», а не только каталог
 *    из 37 карточек;
 *  - простой режим прячет редкие группы, но не запирает их: одна кнопка
 *    возвращает всё, и выбор подробности не сбрасывается между заходами.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AdminScreen from "./AdminScreen";
import { useUI } from "@/store/ui";
import { fetchDashboard, type HrDashboard } from "@/api/hr";

vi.mock("@/api/hr", () => ({ fetchDashboard: vi.fn() }));
// Экраны разделов не предмет теста: важно, что переход произошёл.
vi.mock("./AttentionScreen", () => ({ default: () => <div>внимание-экран</div> }));
vi.mock("./AdminTasksScreen", () => ({ default: () => <div>поручения-экран</div> }));
vi.mock("./InvitationsScreen", () => ({ default: () => <div>приглашения-экран</div> }));

const dashboardMock = vi.mocked(fetchDashboard);

const EMPTY_DASHBOARD: HrDashboard = {
  work_date: "2026-11-07",
  scope: "all",
  departments: [],
  employees: [],
  attention: [],
  activity: [],
  total_employees: 0,
  shifts_started: 0,
  shifts_done: 0,
  tasks_open: 0,
  tasks_overdue: 0,
  open_issues: 0,
};

function renderScreen(platform = true) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AdminScreen users={[]} platform={platform} canManage={false} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  useUI.setState({ adminSection: "root" });
  dashboardMock.mockReset();
  dashboardMock.mockResolvedValue(EMPTY_DASHBOARD);
});
afterEach(cleanup);

describe("AdminScreen: первые шаги и подробность", () => {
  it("предлагает три понятных первых шага вместо выбора из каталога", async () => {
    renderScreen();

    expect(screen.getByTestId("admin-quick-actions")).toBeTruthy();
    expect(screen.getByText("Что будем делать?")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Дать поручение" }));
    expect(await screen.findByText("поручения-экран")).toBeTruthy();
    expect(useUI.getState().adminSection).toBe("admin-tasks");
  });

  it("в простом режиме прячет редкие разделы, но возвращает их кнопкой", () => {
    localStorage.setItem("ux.mode.v1", "simple");
    renderScreen();

    expect(screen.queryByText("Прокси")).toBeNull();
    // Основное осталось на месте: люди и контроль видны сразу.
    expect(screen.getByText("Чек-листы")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Показать все разделы" }));
    expect(screen.getByText("Прокси")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Свернуть лишние разделы" }));
    expect(screen.queryByText("Прокси")).toBeNull();
  });

  it("по умолчанию ничего не скрывает: клиенты уже привыкли к полному списку", () => {
    renderScreen();
    expect(screen.getByText("Прокси")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Показать все разделы" })).toBeNull();
  });

  it("находит раздел по человеческим словам, а не только по старому названию", () => {
    renderScreen();
    fireEvent.change(screen.getByTestId("admin-search"), {
      target: { value: "таблиц" },
    });
    expect(screen.getByText("Загрузить из таблицы")).toBeTruthy();
    expect(screen.queryByText("Запланированные задачи")).toBeNull();
  });
});
