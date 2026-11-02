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

function renderShell() {
  return render(
    <DesktopShell meName="Сергей" meHint="Официант">
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
      "График",
      "Материалы",
      "Проблемы",
      "Передачи смены",
      "Встречи и опросы",
      "Стандарты",
      "Ссылки",
      "Профиль",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeTruthy();
    }
    // Старого «Календаря» (сетка свободного времени планировщика с людьми,
    // которых в смене уже нет) в сайдборе быть не должно — только расписание.
    expect(screen.queryByRole("button", { name: "Календарь" })).toBeNull();
    expect(screen.getByText("Экран")).toBeTruthy();
  });

  it("не держит управленческих разделов — они живут в зоне управления", () => {
    // 02.11.2026: каркас сотрудника один для всех. Команда, приёмка и отчёт
    // переехали во вторую зону (вкладки вверху), а не в сайдбар сотрудника.
    renderShell();
    expect(screen.queryByRole("button", { name: "Команда" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Приёмка работ" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Отчёт смены" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Админка" })).toBeNull();
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
