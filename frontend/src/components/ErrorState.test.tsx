// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import ErrorState from "./ErrorState";

afterEach(cleanup);

describe("ErrorState: обрыв сети", () => {
  it("называет обрыв связи и повторяет запрос, когда сеть вернулась", () => {
    const onRetry = vi.fn();
    render(<ErrorState error={new TypeError("Failed to fetch")} onRetry={onRetry} />);

    expect(screen.getByText("Нет связи")).toBeTruthy();
    fireEvent(window, new Event("online"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("обычную ошибку сервера не выдаёт за обрыв и не ждёт online", () => {
    const onRetry = vi.fn();
    render(<ErrorState error={new Error("boom")} onRetry={onRetry} />);

    expect(screen.getByText("Что-то пошло не так")).toBeTruthy();
    fireEvent(window, new Event("online"));
    expect(onRetry).not.toHaveBeenCalled();
  });
});
