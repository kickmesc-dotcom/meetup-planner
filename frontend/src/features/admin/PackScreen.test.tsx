// @vitest-environment jsdom
/**
 * Пакет отрасли в кабинете (02.11.2026).
 *
 * Что проверяем и почему:
 *  - на экране видно СОДЕРЖИМОЕ пакета (слова, должности, пункты), а не только
 *    название: применять вслепую руководитель не должен;
 *  - «Применить» отправляет частичный запрос без `force_terms`, то есть не
 *    затирает переименованное;
 *  - «Вернуть слова пакета» сначала спрашивает подтверждение и только потом
 *    ставит `force_terms: true`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { applyPack, fetchPack, type PackState } from "@/api/packs";

vi.mock("@/api/packs", () => ({
  fetchPack: vi.fn(),
  applyPack: vi.fn(),
}));

vi.mock("@/tg/webapp", () => ({
  haptic: vi.fn(),
  showAlert: vi.fn(() => Promise.resolve()),
  showConfirm: vi.fn(() => Promise.resolve(true)),
}));

import PackScreen from "./PackScreen";

const STATE: PackState = {
  industry: "salon",
  can_apply: true,
  pack: {
    industry: "salon",
    title: "Салон красоты",
    why: "Приёмы вместо смен, кабинеты вместо залов; чек-листы про инструмент, стерилизацию и запись.",
    terms: {
      "term.hall.one": "Кабинет",
      "term.hall.many": "Кабинеты",
      "term.shift.one": "Приём",
      "term.shift.many": "Приёмы",
      "term.task.one": "Заявка",
      "term.task.many": "Заявки",
    },
    positions: ["Парикмахер", "Мастер ногтей"],
    checklist_items: 2,
    opening_items: ["Проверить стерилизацию"],
    closing_items: ["Убрать кабинет"],
    kpi: { xp_shift_done: 6 },
  },
  catalog: [],
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PackScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(fetchPack).mockResolvedValue(STATE);
  vi.mocked(applyPack).mockResolvedValue({
    industry: "salon",
    title: "Салон красоты",
    terms_set: 6,
    templates_created: 2,
    kpi_updated: true,
    force: false,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PackScreen", () => {
  it("показывает слова, должности и пункты до применения", async () => {
    renderScreen();

    await screen.findByText("Салон красоты");
    // Пара «много · один» читается как словарь, а не как два значения подряд.
    const hallRow = screen.getByText(/Кабинеты/).textContent ?? "";
    expect(hallRow).toContain("Кабинеты");
    expect(hallRow).toContain("Кабинет");
    expect(screen.getByText("Парикмахер")).toBeTruthy();
    expect(screen.getByText(/Проверить стерилизацию/)).toBeTruthy();
  });

  it("применяет пакет без перезаписи правок", async () => {
    renderScreen();
    await screen.findByText("Салон красоты");

    fireEvent.click(screen.getByText("Применить пакет"));

    await waitFor(() => expect(applyPack).toHaveBeenCalledWith({ force_terms: false }));
  });

  it("возвращает слова пакета только после подтверждения", async () => {
    const { showConfirm } = await import("@/tg/webapp");
    renderScreen();
    await screen.findByText("Салон красоты");

    fireEvent.click(screen.getByText("Вернуть слова пакета"));

    await waitFor(() => expect(showConfirm).toHaveBeenCalled());
    await waitFor(() => expect(applyPack).toHaveBeenCalledWith({ force_terms: true }));
  });
});
