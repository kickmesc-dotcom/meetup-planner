// @vitest-environment jsdom
/**
 * VISUAL_AUDIT P3.17: смена вкладки — мягкий вход, но только если ОС не просила
 * обратного.
 *
 * Проверяем два обещания: контент всегда на месте (анимация — украшение, не
 * условие показа) и при `prefers-reduced-motion` стартовое состояние сразу
 * конечное — никакой полупрозрачности и сдвига.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import TabTransition from "./TabTransition";

const motionPref = vi.hoisted(() => ({ reduced: false }));

vi.mock("framer-motion", async (importOriginal) => {
  const actual = await importOriginal<typeof import("framer-motion")>();
  return { ...actual, useReducedMotion: () => motionPref.reduced };
});

beforeEach(() => {
  motionPref.reduced = false;
});

afterEach(cleanup);

describe("TabTransition (P3.17)", () => {
  it("показывает содержимое вкладки", () => {
    render(
      <TabTransition>
        <p>Экран смены</p>
      </TabTransition>,
    );
    expect(screen.getByText("Экран смены")).toBeTruthy();
  });

  it("в обычном режиме входит с нулевой прозрачности", () => {
    const { container } = render(
      <TabTransition>
        <p>Экран</p>
      </TabTransition>,
    );
    expect((container.firstChild as HTMLElement).style.opacity).toBe("0");
  });

  it("уважает prefers-reduced-motion", () => {
    motionPref.reduced = true;
    const { container } = render(
      <TabTransition>
        <p>Экран</p>
      </TabTransition>,
    );
    expect((container.firstChild as HTMLElement).style.opacity).not.toBe("0");
    expect(screen.getByText("Экран")).toBeTruthy();
  });
});
