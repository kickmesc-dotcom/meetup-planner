// @vitest-environment jsdom
/**
 * Стандарт целиком на своём языке (план, 11.5).
 *
 * Инструкцию и тест пишет руководитель по-русски — это данные, кодом их не
 * перевести. Проверяем, что в узбекском интерфейсе у стандарта **одна** кнопка
 * перевода и что она переводит и тело инструкции, и вопрос теста с вариантами
 * одним запросом: кнопка у каждого варианта ответа превратила бы тест в стену
 * иконок.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import StandardsScreen from "./StandardsScreen";
import {
  fetchEmployee,
  fetchStandard,
  fetchStandards,
  type HrEmployee,
} from "@/api/hr";
import * as translateApi from "@/api/translate";
import { __clearTranslateCache } from "@/components/translateCore";
import { useLocale } from "@/i18n";

vi.mock("@/api/hr", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/hr")>();
  return {
    ...actual,
    fetchStandards: vi.fn(),
    fetchStandard: vi.fn(),
    fetchEmployee: vi.fn(),
  };
});

const listMock = vi.mocked(fetchStandards);
const detailMock = vi.mocked(fetchStandard);
const meMock = vi.mocked(fetchEmployee);

const STANDARD = {
  id: 7,
  title: "Мытьё рук перед сменой",
  emoji: "🧼",
  category: "safety" as const,
  summary: null,
  department_id: null,
  department_name: null,
  pass_percent: 80,
  is_required: true,
  is_active: true,
  questions_count: 1,
  passed: false,
  last_percent: null,
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <StandardsScreen />
    </QueryClientProvider>,
  );
}

/** Открыть стандарт из списка: экран двухшаговый. */
async function openStandard() {
  renderScreen();
  fireEvent.click(await screen.findByText(/Мытьё рук перед сменой/));
  return screen.findByText(/Тщательно вымыть руки с мылом/);
}

beforeEach(() => {
  __clearTranslateCache();
  useLocale.setState({ locale: "uz", uzPackAvailable: true });
  listMock.mockReset();
  listMock.mockResolvedValue({ items: [STANDARD], passed: 0, total: 1, attempts: 0 });
  detailMock.mockReset();
  detailMock.mockResolvedValue({
    ...STANDARD,
    body: "Тщательно вымыть руки с мылом не меньше 30 секунд.",
    questions: [
      {
        id: 1,
        text: "Сколько секунд мыть руки?",
        options: ["10 секунд", "30 секунд"],
      },
    ],
  });
  meMock.mockReset();
  meMock.mockResolvedValue({ id: 1 } as unknown as HrEmployee);
});

afterEach(() => {
  cleanup();
  useLocale.setState({ locale: "ru" });
});

describe("StandardDetail и перевод", () => {
  it("одна кнопка переводит инструкцию и тест одним запросом", async () => {
    const spy = vi
      .spyOn(translateApi, "translateTexts")
      .mockImplementation(async (batch, target) => ({
        target,
        available: true,
        reason: null,
        items: batch.map((t) => ({ translated: `[${t}]`, provider: "small100" })),
      }));

    await openStandard();
    expect(screen.getAllByTestId("translate-block")).toHaveLength(1);

    fireEvent.click(screen.getByTestId("translate-block"));

    // Вопрос выводится вместе с номером («1. …»), поэтому ищем подстроку.
    expect(
      await screen.findByText(/\[Сколько секунд мыть руки\?\]/),
    ).toBeTruthy();
    expect(
      screen.getByText("[Тщательно вымыть руки с мылом не меньше 30 секунд.]"),
    ).toBeTruthy();
    expect(screen.getByText("[30 секунд]")).toBeTruthy();
    expect(spy).toHaveBeenCalledTimes(1);

    // Повторное нажатие возвращает оригинал: по нему человек отчитывается.
    fireEvent.click(screen.getByTestId("translate-block"));
    // Вопрос теперь отдельный узел (у него своя подложка перевода), поэтому
    // номер проверяем по строке целиком: он обязан остаться рядом с текстом.
    const questionRow = screen.getByText("Сколько секунд мыть руки?").parentElement!;
    expect(questionRow.textContent).toContain("1.");
    spy.mockRestore();
  });

  it("на русском интерфейсе кнопки перевода нет", async () => {
    useLocale.setState({ locale: "ru" });
    await openStandard();
    expect(screen.queryByTestId("translate-block")).toBeNull();
  });
});
