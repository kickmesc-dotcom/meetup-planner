// @vitest-environment jsdom
/**
 * Правка меню смены в кабинете (02.11.2026).
 *
 * Что здесь важно и почему именно это:
 *  - «убрать» — это скрытие, а не удаление: позиция остаётся в базе, и запрос
 *    уходит частичный (`is_available: false`), чтобы заодно не переписать цену;
 *  - цена вводится как текст, но уходит числом: пустое поле — это «по
 *    запросу», а не ноль рублей;
 *  - в списке видно «нет в наличии»: руководитель должен понимать, что позиция
 *    не исчезла, а спрятана.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMenuItem,
  deleteMenuItem,
  fetchMenu,
  updateMenuItem,
  type Menu,
} from "@/api/menu";

vi.mock("@/api/menu", () => ({
  fetchMenu: vi.fn(),
  createMenuItem: vi.fn(),
  updateMenuItem: vi.fn(),
  deleteMenuItem: vi.fn(),
}));

vi.mock("@/tg/webapp", () => ({
  haptic: vi.fn(),
  showAlert: vi.fn(() => Promise.resolve()),
  showConfirm: vi.fn(() => Promise.resolve(true)),
}));

import MenuScreen from "./MenuScreen";

const MENU: Menu = {
  items: [
    {
      id: 1,
      name: "Борщ",
      category: "Супы",
      description: "с пампушкой",
      price_rub: 320,
      is_available: true,
      sort_order: 0,
      updated_at: null,
    },
    {
      id: 2,
      name: "Рыба дня",
      category: "Горячее",
      description: null,
      price_rub: null,
      is_available: false,
      sort_order: 0,
      updated_at: null,
    },
  ],
  categories: ["Супы", "Горячее"],
  hidden: 1,
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MenuScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(fetchMenu).mockResolvedValue(MENU);
  vi.mocked(updateMenuItem).mockResolvedValue({
    ...MENU.items[0],
    is_available: false,
  });
  vi.mocked(createMenuItem).mockResolvedValue(MENU.items[0]);
  vi.mocked(deleteMenuItem).mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("MenuScreen", () => {
  it("показывает группы, цены и скрытые позиции", async () => {
    renderScreen();

    await screen.findByText("Супы");
    expect(screen.getByText("Борщ")).toBeTruthy();
    expect(screen.getByText("320 ₽")).toBeTruthy();
    // Пустая цена — «по запросу», а не «0 ₽».
    expect(screen.getByText("по запросу")).toBeTruthy();
    // Скрытая позиция остаётся в списке с пометкой: она не удалена.
    expect(screen.getByText("нет в наличии")).toBeTruthy();
    expect(screen.getByText("Скрыто позиций: 1")).toBeTruthy();
  });

  it("прячет позицию частичной правкой, а не удалением", async () => {
    renderScreen();
    await screen.findByText("Борщ");

    fireEvent.click(screen.getAllByText("Убрать")[0]);

    await waitFor(() =>
      expect(updateMenuItem).toHaveBeenCalledWith(1, { is_available: false }),
    );
    // Удаления не было: строка остаётся доступной для возврата.
    expect(deleteMenuItem).not.toHaveBeenCalled();
  });

  it("добавляет позицию с ценой числом", async () => {
    renderScreen();
    await screen.findByText("Борщ");

    fireEvent.click(screen.getByText("+ Добавить позицию"));
    fireEvent.change(screen.getByPlaceholderText("Например: Борщ с пампушкой"), {
      target: { value: "Сырники" },
    });
    fireEvent.change(screen.getByLabelText(/Цена/), {
      target: { value: "390" },
    });
    fireEvent.click(screen.getByText("Сохранить"));

    await waitFor(() =>
      expect(createMenuItem).toHaveBeenCalledWith({
        name: "Сырники",
        category: undefined,
        price_rub: 390,
        description: null,
      }),
    );
  });
});
