// @vitest-environment jsdom
/**
 * «Спросить»: поиск по знаниям.
 *
 * Проверяем ровно то, от чего зависит доверие к поиску: запрос уходит только по
 * кнопке (не на каждую букву), результат показывается с контекстом, а пустая
 * выдача говорит «спросите руководителя», а не оставляет пустой экран.
 *
 * Сеть и Telegram-webapp замоканы: экран не должен ни ходить в API, ни дёргать
 * `window.Telegram` в тестовом окружении.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AskScreen from "./AskScreen";
import { searchKnowledge } from "@/api/knowledge";

vi.mock("@/api/knowledge", () => ({ searchKnowledge: vi.fn() }));
vi.mock("@/tg/webapp", () => ({ haptic: vi.fn() }));
vi.mock("@/store/ui", () => ({
  useUI: (selector: (state: { setTab: () => void }) => unknown) =>
    selector({ setTab: () => {} }),
}));

const searchMock = vi.mocked(searchKnowledge);

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AskScreen />
    </QueryClientProvider>,
  );
}

async function runSearch(text: string) {
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: text } });
  fireEvent.submit(input.closest("form")!);
}

beforeEach(() => searchMock.mockReset());
afterEach(cleanup);

describe("AskScreen", () => {
  it("не ходит в сеть, пока запрос не отправлен", () => {
    renderScreen();
    expect(searchMock).not.toHaveBeenCalled();
    // Кнопка выключена на коротком вводе: запрос из одной буквы — это не поиск.
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "с" } });
    expect((screen.getByRole("button", { name: "Найти" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("ищет по кнопке и показывает результат с разделом", async () => {
    searchMock.mockResolvedValue({
      query: "закрыть смену",
      words: ["закрыть", "смену"],
      hits: [
        {
          kind: "standard",
          id: 7,
          title: "Закрытие смены",
          snippet: "…сдайте выручку старшему…",
          subtitle: "other",
        },
      ],
      empty: false,
    });
    renderScreen();
    await runSearch("закрыть смену");
    await waitFor(() => expect(searchMock).toHaveBeenCalledTimes(1));
    expect(searchMock.mock.calls[0][0]).toBe("закрыть смену");
    expect(await screen.findByText("Закрытие смены")).toBeTruthy();
    expect(screen.getByText(/сдайте выручку/)).toBeTruthy();
  });

  it("на пустой выдаче предлагает спросить руководителя", async () => {
    searchMock.mockResolvedValue({
      query: "несуществующее",
      words: ["несуществующее"],
      hits: [],
      empty: true,
    });
    renderScreen();
    await runSearch("несуществующее");
    expect(
      await screen.findByText(/Спросите руководителя/),
    ).toBeTruthy();
  });
});
