// @vitest-environment jsdom
/**
 * VISUAL_AUDIT P3.16: статусная палитра — только для состояния.
 *
 * Пометка тестового пула `BOT` — подпись, а не статус, поэтому она не должна
 * брать янтарный цвет: на одном экране он спорил с настоящими статусами
 * (выполнено / просрочено / в работе).
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import Badge from "./Badge";

afterEach(cleanup);

describe("Badge (P3.16)", () => {
  it("помечает тестовый пул нейтрально, без статусного цвета", () => {
    render(<Badge text="Стажёр" emoji="🌱" demo />);

    const chip = screen.getByText("BOT");
    expect(chip.className).not.toMatch(/status-/);
    // Сама плашка при этом остаётся: должность читается.
    expect(screen.getByText("Стажёр")).toBeTruthy();
  });

  it("живому сотруднику чипа BOT не добавляет", () => {
    render(<Badge text="Су-шеф" />);
    expect(screen.queryByText("BOT")).toBeNull();
  });

  it("без текста и без пометки ничего не рисует", () => {
    const { container } = render(<Badge text={null} />);
    expect(container.firstChild).toBeNull();
  });
});
