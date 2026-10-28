// @vitest-environment jsdom
/**
 * «Сказал — стало поручением» (план, 8.5).
 *
 * Проверяем то, ради чего механика существует, а не «рисуется ли компонент»:
 *
 *  • **подписи раньше данных.** Заголовок, поле и кнопка видны сразу, ещё до
 *    ответа сервера: на медленном канале человек не смотрит в пустую шторку;
 *  • **черновик показывается до создания** — «как поняли» появляется в ответ на
 *    ввод, и ничего при этом не создаётся (одно нажатие остаётся за человеком);
 *  • **неоднозначность не угадывается:** две Ани дают выбор, а кнопка
 *    «Создать» заблокирована, пока исполнитель не выбран;
 *  • **созревает ровно то, что на экране:** в запрос уходят срок, срочность и
 *    фото, которые видны в плашках, а не «что-то похожее»;
 *  • **голос есть только там, где браузер умеет слушать** — иначе кнопки нет.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import QuickTaskSheet from "./QuickTaskSheet";
import {
  createQuickTask,
  fetchQuickPeople,
  parseQuickText,
  type QuickDraft,
} from "@/api/quick";

vi.mock("@/api/quick", async (importOriginal) => {
  // `quickErrorText` оставляем настоящим: проверяем перевод кодов в фразы.
  const actual = await importOriginal<typeof import("@/api/quick")>();
  return {
    ...actual,
    parseQuickText: vi.fn(),
    createQuickTask: vi.fn(),
    fetchQuickPeople: vi.fn(),
  };
});

const parseMock = vi.mocked(parseQuickText);
const createMock = vi.mocked(createQuickTask);
const peopleMock = vi.mocked(fetchQuickPeople);

function draft(overrides: Partial<QuickDraft> = {}): QuickDraft {
  return {
    title: "Протри витрину",
    text: "Аня, протри витрину до 18:00",
    scope: "employee",
    assignee: {
      id: 2,
      name: "Аня Петрова",
      position: "Повар",
      department_id: 1,
    },
    candidates: [],
    department_id: 1,
    due_at: new Date(Date.now() + 3_600_000).toISOString(),
    due_kind: "time",
    priority: "normal",
    requires_photo: false,
    requires_review: false,
    unclear: [],
    ...overrides,
  };
}

function renderSheet() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <QuickTaskSheet onClose={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  parseMock.mockReset();
  createMock.mockReset();
  peopleMock.mockReset();
  peopleMock.mockResolvedValue([
    { id: 2, name: "Аня Петрова", position: "Повар", department_id: 1 },
    { id: 3, name: "Пётр Сидоров", position: "Бариста", department_id: 1 },
  ]);
});

afterEach(cleanup);

describe("быстрое поручение", () => {
  it("показывает подписи и поле до ответа сервера", () => {
    renderSheet();
    expect(screen.getByText("Скажи, что нужно сделать")).toBeTruthy();
    expect(screen.getByLabelText("Что нужно сделать")).toBeTruthy();
    expect(
      screen.getByText(/Напиши или продиктуй одной фразой/),
    ).toBeTruthy();
    // Кнопка есть сразу, но неактивна: пустую фразу отправлять некуда.
    const button = screen.getByRole("button", { name: "Создать поручение" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(parseMock).not.toHaveBeenCalled();
  });

  it("показывает, как понял, и не создаёт поручение само", async () => {
    parseMock.mockResolvedValue(draft());
    renderSheet();

    fireEvent.change(screen.getByLabelText("Что нужно сделать"), {
      target: { value: "Аня, протри витрину до 18:00" },
    });

    await waitFor(() => expect(screen.getByText("Протри витрину")).toBeTruthy());
    expect(screen.getByText("Аня Петрова")).toBeTruthy();
    expect(screen.getByText("Срок взят из фразы")).toBeTruthy();
    expect(createMock).not.toHaveBeenCalled();
  });

  it("две одинаковые Ани дают выбор, а не догадку", async () => {
    parseMock.mockResolvedValue(
      draft({
        assignee: null,
        unclear: ["assignee"],
        candidates: [
          { id: 2, name: "Аня Петрова", position: "Повар", department_id: 1 },
          { id: 4, name: "Аня Кузнецова", position: "Официант", department_id: 1 },
        ],
      }),
    );
    renderSheet();

    fireEvent.change(screen.getByLabelText("Что нужно сделать"), {
      target: { value: "Аня, протри витрину" },
    });

    await waitFor(() => expect(screen.getByText("Кто именно:")).toBeTruthy());
    const button = screen.getByRole("button", { name: "Создать поручение" });
    expect((button as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Аня Кузнецова" }));
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });

  it("отправляет срок и срочность, которые видит человек", async () => {
    const due = new Date(Date.now() + 3_600_000).toISOString();
    parseMock.mockResolvedValue(draft({ due_at: due }));
    createMock.mockResolvedValue({
      id: 7,
      title: "Протри витрину",
      due_at: due,
      status: "new",
      scope: "employee",
      assignee_name: "Аня Петрова",
    });
    renderSheet();

    fireEvent.change(screen.getByLabelText("Что нужно сделать"), {
      target: { value: "Аня, протри витрину до 18:00" },
    });
    await waitFor(() => expect(screen.getByText("Протри витрину")).toBeTruthy());
    // Помечаем срочным: в запрос должна уйти именно эта правка.
    fireEvent.click(screen.getByRole("button", { name: "Срочно" }));
    fireEvent.click(screen.getByRole("button", { name: "Создать поручение" }));

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    expect(createMock.mock.calls[0][0]).toMatchObject({
      text: "Аня, протри витрину до 18:00",
      assignee_employee_id: 2,
      due_at: due,
      priority: "high",
      requires_photo: false,
    });
    // И подтверждение видно: «создалось и исчезло» — это тревога, а не успех.
    await waitFor(() => expect(screen.getByText("Поручение создано")).toBeTruthy());
  });

  it("без распознавания речи кнопки микрофона нет", () => {
    // В jsdom `SpeechRecognition` нет — это и есть часть iOS/старых браузеров.
    renderSheet();
    expect(screen.queryByLabelText("Сказать голосом")).toBeNull();
  });

  it("с распознаванием речь дописывается в поле", async () => {
    class FakeRecognition {
      lang = "";
      continuous = false;
      interimResults = false;
      onresult: ((event: unknown) => void) | null = null;
      onerror: (() => void) | null = null;
      onend: (() => void) | null = null;
      start() {
        // Браузер отдаёт результат асинхронно — здесь тоже, чтобы проверка не
        // проходила «потому что успела».
        setTimeout(() => {
          this.onresult?.({
            results: [{ 0: { transcript: "помыть полы" } }],
          });
          this.onend?.();
        }, 0);
      }
      stop() {}
    }
    (window as unknown as { SpeechRecognition?: unknown }).SpeechRecognition =
      FakeRecognition;
    parseMock.mockResolvedValue(draft({ title: "Помыть полы" }));

    try {
      renderSheet();
      fireEvent.click(screen.getByLabelText("Сказать голосом"));
      await waitFor(() => {
        const field = screen.getByLabelText("Что нужно сделать") as HTMLTextAreaElement;
        expect(field.value).toBe("помыть полы");
      });
      await waitFor(() => expect(parseMock).toHaveBeenCalledWith("помыть полы"));
    } finally {
      delete (window as unknown as { SpeechRecognition?: unknown })
        .SpeechRecognition;
    }
  });
});
