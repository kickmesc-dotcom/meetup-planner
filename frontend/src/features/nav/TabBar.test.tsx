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
    const { container } = render(<TabBar isAdmin={false} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(5);
    for (const label of ["Задачи", "Смена", "Табель", "События", "Профиль"]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    // Раньше здесь были эмодзи (✅ 🕒 🗓 …) — теперь один SVG на вкладку.
    expect(container.querySelectorAll("svg")).toHaveLength(5);
    expect(container.textContent).not.toMatch(/[✅🕒🗓📋👤]/u);
  });

  it("руководителю добавляет «Команду», админу — «Админ»", () => {
    render(<TabBar isAdmin canManage />);
    expect(screen.getByText("Команда")).toBeTruthy();
    expect(screen.getByText("Админ")).toBeTruthy();
    expect(screen.getAllByRole("button")).toHaveLength(7);
  });

  it("семь подписей не вылезают за кнопку", () => {
    // P3.17: на 360–390 px «Команда»/«События» при 12 px обрезались по краям
    // экрана. Подпись обязана ужиматься внутри своей кнопки, а не вылезать.
    render(<TabBar isAdmin canManage />);
    const label = screen.getByText("Команда");
    expect(label.className).toContain("truncate");
    expect(label.className).toContain("text-center");
    const button = label.closest("button");
    expect(button?.className).toContain("min-w-0");
    expect(button?.className).toContain("text-2xs");
  });

  it("тап переключает вкладку", () => {
    render(<TabBar isAdmin={false} />);
    fireEvent.click(screen.getByText("Смена"));
    expect(useUI.getState().tab).toBe("checklist");
  });

  it("«События» стоят первыми — туда приложение и открывается", () => {
    // Раунд 5: первый экран — события смены, а не личные задачи.
    expect(useUI.getInitialState().tab).toBe("feed");
    render(<TabBar isAdmin={false} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons[0].textContent).toContain("События");
  });
});
