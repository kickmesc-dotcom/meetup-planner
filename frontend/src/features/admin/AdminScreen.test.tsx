// @vitest-environment jsdom
/**
 * VISUAL_AUDIT P1.9: админка — 17 карточек одним списком.
 *
 * Проверяем три обещания:
 *  - поиск фильтрует по названию/подписи и честно говорит, что ничего не нашёл;
 *  - разделы, которые открывали, переезжают в «Частое» (а не дублируются ниже);
 *  - открытие раздела увеличивает счётчик в localStorage, по нему и строится
 *    «Частое» при следующем заходе.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AdminScreen from "./AdminScreen";
import { fetchAdminTasks } from "@/api/hr";
import { fetchIssues } from "@/api/issues";

vi.mock("@/api/hr", () => ({ fetchAdminTasks: vi.fn() }));
vi.mock("@/api/issues", () => ({ fetchIssues: vi.fn() }));
// Подраздел не предмет теста: важно, что переход произошёл.
vi.mock("./AppTextsScreen", () => ({ default: () => <div>тексты-экран</div> }));

const tasksMock = vi.mocked(fetchAdminTasks);
const issuesMock = vi.mocked(fetchIssues);

const USAGE_KEY = "admin.usage.v1";

function renderScreen() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AdminScreen users={[]} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  tasksMock.mockReset();
  issuesMock.mockReset();
  tasksMock.mockResolvedValue([]);
  issuesMock.mockResolvedValue({
    summary: { attention: 0 },
  } as unknown as Awaited<ReturnType<typeof fetchIssues>>);
});
afterEach(cleanup);

describe("AdminScreen (P1.9)", () => {
  it("ищет по названию раздела и убирает остальные", () => {
    renderScreen();

    const search = screen.getByTestId("admin-search") as HTMLInputElement;
    fireEvent.change(search, { target: { value: "чек" } });

    expect(screen.getByText("Чек-листы")).toBeTruthy();
    expect(screen.queryByText("Прокси")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Найдено: 1");
  });

  it("честно сообщает о пустом поиске и сбрасывается", () => {
    renderScreen();

    fireEvent.change(screen.getByTestId("admin-search"), {
      target: { value: "иии" },
    });
    expect(screen.queryByText("Прокси")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Ничего не нашли");

    fireEvent.click(screen.getByText("Сбросить поиск"));
    expect(screen.getByText("Прокси")).toBeTruthy();
  });

  it("поднимает частые разделы вверх без дублей", () => {
    localStorage.setItem(USAGE_KEY, JSON.stringify({ texts: 4 }));
    renderScreen();

    expect(screen.getByText("Частое")).toBeTruthy();
    // Раздел переехал, а не скопировался: одна карточка и нет пустой группы.
    expect(screen.getAllByText("Тексты приложения")).toHaveLength(1);
    expect(screen.queryByText("Тексты")).toBeNull();
  });

  it("запоминает открытый раздел в localStorage", () => {
    renderScreen();

    fireEvent.click(screen.getByText("Тексты приложения"));

    expect(screen.getByText("тексты-экран")).toBeTruthy();
    const stored = JSON.parse(localStorage.getItem(USAGE_KEY) ?? "{}");
    expect(stored.texts).toBe(1);
  });
});
