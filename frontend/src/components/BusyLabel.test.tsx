// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { BusyLabel } from "./BusyLabel";

afterEach(cleanup);

describe("BusyLabel", () => {
  it("без ожидания показывает только текст действия", () => {
    const { container } = render(<BusyLabel busy={false}>Сохранить</BusyLabel>);
    expect(screen.getByText("Сохранить")).toBeTruthy();
    expect(container.querySelector(".animate-spin")).toBeNull();
  });

  it("в ожидании оставляет текст и добавляет спиннер", () => {
    const { container } = render(<BusyLabel busy>Сохранить</BusyLabel>);
    expect(screen.getByText("Сохранить")).toBeTruthy();
    expect(container.querySelector(".animate-spin")).not.toBeNull();
  });
});
