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
  useUI.setState({ tab: "tasks" });
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

  it("тап переключает вкладку", () => {
    render(<TabBar isAdmin={false} />);
    fireEvent.click(screen.getByText("Смена"));
    expect(useUI.getState().tab).toBe("checklist");
  });
});
