// @vitest-environment jsdom
/**
 * Фото-пункты чек-листа свёрнуты в строку.
 *
 * Причина: на 360px пункт с фотоотчётом занимал пол-экрана (описание,
 * подсказка, кнопка камеры), и в список помещалось полтора пункта. Свёрнутый
 * вид даёт увидеть смену целиком, а раскрытие — одним тапом.
 *
 * Проверяем именно поведение: по умолчанию деталей нет, после тапа они
 * появляются, после «Свернуть» — снова нет. Обычный пункт не сворачивается:
 * у него нет ничего лишнего, и прятать нечего.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ChecklistScreen from "./ChecklistScreen";
import * as hrApi from "@/api/hr";

vi.mock("@/api/texts", () => ({
  useAppText: (_code: string, fallback: string) => fallback,
  useTerms: () => (_code: string, fallback: string) => fallback,
}));

const plainItem = {
  id: 10,
  title: "Протереть столы",
  description: null,
  requires_photo: false,
  is_mandatory: true,
  done: false,
  done_at: null,
  photo_file_id: null,
  photo_url: null,
  note: null,
};

const photoItem = {
  ...plainItem,
  id: 11,
  title: "Показать рабочее место",
  description: "Снимок стойки и зала целиком",
  requires_photo: true,
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
  localStorage.clear();
  vi.spyOn(hrApi, "fetchHalls").mockResolvedValue([]);
  vi.spyOn(hrApi, "fetchChecklist").mockResolvedValue({
    run_id: 1,
    template_id: 5,
    template_title: "Закрытие смены",
    kind: "shift",
    shift_date: "2026-11-06",
    status: "in_progress",
    done: 0,
    total: 2,
    progress_text: "Выполнено 0 из 2",
    items: [plainItem, photoItem],
    needs_hall: false,
    hall_id: 1,
    hall_name: "Первый зал",
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ChecklistScreen: фото-пункт свёрнут", () => {
  it("по умолчанию не показывает описание и камеру", async () => {
    renderScreen();

    expect(await screen.findByText("Показать рабочее место")).toBeTruthy();
    // Название видно всегда: человек должен знать, что пункт есть.
    expect(screen.queryByText("Снимок стойки и зала целиком")).toBeNull();
    expect(screen.queryByRole("button", { name: /Снять/ })).toBeNull();
  });

  it("раскрывается по тапу и сворачивается обратно", async () => {
    renderScreen();

    fireEvent.click(
      await screen.findByRole("button", { name: "Раскрыть пункт с фотоотчётом" }),
    );

    expect(await screen.findByText("Снимок стойки и зала целиком")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Снять/ })).toBeTruthy();

    fireEvent.click(screen.getByText("Свернуть"));

    expect(screen.queryByText("Снимок стойки и зала целиком")).toBeNull();
    expect(screen.queryByRole("button", { name: /Снять/ })).toBeNull();
  });

  it("обычный пункт не прячет ничего", async () => {
    renderScreen();

    // Кнопка раскрытия одна — только у фото-пункта.
    await screen.findByText("Протереть столы");
    expect(
      screen.getAllByRole("button", { name: "Раскрыть пункт с фотоотчётом" }),
    ).toHaveLength(1);
  });
});
