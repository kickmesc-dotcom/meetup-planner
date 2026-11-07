// @vitest-environment jsdom
/**
 * §3.2: знакомство появляется один раз и не возвращается после «Понятно».
 * §4.3: сотруднику, которому кабинет недоступен, подсказка не показывается.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import ZoneHint from "./ZoneHint";

vi.mock("@/tg/webapp", () => ({ haptic: vi.fn() }));

beforeEach(() => localStorage.clear());
afterEach(cleanup);

describe("ZoneHint", () => {
  it("показывает подсказку руководителю один раз", () => {
    render(<ZoneHint canManage />);
    expect(screen.getByTestId("zone-hint")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Понятно" }));

    expect(screen.queryByTestId("zone-hint")).toBeNull();
    expect(localStorage.getItem("ux.zoneHint.v1")).toBe("1");
  });

  it("не возвращается после перезапуска", () => {
    localStorage.setItem("ux.zoneHint.v1", "1");
    render(<ZoneHint canManage />);
    expect(screen.queryByTestId("zone-hint")).toBeNull();
  });

  it("не показывается сотруднику без права на кабинет", () => {
    render(<ZoneHint canManage={false} />);
    expect(screen.queryByTestId("zone-hint")).toBeNull();
  });
});
