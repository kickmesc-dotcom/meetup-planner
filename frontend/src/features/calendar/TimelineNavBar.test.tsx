// @vitest-environment jsdom
/**
 * GHG11(12): тема — обычный элемент постоянной панели календаря.
 *
 * В режиме таймлайна `NavBar` не рисуется (у него своя нижняя плашка), поэтому
 * свитчер темы обязан жить и здесь — иначе на календаре остаётся экран без
 * переключателя. Заодно проверяем, что он не спрятан в закрываемом баннере.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import TimelineNavBar from "./views/TimelineNavBar";
import NavBar from "./NavBar";
import WelcomeBanner from "@/features/welcome/WelcomeBanner";

afterEach(cleanup);

describe("свитчер темы в панелях календаря", () => {
  it("в нижней плашке таймлайна свитчер есть и он рядом с «К сегодня»", () => {
    render(<TimelineNavBar isOnToday={false} />);
    const switcher = screen.getByTestId("theme-switcher");
    expect(switcher).toBeTruthy();
    const row = switcher.parentElement!;
    expect(row.textContent).toContain("К сегодня");
  });

  it("в NavBar свитчер идёт последним элементом строки (после стрелки вперёд)", () => {
    render(<NavBar />);
    const switcher = screen.getByTestId("theme-switcher");
    const row = switcher.parentElement!;
    const buttons = [...row.querySelectorAll("button")];
    expect(buttons[buttons.length - 1]).toBe(switcher);
    expect(row.querySelector('button[aria-label="вперёд"]')).toBeTruthy();
  });

  it("в приветствии свитчера нет — баннер закрывается, кнопка бы пропала", () => {
    // Баннер ходит в react-query за званиями — нужен провайдер.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <WelcomeBanner users={[]} meName="Сомов" format="avatar" onHide={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(screen.queryByTestId("theme-switcher")).toBeNull();
    expect(screen.getByLabelText("Скрыть приветствие")).toBeTruthy();
  });
});
