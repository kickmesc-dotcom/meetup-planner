// @vitest-environment jsdom
/**
 * Чек-лист смены: выбор зала и общее закрытие.
 *
 * Проверяем два правила владельца: официант сначала выбирает зал (без выбора
 * пунктов нет), а закрытие смены — отдельная общая вкладка, где последний пункт
 * требует фотоотчёт.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ChecklistScreen from "./ChecklistScreen";
import * as hrApi from "@/api/hr";

vi.mock("@/api/texts", () => ({
  useAppText: (_code: string, fallback: string) => fallback,
}));

const item = {
  id: 10,
  title: "Протереть столы 400–500 спецраствором",
  description: null,
  requires_photo: false,
  is_mandatory: true,
  done: false,
  done_at: null,
  photo_file_id: null,
  photo_url: null,
  note: null,
};

function renderScreen() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ChecklistScreen />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.spyOn(hrApi, "fetchHalls").mockResolvedValue([
    { id: 1, name: "Первый зал", slug: "first", sort_order: 10 },
    { id: 2, name: "Второй зал", slug: "second", sort_order: 20 },
  ]);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ChecklistScreen", () => {
  it("без выбора зала показывает выбор, а не пункты", async () => {
    vi.spyOn(hrApi, "fetchChecklist").mockResolvedValue({
      run_id: null,
      template_id: null,
      template_title: null,
      kind: "shift",
      shift_date: "2026-10-20",
      status: "in_progress",
      done: 0,
      total: 0,
      progress_text: "Выполнено 0 из 0",
      items: [],
      needs_hall: true,
      hall_id: null,
      hall_name: null,
    });
    renderScreen();
    expect(await screen.findByText("В каком зале работаешь?")).toBeTruthy();
    expect(screen.queryByText(item.title)).toBeNull();
  });

  it("выбор зала открывает чек-лист именно этого зала", async () => {
    vi.spyOn(hrApi, "fetchChecklist").mockResolvedValue({
      run_id: null,
      template_id: null,
      template_title: null,
      kind: "shift",
      shift_date: "2026-10-20",
      status: "in_progress",
      done: 0,
      total: 0,
      progress_text: "Выполнено 0 из 0",
      items: [],
      needs_hall: true,
      hall_id: null,
      hall_name: null,
    });
    const choose = vi.spyOn(hrApi, "chooseHall").mockResolvedValue({
      run_id: null,
      template_id: 5,
      template_title: "Открытие — Первый зал",
      kind: "shift",
      shift_date: "2026-10-20",
      status: "in_progress",
      done: 0,
      total: 1,
      progress_text: "Выполнено 0 из 1",
      items: [item],
      needs_hall: false,
      hall_id: 1,
      hall_name: "Первый зал",
    });

    renderScreen();
    // VISUAL_AUDIT P1.4: дверь теперь SVG-иконка, текст остался.
    fireEvent.click(
      await screen.findByRole("button", { name: /Первый зал/ }),
    );
    expect(await screen.findByText(item.title)).toBeTruthy();
    expect(choose).toHaveBeenCalledWith(1);
    expect(screen.getByText(/Сегодня работаешь:/)).toBeTruthy();
  });

  it("вкладка «Закрытие» показывает общий чек-лист с фото-пунктом", async () => {
    const fetch = vi.spyOn(hrApi, "fetchChecklist").mockImplementation(
      async (kind) =>
        kind === "close"
          ? {
              run_id: null,
              template_id: 9,
              template_title: "Закрытие смены",
              kind: "close",
              shift_date: "2026-10-20",
              status: "in_progress",
              done: 0,
              total: 1,
              progress_text: "Выполнено 0 из 1",
              items: [
                {
                  ...item,
                  id: 99,
                  title: "Показать рабочее место перед закрытием смены",
                  requires_photo: true,
                },
              ],
              needs_hall: false,
              hall_id: null,
              hall_name: null,
            }
          : {
              run_id: null,
              template_id: 5,
              template_title: "Открытие — Первый зал",
              kind: "shift",
              shift_date: "2026-10-20",
              status: "in_progress",
              done: 0,
              total: 1,
              progress_text: "Выполнено 0 из 1",
              items: [item],
              needs_hall: false,
              hall_id: 1,
              hall_name: "Первый зал",
            },
    );

    renderScreen();
    fireEvent.click(screen.getByText("Закрытие"));
    // общий чек-лист не зависит от зала — выбора зала на этой вкладке нет
    expect(
      await screen.findByText("Показать рабочее место перед закрытием смены"),
    ).toBeTruthy();
    expect(screen.queryByText("В каком зале работаешь?")).toBeNull();
    expect(fetch).toHaveBeenCalledWith("close");
  });
});
