// @vitest-environment jsdom
/**
 * Широкий экран: каркас вместо нижней полосы.
 *
 * Проверяем ровно то, из-за чего каркас и появился: все разделы в одном
 * сайдбаре (а не пять подписей в полосе), роли не видят чужих пунктов, а клик
 * переключает вкладку.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import DesktopShell from "./DesktopShell";
import { useUI } from "@/store/ui";

function renderShell(props?: { canManage?: boolean; isAdmin?: boolean }) {
  return render(
    <DesktopShell
      canManage={props?.canManage ?? false}
      isAdmin={props?.isAdmin ?? false}
      meName="Сергей"
      meHint="Официант"
    >
      <div>Экран</div>
    </DesktopShell>,
  );
}

afterEach(() => {
  cleanup();
  useUI.setState({ tab: "feed" });
});

describe("DesktopShell", () => {
  it("кладет в сайдбар все рабочие разделы, а не пять вкладок", () => {
    renderShell();
    for (const label of [
      "События",
      "Мои задачи",
      "Чек-лист смены",
      "Табель",
      "Материалы",
      "Проблемы",
      "Передачи смены",
      "Календарь",
      "Встречи и опросы",
      "Стандарты",
      "Ссылки",
      "Профиль",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeTruthy();
    }
    expect(screen.getByText("Экран")).toBeTruthy();
  });

  it("руководителю показывает команду, приёмку и отчет", () => {
    renderShell({ canManage: true });
    expect(screen.getByRole("button", { name: "Команда" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Приёмка работ" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Отчёт смены" })).toBeTruthy();
    // Без админской роли раздела «Управление» нет.
    expect(screen.queryByRole("button", { name: "Админка" })).toBeNull();
  });

  it("сотруднику не показывает чужие разделы", () => {
    renderShell();
    expect(screen.queryByRole("button", { name: "Команда" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Приёмка работ" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Админка" })).toBeNull();
  });

  it("админу добавляет раздел «Управление»", () => {
    renderShell({ canManage: true, isAdmin: true });
    expect(screen.getByText("Управление")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Админка" }));
    expect(useUI.getState().tab).toBe("admin");
  });

  it("подсвечивает текущий раздел и переключает вкладку по клику", () => {
    renderShell();
    const active = screen
      .getByRole("button", { name: "События" })
      .getAttribute("aria-current");
    expect(active).toBe("page");

    fireEvent.click(screen.getByRole("button", { name: "Мои задачи" }));
    expect(useUI.getState().tab).toBe("tasks");
    expect(
      screen.getByRole("button", { name: "Мои задачи" }).getAttribute("aria-current"),
    ).toBe("page");
    expect(
      screen.getByRole("button", { name: "События" }).getAttribute("aria-current"),
    ).toBeNull();
  });

  it("внизу сайдбара видно, кто вошел", () => {
    renderShell();
    expect(screen.getByText("Сергей")).toBeTruthy();
    expect(screen.getByText("Официант")).toBeTruthy();
    expect(screen.getByTestId("theme-switcher")).toBeTruthy();
  });
});
