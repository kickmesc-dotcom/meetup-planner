// @vitest-environment jsdom
/**
 * `back-stack-integrity`: вкладка — шаг истории.
 *
 * До прохода смена вкладок не писалась в историю: «назад» закрывал мини-апп
 * с любой вкладки, кроме корневой. Тест держит два обещания:
 *
 *  - переход пишет `semitaskTab` в состояние истории;
 *  - `popstate` возвращает вкладку и НЕ добавляет новый шаг.
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useTabHistory } from "./useTabHistory";
import { useUI } from "@/store/ui";

beforeEach(() => {
  useUI.setState({ tab: "feed" });
  window.history.replaceState({}, "");
});

describe("useTabHistory", () => {
  it("пишет вкладку в историю при переходе", () => {
    renderHook(() => useTabHistory());

    act(() => useUI.getState().setTab("tasks"));

    expect(useUI.getState().tab).toBe("tasks");
    expect(window.history.state?.semitaskTab).toBe("tasks");
  });

  it("возвращает вкладку по popstate без нового шага", () => {
    renderHook(() => useTabHistory());
    act(() => useUI.getState().setTab("tasks"));
    const lengthBefore = window.history.length;
    // Так выглядит шаг, оставленный прежней вкладкой.
    const state = { semitaskTab: "checklist" };

    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate", { state }));
    });

    expect(useUI.getState().tab).toBe("checklist");
    expect(window.history.length).toBe(lengthBefore);
  });
});
