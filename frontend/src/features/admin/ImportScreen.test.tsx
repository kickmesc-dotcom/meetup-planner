// @vitest-environment jsdom
/**
 * Экран импорта (шаг 6.3).
 *
 * Проверяем порядок, который и есть суть экрана: сначала разбор, потом запись.
 * «Импортировать» недоступно, пока нет предпросмотра, — иначе кнопка стирала бы
 * смены вслепую.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ImportScreen from "./ImportScreen";
import { applyImport, previewImport } from "@/api/imports";

vi.mock("@/api/imports", () => ({
  previewImport: vi.fn(),
  applyImport: vi.fn(),
  sampleCsv: () => "имя;должность\nАнна;Официант",
}));
vi.mock("@/tg/webapp", () => ({
  haptic: vi.fn(),
  showAlert: vi.fn(),
}));

const previewMock = vi.mocked(previewImport);
const applyMock = vi.mocked(applyImport);

const PREVIEW = {
  kind: "people" as const,
  delimiter: ";",
  total: 2,
  create: 1,
  update: 0,
  skip: 1,
  error: 0,
  departments: ["Зал"],
  rows: [
    { row: 2, action: "create", name: "Анна Смирнова", detail: "", errors: [] },
    { row: 3, action: "skip", name: "Борис Петров", detail: "Уже в пуле сотрудников", errors: [] },
  ],
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ImportScreen onBack={() => undefined} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  previewMock.mockReset();
  applyMock.mockReset();
  previewMock.mockResolvedValue(PREVIEW);
  applyMock.mockResolvedValue({
    kind: "people",
    created: 1,
    updated: 0,
    skipped: 1,
    errors: 0,
    rows: PREVIEW.rows,
  });
});
afterEach(cleanup);

describe("ImportScreen", () => {
  it("без предпросмотра импорт недоступен", () => {
    renderScreen();
    const button = screen.getByTestId("import-apply") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("разбирает вставленный текст и показывает, что будет записано", async () => {
    renderScreen();
    fireEvent.change(screen.getByTestId("import-text"), {
      target: { value: "имя;должность\nАнна;Официант" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Проверить" }));

    expect(await screen.findByTestId("import-preview")).toBeTruthy();
    expect(screen.getByText("Анна Смирнова")).toBeTruthy();
    expect(screen.getByText("Уже в пуле сотрудников")).toBeTruthy();
    expect(previewMock).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "people", text: expect.stringContaining("Анна") }),
    );
    // Записывать пока нечего: предпросмотр — это чтение, а не импорт.
    expect(applyMock).not.toHaveBeenCalled();
  });

  it("после подтверждения показывает итог и не пишет второй раз", async () => {
    renderScreen();
    fireEvent.change(screen.getByTestId("import-text"), {
      target: { value: "имя\nАнна" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Проверить" }));
    await screen.findByTestId("import-preview");

    fireEvent.click(screen.getByTestId("import-apply"));

    expect(await screen.findByTestId("import-result")).toBeTruthy();
    expect(applyMock).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.getByText(/Создано: 1/)).toBeTruthy(),
    );
  });

  it("переключение на график меняет подсказку и сбрасывает разбор", async () => {
    renderScreen();
    fireEvent.change(screen.getByTestId("import-text"), {
      target: { value: "имя\nАнна" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Проверить" }));
    await screen.findByTestId("import-preview");

    fireEvent.click(screen.getByRole("tab", { name: "График" }));

    expect(screen.queryByTestId("import-preview")).toBeNull();
    expect(screen.getByText(/Люди должны быть заведены заранее/)).toBeTruthy();
  });
});
