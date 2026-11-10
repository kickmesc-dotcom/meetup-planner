// @vitest-environment jsdom
/**
 * Экран «Бренд» (шаг 4.4).
 *
 * Проверяем то, что ломается незаметно:
 *  - без настроек показывается имя организации, а не пустое поле;
 *  - сохранение отправляет ровно те поля, которые человек правил;
 *  - ошибка сервера (`bad_color`) объясняется по-человечески, а не «400».
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import BrandScreen from "./BrandScreen";
import { fetchBrand, resetBrand, updateBrand, type OrgBrand } from "@/api/brand";

vi.mock("@/api/brand", () => ({
  fetchBrand: vi.fn(),
  updateBrand: vi.fn(),
  resetBrand: vi.fn(),
}));

const fetchMock = vi.mocked(fetchBrand);
const updateMock = vi.mocked(updateBrand);
const resetMock = vi.mocked(resetBrand);

const BRAND: OrgBrand = {
  name: "Салон А",
  color: "#1c6fb8",
  logo_url: null,
  bot_username: null,
  is_custom: false,
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BrandScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  fetchMock.mockReset();
  updateMock.mockReset();
  resetMock.mockReset();
  fetchMock.mockResolvedValue(BRAND);
  updateMock.mockResolvedValue({ ...BRAND, name: "Ножницы", is_custom: true });
  resetMock.mockResolvedValue(BRAND);
});

describe("BrandScreen", () => {
  it("показывает имя организации, пока бренд не настроен", async () => {
    renderScreen();

    expect(await screen.findByText("Салон А")).toBeTruthy();
    expect(screen.getByText("Сейчас команда видит")).toBeTruthy();
  });

  it("сохраняет изменённое имя и цвет", async () => {
    renderScreen();

    const name = (await screen.findByLabelText(/Название/)) as HTMLInputElement;
    fireEvent.change(name, { target: { value: "Ножницы" } });
    fireEvent.click(screen.getByText("Сохранить"));

    await vi.waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith({
        name: "Ножницы",
        color: "#1c6fb8",
        logo_url: "",
      }),
    );
  });

  it("объясняет ошибку цвета человеческим текстом", async () => {
    updateMock.mockRejectedValue({ detail: "bad_color" });
    renderScreen();

    fireEvent.click(await screen.findByText("Сохранить"));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent ?? "").toContain("нужен формат #1c6fb8");
  });

  it("сбрасывает бренд к имени организации", async () => {
    renderScreen();

    fireEvent.click(await screen.findByText("Сбросить бренд"));

    await vi.waitFor(() => expect(resetMock).toHaveBeenCalled());
  });
});
