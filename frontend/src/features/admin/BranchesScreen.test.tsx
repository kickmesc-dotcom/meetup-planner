// @vitest-environment jsdom
/**
 * Филиалы сети (06.11.2026).
 *
 * Проверяем то, ради чего экран существует: владелец видит, где он сейчас,
 * может переключиться в другой филиал и завести новый.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import BranchesScreen from "./BranchesScreen";
import {
  createBranch,
  fetchBranchEmployees,
  fetchBranches,
  transferEmployee,
  type Branch,
} from "@/api/orgs";
import { setActiveOrg } from "@/api/client";

vi.mock("@/api/orgs", () => ({
  fetchBranches: vi.fn(),
  createBranch: vi.fn(),
  fetchBranchEmployees: vi.fn(),
  transferEmployee: vi.fn(),
}));
vi.mock("@/api/client", () => ({
  setActiveOrg: vi.fn(),
  humanizeApiError: (error: unknown) => String(error),
}));
vi.mock("./SubScreen", () => ({
  default: ({
    title,
    subtitle,
    children,
  }: {
    title: string;
    subtitle?: string;
    children: React.ReactNode;
  }) => (
    <div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
      {children}
    </div>
  ),
}));

const fetchMock = vi.mocked(fetchBranches);
const createMock = vi.mocked(createBranch);
const employeesMock = vi.mocked(fetchBranchEmployees);
const transferMock = vi.mocked(transferEmployee);
const pickMock = vi.mocked(setActiveOrg);
const reload = vi.fn();

function branch(overrides: Partial<Branch> = {}): Branch {
  return {
    id: 1,
    slug: "salon",
    name: "Салон на Ленина",
    role: "owner",
    is_root: true,
    is_current: false,
    ...overrides,
  };
}

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BranchesScreen onBack={() => undefined} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  createMock.mockReset();
  employeesMock.mockReset();
  transferMock.mockReset();
  pickMock.mockReset();
  reload.mockReset();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { reload },
  });
  fetchMock.mockResolvedValue([
    branch({ id: 1, is_root: true, is_current: true, name: "Салон на Ленина" }),
    branch({ id: 2, is_root: false, name: "Салон Юг" }),
  ]);
  createMock.mockResolvedValue(branch({ id: 3, name: "Салон Север" }));
  employeesMock.mockResolvedValue([
    { id: 10, name: "Анна", position: "Бармен" },
  ]);
  transferMock.mockResolvedValue({
    employee_id: 11,
    from_org_id: 1,
    to_org_id: 2,
    shifts_moved: 3,
  });
});
afterEach(cleanup);

describe("BranchesScreen", () => {
  it("показывает головную организацию и филиалы", async () => {
    renderScreen();

    expect(await screen.findByText("Салон на Ленина")).toBeTruthy();
    // Филиал есть и в списке, и в выборе цели переноса.
    expect(screen.getAllByText("Салон Юг").length).toBeGreaterThan(0);
    expect(screen.getByText("Головная организация · Текущая")).toBeTruthy();
    expect(screen.getByText("Вы здесь")).toBeTruthy();
  });

  it("переключает организацию и перезагружает приложение", async () => {
    renderScreen();

    const buttons = await screen.findAllByRole("button", { name: "Переключиться" });
    fireEvent.click(buttons[0]);

    expect(pickMock).toHaveBeenCalledWith(2);
    expect(reload).toHaveBeenCalled();
  });

  it("создаёт филиал по названию", async () => {
    renderScreen();

    fireEvent.change(await screen.findByPlaceholderText("Название филиала"), {
      target: { value: "Салон Север" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));

    await waitFor(() => expect(createMock).toHaveBeenCalledWith("Салон Север"));
  });

  it("показывает ошибку создания у поля, а не только тостом", async () => {
    createMock.mockRejectedValueOnce("Такое название уже занято");
    renderScreen();

    const input = await screen.findByPlaceholderText("Название филиала");
    fireEvent.change(input, { target: { value: "Салон Юг" } });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Такое название уже занято");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")).toContain(
      "branch-name-error",
    );
  });

  it("переводит сотрудника в выбранный филиал", async () => {
    renderScreen();

    fireEvent.change(await screen.findByLabelText("Кто переезжает"), {
      target: { value: "10" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Перевести" }));

    await waitFor(() =>
      expect(transferMock).toHaveBeenCalledWith({
        employee_id: 10,
        target_org_id: 2,
        move_shifts: true,
      }),
    );
  });
});
