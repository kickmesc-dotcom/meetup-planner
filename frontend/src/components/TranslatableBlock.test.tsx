// @vitest-environment jsdom
/**
 * Перевод целого блока одной кнопкой (план, 11.5).
 *
 * Проверяем обещания, которые легко нарушить молча:
 *
 *  • один запрос на весь блок, а не запрос на строку — иначе лента из 20
 *    событий упирается в 20 кругов до сервера на мобильном интернете;
 *  • ручка принимает не больше 20 строк, поэтому больший блок идёт порциями,
 *    а не теряет половину;
 *  • повторное нажатие возвращает оригинал, уход с экрана снимает режим;
 *  • при русском интерфейсе и на латинском тексте кнопки нет;
 *  • честный отказ сервера назван словами, а не пустым местом.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  TranslateBlockButton,
  TranslateFailedNotice,
  useBatchTranslate,
} from "./TranslatableBlock";
import { __clearTranslateCache } from "./translateCore";
import * as translateApi from "@/api/translate";
import { useLocale } from "@/i18n";
import { useTranslateAssist } from "@/store/translate";

function Block({ texts }: { texts: string[] }) {
  const tr = useBatchTranslate(texts);
  return (
    <div>
      {tr.canTranslate && (
        <TranslateBlockButton
          on={tr.on}
          busy={tr.busy}
          onClick={() => void tr.toggle()}
        />
      )}
      <TranslateFailedNotice show={tr.failed} />
      <ul>
        {texts.map((text) => (
          <li key={text}>{tr.t(text)}</li>
        ))}
      </ul>
    </div>
  );
}

beforeEach(() => {
  __clearTranslateCache();
  useLocale.setState({ locale: "uz", uzPackAvailable: true });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useLocale.setState({ locale: "ru" });
});

describe("перевод блока", () => {
  it("переводит весь блок одним запросом и возвращает оригинал повторным нажатием", async () => {
    vi.spyOn(translateApi, "translateTexts").mockResolvedValue({
      target: "uz",
      available: true,
      reason: null,
      items: [
        { translated: "Zalni tozalash", provider: "small100" },
        { translated: "Kassani tekshirish", provider: "small100" },
      ],
    });

    render(<Block texts={["Убрать зал", "Проверить кассу"]} />);
    expect(screen.getByText("Убрать зал")).toBeTruthy();
    // Код языка виден до нажатия: кнопка обязана ответить «на что переведёт».
    expect(screen.getByTestId("translate-target").textContent).toBe("UZ");

    const button = screen.getByTestId("translate-block");
    fireEvent.click(button);

    expect(await screen.findByText("Zalni tozalash")).toBeTruthy();
    expect(screen.getByText("Kassani tekshirish")).toBeTruthy();
    expect(translateApi.translateTexts).toHaveBeenCalledTimes(1);
    expect(translateApi.translateTexts).toHaveBeenCalledWith(
      ["Убрать зал", "Проверить кассу"],
      "uz",
    );
    expect(button.getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(button);
    expect(screen.getByText("Убрать зал")).toBeTruthy();
    // Второе нажатие — из памяти, без нового круга до сервера.
    expect(translateApi.translateTexts).toHaveBeenCalledTimes(1);
  });

  it("большой блок идёт порциями по 20, а не теряет хвост", async () => {
    const texts = Array.from({ length: 25 }, (_, i) => `Строка ${i + 1}`);
    const spy = vi.spyOn(translateApi, "translateTexts").mockImplementation(
      async (batch, target) => ({
        target,
        available: true,
        reason: null,
        items: batch.map((t) => ({ translated: `[${t}]`, provider: "small100" })),
      }),
    );

    render(<Block texts={texts} />);
    fireEvent.click(screen.getByTestId("translate-block"));

    expect(await screen.findByText("[Строка 1]")).toBeTruthy();
    expect(screen.getByText("[Строка 25]")).toBeTruthy();
    expect(translateApi.translateTexts).toHaveBeenCalledTimes(2);
    expect(spy.mock.calls[0][0]).toHaveLength(20);
    expect(spy.mock.calls[1][0]).toHaveLength(5);
  });

  it("уход с экрана снимает режим", async () => {
    vi.spyOn(translateApi, "translateTexts").mockResolvedValue({
      target: "uz",
      available: true,
      reason: null,
      items: [{ translated: "Zalni tozalash", provider: "small100" }],
    });

    render(<Block texts={["Убрать зал"]} />);
    fireEvent.click(screen.getByTestId("translate-block"));
    expect(await screen.findByText("Zalni tozalash")).toBeTruthy();

    // Так экран узнаёт о переходе на другую вкладку.
    useTranslateAssist.getState().bump();

    await waitFor(() => expect(screen.getByText("Убрать зал")).toBeTruthy());
  });

  it("на русском интерфейсе кнопки нет", () => {
    useLocale.setState({ locale: "ru" });
    render(<Block texts={["Убрать зал"]} />);
    expect(screen.queryByTestId("translate-block")).toBeNull();
  });

  it("на латинском тексте кнопки нет: переводить нечего", () => {
    render(<Block texts={["Clean the hall"]} />);
    expect(screen.queryByTestId("translate-block")).toBeNull();
  });

  it("честный отказ сервера назван словами", async () => {
    vi.spyOn(translateApi, "translateTexts").mockResolvedValue({
      target: "uz",
      available: true,
      reason: "no model",
      items: [{ translated: null, provider: null }],
    });

    render(<Block texts={["Убрать зал"]} />);
    fireEvent.click(screen.getByTestId("translate-block"));

    expect(await screen.findByTestId("translate-block-failed")).toBeTruthy();
    expect(screen.getByText("Убрать зал")).toBeTruthy();
  });
});
