// @vitest-environment jsdom
/**
 * Кнопка перевода на блоке данных (план, 11).
 *
 * Проверяются обещания, которые легко нарушить молча:
 *
 *  • перевод появляется только по нажатию и снимается повторным — человек
 *    должен уметь вернуться к оригиналу задания, по которому отчитывается;
 *  • уход с экрана снимает режим сам (вкладки не размонтируются, поэтому
 *    локального состояния мало — это отдельный счётчик);
 *  • при русском интерфейсе и на латинском тексте кнопки нет: обещание
 *    «перевести» не должно висеть там, где переводить нечего;
 *  • если сервер честно ответил «недоступно» (Amvera без модели), это сказано
 *    словами, а не пустым местом.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import TranslatableText from "./TranslatableText";
import * as translateApi from "@/api/translate";
import { useLocale } from "@/i18n";
import { useTranslateAssist } from "@/store/translate";

beforeEach(() => {
  useLocale.setState({ locale: "uz", uzPackAvailable: true });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useLocale.setState({ locale: "ru" });
});

describe("TranslatableText", () => {
  it("переводит по нажатию и возвращает оригинал повторным", async () => {
    vi.spyOn(translateApi, "translateTexts").mockResolvedValue({
      target: "uz",
      available: true,
      reason: null,
      items: [{ translated: "Zalni tozalash", provider: "small100" }],
    });

    render(<TranslatableText text="Убрать зал к открытию" />);
    const button = screen.getByTestId("translate-toggle");
    expect(screen.getByText("Убрать зал к открытию")).toBeTruthy();
    expect(button.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(button);
    expect(await screen.findByText("Zalni tozalash")).toBeTruthy();
    expect(screen.queryByText("Убрать зал к открытию")).toBeNull();
    expect(button.getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(button);
    expect(screen.getByText("Убрать зал к открытию")).toBeTruthy();
    expect(translateApi.translateTexts).toHaveBeenCalledTimes(1);
  });

  it("снимает режим при уходе с экрана", async () => {
    vi.spyOn(translateApi, "translateTexts").mockResolvedValue({
      target: "uz",
      available: true,
      reason: null,
      items: [{ translated: "Kassani tekshirish", provider: "small100" }],
    });

    render(<TranslatableText text="Проверить кассу вечером" />);
    fireEvent.click(screen.getByTestId("translate-toggle"));
    expect(await screen.findByText("Kassani tekshirish")).toBeTruthy();

    // Смена вкладки: то же событие, что дёргает `setTab`.
    useTranslateAssist.getState().bump();

    await waitFor(() =>
      expect(screen.getByText("Проверить кассу вечером")).toBeTruthy(),
    );
    expect(screen.queryByText("Kassani tekshirish")).toBeNull();
  });

  it("при русском интерфейсе кнопки нет", () => {
    useLocale.setState({ locale: "ru" });
    render(<TranslatableText text="Вынести мусор" />);
    expect(screen.queryByTestId("translate-toggle")).toBeNull();
    expect(screen.getByText("Вынести мусор")).toBeTruthy();
  });

  it("латинский текст не переводится и кнопки не получает", () => {
    render(<TranslatableText text="Wi-Fi in the hall" />);
    expect(screen.queryByTestId("translate-toggle")).toBeNull();
  });

  it("честно говорит, что перевода нет", async () => {
    vi.spyOn(translateApi, "translateTexts").mockResolvedValue({
      target: "uz",
      available: false,
      reason: "model_unavailable",
      items: [{ translated: null, provider: null }],
    });

    render(<TranslatableText text="Сдать смену мастеру" />);
    fireEvent.click(screen.getByTestId("translate-toggle"));
    expect(await screen.findByTestId("translate-failed")).toBeTruthy();
    // Оригинал остаётся на месте: подменять его «ничем» нельзя.
    expect(screen.getByText("Сдать смену мастеру")).toBeTruthy();
  });
});
