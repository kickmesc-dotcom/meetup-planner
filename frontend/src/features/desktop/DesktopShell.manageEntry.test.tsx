// @vitest-environment jsdom
/**
 * §4.2: главное действие должно быть доступно быстро.
 *
 * Раньше попасть в кабинет на компьютере можно было только через профиль или
 * узкий переключатель сверху. Теперь в сайдбаре есть отдельная дверь — но
 * только у того, кому сервер разрешил управлять.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import DesktopShell from "./DesktopShell";
import { useUI } from "@/store/ui";

vi.mock("@/components/LanguageSwitcher", () => ({ default: () => <div>lang</div> }));
vi.mock("@/components/ThemeSwitcher", () => ({ default: () => <div>theme</div> }));
vi.mock("@/api/texts", () => ({
  useTerms: () => (_code: string, fallback: string) => fallback,
}));

beforeEach(() => {
  useUI.setState({ tab: "feed", mode: "staff" });
});
afterEach(cleanup);

function shell(canManage: boolean) {
  return render(
    <DesktopShell meName="Анна" meHint="Управляющая" canManage={canManage}>
      <div>работа</div>
    </DesktopShell>,
  );
}

describe("DesktopShell: дверь в кабинет", () => {
  it("не показывает управление тому, кому оно недоступно", () => {
    shell(false);
    expect(screen.queryByRole("button", { name: "Управление" })).toBeNull();
  });

  it("переключает зону из сайдбара одним нажатием", () => {
    shell(true);
    fireEvent.click(screen.getByRole("button", { name: "Управление" }));
    expect(useUI.getState().mode).toBe("manage");
  });
});
