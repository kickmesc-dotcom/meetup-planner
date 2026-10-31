// @vitest-environment jsdom
/**
 * VISUAL_AUDIT P1.4: нижняя навигация.
 *
 * Проверяем, что вкладки рисуются SVG-иконками (а не эмодзи), подписи остаются
 * доступным именем кнопки, а роли добавляют/убирают нужные пункты.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import TabBar from "./TabBar";
import { useUI } from "@/store/ui";

afterEach(() => {
  cleanup();
  useUI.setState({ tab: "feed" });
});

describe("TabBar", () => {
  it("рисует пять вкладок с SVG-иконками и подписями", () => {
    const { container } = render(<TabBar />);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(5);
    for (const label of ["Задачи", "Смена", "График", "События", "Профиль"]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    // Раньше здесь были эмодзи (✅ 🕒 🗓 …) — теперь один SVG на вкладку.
    expect(container.querySelectorAll("svg")).toHaveLength(5);
    expect(container.textContent).not.toMatch(/[✅🕒🗓📋👤]/u);
  });

  it("руководителю добавляет «Команду», но кабинета в полосе нет ни у кого", () => {
    // 31.10.2026: «Управление» убрано из полосы. Полоса — рабочий день
    // сотрудника, кабинет предприятия живёт в профиле, в разделе
    // «Руководителю». Сотрудник вкладку управления не видит вообще.
    render(<TabBar canManage />);
    expect(screen.getByText("Команда")).toBeTruthy();
    expect(screen.queryByText("Админ")).toBeNull();
    expect(screen.getAllByRole("button")).toHaveLength(6);
  });

  it("сотрудник видит ровно пять своих разделов", () => {
    render(<TabBar />);
    expect(screen.getAllByRole("button")).toHaveLength(5);
    expect(screen.queryByText("Команда")).toBeNull();
  });

  it("шесть подписей не вылезают за кнопку", () => {
    // P3.17: на 360–390 px «Команда»/«События» при 12 px обрезались по краям
    // экрана. Подпись обязана ужиматься внутри своей кнопки, а не вылезать.
    render(<TabBar canManage />);
    const label = screen.getByText("Команда");
    expect(label.className).toContain("truncate");
    expect(label.className).toContain("text-center");
    const button = label.closest("button");
    expect(button?.className).toContain("min-w-0");
    expect(button?.className).toContain("text-2xs");
  });

  it("показывает число открытых поручений, но не больше 9+", () => {
    // Приём из соцсетей: цифра на разделе видна до перехода.
    render(<TabBar openTasks={3} />);
    expect(screen.getByTestId("tab-tasks-badge").textContent).toBe("3");
    // Цифра не ломает доступное имя: объяснение — в aria-label кнопки.
    expect(
      screen.getByRole("button", { name: "Задачи, открытых: 3" }),
    ).toBeTruthy();

    cleanup();
    render(<TabBar openTasks={12} />);
    expect(screen.getByTestId("tab-tasks-badge").textContent).toBe("9+");
  });

  it("не рисует бейдж без открытых задач", () => {
    render(<TabBar openTasks={0} />);
    expect(screen.queryByTestId("tab-tasks-badge")).toBeNull();
  });

  it("тап переключает вкладку", () => {
    render(<TabBar />);
    fireEvent.click(screen.getByText("Смена"));
    expect(useUI.getState().tab).toBe("checklist");
  });

  it("«События» стоят первыми — туда приложение и открывается", () => {
    // Раунд 5: первый экран — события смены, а не личные задачи.
    expect(useUI.getInitialState().tab).toBe("feed");
    render(<TabBar />);
    const buttons = screen.getAllByRole("button");
    expect(buttons[0].textContent).toContain("События");
  });
});
