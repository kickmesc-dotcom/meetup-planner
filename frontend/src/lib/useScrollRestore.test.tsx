// @vitest-environment jsdom
import { useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

import { useScrollRestore } from "./useScrollRestore";

function Probe({ ready }: { ready: boolean }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const { showTop } = useScrollRestore("probe", ready, ref);
  return (
    <div ref={ref} data-testid="box">
      {showTop ? "top" : "hidden"}
    </div>
  );
}

describe("useScrollRestore", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });
  afterEach(cleanup);

  it("показывает «Наверх» после первого экрана и запоминает место", () => {
    const { unmount } = render(<Probe ready />);
    const box = screen.getByTestId("box");
    // jsdom не считает layout, поэтому высоту прокрутки задаём явно.
    Object.defineProperty(box, "scrollTop", {
      value: 900,
      writable: true,
      configurable: true,
    });
    act(() => {
      box.dispatchEvent(new Event("scroll"));
    });
    expect(box.textContent).toBe("top");

    unmount();
    expect(window.sessionStorage.getItem("scroll:probe")).toBe("900");
  });

  it("не падает, если хранилище запрещено", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });
    expect(() => render(<Probe ready />)).not.toThrow();
    spy.mockRestore();
    cleanup();
  });
});
