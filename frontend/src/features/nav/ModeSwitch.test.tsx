// @vitest-environment jsdom
/**
 * Верхние вкладки зон «Сотрудник | Управление» (02.11.2026).
 *
 * Проверяем контракт, на котором держится разделение:
 *  - RÔLE: две вкладки с `aria-selected`, как положено табам (скринридер не
 *    должен читать их как обычные кнопки без состояния);
 *  - переход в управление и обратно меняет режим в сторе, а не вкладку —
 *    вкладка сотрудника остаётся той, где человек был;
 *  - приложение всегда открывается зоной сотрудника.
 *
 * Права здесь не проверяются намеренно: переключатель — лист, а не охрана.
 * Кто его рисует, решает `App.tsx` (`canManageZone`), а сервер всё равно
 * проверяет права на каждой ручке кабинета.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import ModeSwitch from "./ModeSwitch";
import { useUI } from "@/store/ui";

afterEach(() => {
  cleanup();
  useUI.setState({ mode: "staff", tab: "feed" });
});

describe("ModeSwitch", () => {
  it("рисует две вкладки и отмечает активную", () => {
    render(<ModeSwitch />);

    const staff = screen.getByTestId("mode-staff");
    const manage = screen.getByTestId("mode-manage");
    expect(staff.getAttribute("role")).toBe("tab");
    expect(staff.getAttribute("aria-selected")).toBe("true");
    expect(manage.getAttribute("aria-selected")).toBe("false");
    expect(screen.getByRole("tablist").getAttribute("aria-label")).toBe(
      "Зона приложения",
    );
  });

  it("переключает в управление, не трогая вкладку сотрудника", () => {
    useUI.setState({ tab: "checklist" });
    render(<ModeSwitch />);

    fireEvent.click(screen.getByTestId("mode-manage"));
    expect(useUI.getState().mode).toBe("manage");
    // Вернувшись, человек должен попасть туда, где был, а не на «События».
    expect(useUI.getState().tab).toBe("checklist");

    fireEvent.click(screen.getByTestId("mode-staff"));
    expect(useUI.getState().mode).toBe("staff");
  });

  it("по умолчанию открывается зоной сотрудника", () => {
    expect(useUI.getInitialState().mode).toBe("staff");
  });
});
