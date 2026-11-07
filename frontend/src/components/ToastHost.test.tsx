// @vitest-environment jsdom
/**
 * §7.3: после действия человек понимает, что произошло, и не обязан нажимать
 * «ОК» ради этого. Проверяем показ, автоскрытие и ручное закрытие.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import ToastHost from "./ToastHost";
import { clearToasts, showToast } from "./toast";

beforeEach(() => {
  clearToasts();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("ToastHost", () => {
  it("показывает подтверждение и убирает его само", () => {
    render(<ToastHost />);

    act(() => showToast("Сохранено"));
    expect(screen.getByText("Сохранено")).toBeTruthy();

    act(() => vi.advanceTimersByTime(3300));
    expect(screen.queryByText("Сохранено")).toBeNull();
  });

  it("закрывается кнопкой, не дожидаясь таймера", () => {
    render(<ToastHost />);

    act(() => showToast("Готово"));
    fireEvent.click(screen.getByRole("button", { name: "Скрыть сообщение" }));

    expect(screen.queryByText("Готово")).toBeNull();
  });

  it("действие в тосте возвращает удалённое и закрывает плашку", () => {
    const undo = vi.fn();
    render(<ToastHost />);

    act(() => showToast("Смена удалена", "success", { label: "Отменить", run: undo }));
    fireEvent.click(screen.getByRole("button", { name: "Отменить" }));

    expect(undo).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Смена удалена")).toBeNull();
  });

  it("пустое сообщение не превращается в пустую плашку", () => {
    render(<ToastHost />);
    act(() => showToast("   "));
    expect(screen.queryByTestId("toast-host")?.textContent).toBe("");
  });
});
