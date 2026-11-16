// @vitest-environment jsdom
/**
 * Склад расходников (13.11.2026).
 *
 * Проверяем путь, ради которого экран существует: увидеть остаток, заметить
 * «мало» и списать с комментарием. Приход — только у руководителя.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fetchEmployee } from "@/api/hr";
import {
  fetchSupplies,
  fetchSupplyMovements,
  moveSupply,
  type Supply,
} from "@/api/supplies";
import { useLocale } from "@/i18n";

vi.mock("@/api/hr", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/hr")>();
  return { ...actual, fetchEmployee: vi.fn() };
});
vi.mock("@/api/supplies", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/supplies")>();
  return {
    ...actual,
    fetchSupplies: vi.fn(),
    fetchSupplyMovements: vi.fn(),
    moveSupply: vi.fn(),
  };
});

import SuppliesScreen from "./SuppliesScreen";

const GLOVES: Supply = {
  id: 1,
  name: "Перчатки",
  unit: "пар",
  quantity: 0,
  min_quantity: 2,
  low: true,
  department_id: null,
  department: null,
  updated_at: "2026-11-13T09:00:00Z",
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SuppliesScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useLocale.setState({ locale: "ru" });
  vi.mocked(fetchEmployee).mockResolvedValue({ is_staff: false } as never);
  vi.mocked(fetchSupplies).mockResolvedValue([GLOVES]);
  vi.mocked(fetchSupplyMovements).mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SuppliesScreen", () => {
  it("показывает остаток и помечает «мало»", async () => {
    renderScreen();
    expect(await screen.findByText("Перчатки")).toBeTruthy();
    expect(screen.getByText("мало")).toBeTruthy();
    expect(screen.getByText("Мало на складе: 1")).toBeTruthy();
  });

  it("списывает количество с комментарием", async () => {
    vi.mocked(moveSupply).mockResolvedValue({
      supply: { ...GLOVES, quantity: 0 },
      movement: {
        id: 1,
        kind: "out",
        quantity: 3,
        comment: "Вечерняя смена",
        employee_name: "Борис",
        created_at: "2026-11-13T10:00:00Z",
      },
    });

    renderScreen();
    fireEvent.click(await screen.findByText("Перчатки"));
    fireEvent.click(screen.getByText("Списать"));

    const amount = screen.getByRole("spinbutton");
    fireEvent.change(amount, { target: { value: "3" } });
    fireEvent.change(screen.getByPlaceholderText("Куда или зачем (необязательно)"), {
      target: { value: "Вечерняя смена" },
    });
    fireEvent.click(screen.getAllByText("Списать").at(-1) as HTMLElement);

    await waitFor(() =>
      expect(vi.mocked(moveSupply)).toHaveBeenCalledWith(1, {
        kind: "out",
        quantity: 3,
        comment: "Вечерняя смена",
      }),
    );
  });

  it("не показывает приход сотруднику без прав", async () => {
    renderScreen();
    fireEvent.click(await screen.findByText("Перчатки"));
    expect(screen.queryByText("Приход")).toBeNull();
  });

  it("показывает приход руководителю", async () => {
    vi.mocked(fetchEmployee).mockResolvedValue({ is_staff: true } as never);
    renderScreen();
    fireEvent.click(await screen.findByText("Перчатки"));
    expect(await screen.findByText("Приход")).toBeTruthy();
    expect(screen.getByText("Добавить позицию")).toBeTruthy();
  });
});
