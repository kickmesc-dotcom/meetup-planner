// @vitest-environment jsdom
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import ErrorBoundary from "./ErrorBoundary";

function Boom(): ReactElement {
  throw new Error("boom");
}

afterEach(cleanup);

describe("ErrorBoundary", () => {
  it("вместо белого экрана показывает восстановление", () => {
    // React штатно логирует пойманную ошибку — в тесте это шум.
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Обновить" })).toBeTruthy();
    spy.mockRestore();
  });

  it("здоровое дерево рендерится как есть", () => {
    render(
      <ErrorBoundary>
        <p>работает</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("работает")).toBeTruthy();
  });
});
