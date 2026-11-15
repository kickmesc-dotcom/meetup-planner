// @vitest-environment jsdom
/**
 * Плашка стоп-листа над лентой (13.11.2026).
 *
 * Она отвечает на вопрос официанта «что сегодня нельзя заказать» без похода в
 * меню. Проверяем три вещи: пустой стоп-лист не занимает места, длинный список
 * не растягивает шапку на пол-экрана, а названия действительно видны.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fetchMenu, type Menu, type MenuItem } from "@/api/menu";
import { useLocale } from "@/i18n";

vi.mock("@/api/menu", () => ({ fetchMenu: vi.fn() }));

import StopListBanner from "./StopListBanner";

function item(id: number, name: string, isAvailable: boolean): MenuItem {
  return {
    id,
    name,
    category: "Горячее",
    description: null,
    price_rub: 300,
    is_available: isAvailable,
    sort_order: id,
    updated_at: null,
  };
}

function renderBanner() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <StopListBanner />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useLocale.setState({ locale: "ru" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("StopListBanner", () => {
  it("молчит, когда стоп-листа нет", async () => {
    const menu: Menu = {
      items: [item(1, "Борщ", true)],
      categories: ["Горячее"],
      stopped: 0,
    };
    vi.mocked(fetchMenu).mockResolvedValue(menu);

    renderBanner();
    // Дождаться ответа и убедиться, что плашки всё равно нет.
    await waitFor(() => expect(fetchMenu).toHaveBeenCalled());
    expect(screen.queryByTestId("stop-list-banner")).toBeNull();
  });

  it("не роняет ленту на неожиданном ответе", async () => {
    // Так ответил мок e2e до правки: пустой список вместо объекта. Плашка
    // должна промолчать, а не утянуть экран в ErrorBoundary.
    vi.mocked(fetchMenu).mockResolvedValue([] as unknown as Menu);

    renderBanner();
    await waitFor(() => expect(fetchMenu).toHaveBeenCalled());
    expect(screen.queryByTestId("stop-list-banner")).toBeNull();
  });

  it("показывает названия и сворачивает хвост", async () => {
    const menu: Menu = {
      items: [
        item(1, "Борщ", true),
        item(2, "Рыба", false),
        item(3, "Стейк", false),
        item(4, "Пицца", false),
        item(5, "Паста", false),
      ],
      categories: ["Горячее"],
      stopped: 4,
    };
    vi.mocked(fetchMenu).mockResolvedValue(menu);

    renderBanner();

    expect(await screen.findByTestId("stop-list-banner")).toBeTruthy();
    expect(screen.getByText(/Рыба, Стейк, Пицца/)).toBeTruthy();
    // Четвёртое название не перечисляем: шапка не должна расти вместе с меню.
    expect(screen.getByText(/и ещё 1/)).toBeTruthy();
    expect(screen.queryByText(/Паста/)).toBeNull();
    // Доступное блюдо в стоп-лист не попадает.
    expect(screen.queryByText(/Борщ/)).toBeNull();
  });
});
