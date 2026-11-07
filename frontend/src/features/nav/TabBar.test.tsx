// @vitest-environment jsdom
/**
 * VISUAL_AUDIT P1.4: нижняя навигация.
 *
 * Проверяем, что вкладки рисуются SVG-иконками (а не эмодзи), подписи остаются
 * доступным именем кнопки, а роли добавляют/убирают нужные пункты.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import TabBar from "./TabBar";
import { useUI } from "@/store/ui";
const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));

// Подменяем не `useTerms`, а сам HTTP-слой: иначе проверяли бы заглушку, а не
// настоящую подстановку термина в подпись вкладки.
vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return { ...actual, api: apiMock };
});

/** Полоса берёт термины отрасли из тех же текстов, что и остальной интерфейс. */
function renderTabBar(props: { openTasks?: number } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TabBar {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMock.mockResolvedValue({});
});


afterEach(() => {
  cleanup();
  useUI.setState({ tab: "feed" });
});

describe("TabBar", () => {
  it("берёт подпись вкладки из термина отрасли", async () => {
    // Шаг 3.1 плана: у розницы «Задачи» — это «Заявки», у салона «Смена» —
    // «Приём». Меняется одна строка в кабинете, код остаётся прежним.
    apiMock.mockResolvedValue({
      "term.task.many": "Заявки",
      "term.shift.one": "Приём",
    });
    renderTabBar();

    expect(await screen.findByText("Заявки")).toBeTruthy();
    expect(screen.getByText("Приём")).toBeTruthy();
    // Не тронутые термином подписи остаются как были.
    expect(screen.getByText("График")).toBeTruthy();
    expect(screen.queryByText("Задачи")).toBeNull();
  });

  it("рисует пять вкладок с SVG-иконками и подписями", () => {
    const { container } = renderTabBar();
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(5);
    for (const label of ["Задачи", "Чек-лист", "График", "События", "Профиль"]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    // Раньше здесь были эмодзи (✅ 🕒 🗓 …) — теперь один SVG на вкладку.
    expect(container.querySelectorAll("svg")).toHaveLength(5);
    expect(container.textContent).not.toMatch(/[✅🕒🗓📋👤]/u);
  });

  it("полоса одна для всех: руководитель видит те же пять разделов", () => {
    // 02.11.2026: полоса — это рабочий день сотрудника, без вариантов по роли.
    // Раньше у руководителя на месте «Профиля» стояла «Команда», и одна зона
    // выглядела по-разному у разных людей. Команда, приёмка и отчёт живут
    // в зоне управления — вкладками вверху экрана.
    renderTabBar();
    expect(screen.getAllByRole("button")).toHaveLength(5);
    expect(screen.queryByText("Команда")).toBeNull();
    expect(screen.queryByText("Админ")).toBeNull();
  });

  it("подписи не вылезают за кнопку", () => {
    // P3.17: на 360–390 px подписи при 12 px обрезались по краям экрана.
    // Подпись обязана ужиматься внутри своей кнопки, а не вылезать.
    renderTabBar();
    const label = screen.getByText("События");
    expect(label.className).toContain("truncate");
    expect(label.className).toContain("text-center");
    const button = label.closest("button");
    expect(button?.className).toContain("min-w-0");
    expect(button?.className).toContain("text-2xs");
  });

  it("показывает число открытых поручений, но не больше 9+", () => {
    // Приём из соцсетей: цифра на разделе видна до перехода.
    renderTabBar({ openTasks: 3 });
    expect(screen.getByTestId("tab-tasks-badge").textContent).toBe("3");
    // Цифра не ломает доступное имя: объяснение — в aria-label кнопки.
    expect(
      screen.getByRole("button", { name: "Задачи, открытых: 3" }),
    ).toBeTruthy();

    cleanup();
    renderTabBar({ openTasks: 12 });
    expect(screen.getByTestId("tab-tasks-badge").textContent).toBe("9+");
  });

  it("не рисует бейдж без открытых задач", () => {
    renderTabBar({ openTasks: 0 });
    expect(screen.queryByTestId("tab-tasks-badge")).toBeNull();
  });

  it("тап переключает вкладку", () => {
    renderTabBar();
    fireEvent.click(screen.getByText("Чек-лист"));
    expect(useUI.getState().tab).toBe("checklist");
  });

  it("«События» стоят первыми — туда приложение и открывается", () => {
    // Раунд 5: первый экран — события смены, а не личные задачи.
    expect(useUI.getInitialState().tab).toBe("feed");
    renderTabBar();
    const buttons = screen.getAllByRole("button");
    expect(buttons[0].textContent).toContain("События");
  });
});
