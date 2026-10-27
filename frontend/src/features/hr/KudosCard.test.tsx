// @vitest-environment jsdom
/**
 * «Спасибо коллеге» (план, 8.4).
 *
 * Проверяем то, что человек видит и что может сломаться незаметно:
 *
 *  • карточка появляется каркасом и не ждёт сервер пустым местом;
 *  • числа недели и топ приходят из ответа, а «топ» из одного себя не
 *    показывается — это выглядело бы насмешкой, а не признанием;
 *  • лист отправляет ровно то, что выбрано (коллега + фраза), и одна кнопка
 *    заблокирована, пока никого не выбрали;
 *  • отказ сервера объясняется словами: код `already_today` → фраза, а не
 *    молчание, при котором нажатие выглядит потерянным;
 *  • когда благодарить некого, кнопки нет вовсе — «нажми и получи отказ» хуже,
 *    чем честное «коллег в подразделении нет».
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import KudosCard, { KudosSheet } from "./KudosCard";
import {
  fetchKudosPeople,
  fetchKudosWeek,
  giveKudos,
  type KudosWeek,
} from "@/api/kudos";

vi.mock("@/api/kudos", async (importOriginal) => {
  // `kudosErrorText` оставляем настоящим: проверяем перевод кодов в фразы,
  // а не заглушку.
  const actual = await importOriginal<typeof import("@/api/kudos")>();
  return {
    ...actual,
    fetchKudosWeek: vi.fn(),
    fetchKudosPeople: vi.fn(),
    giveKudos: vi.fn(),
  };
});

const weekMock = vi.mocked(fetchKudosWeek);
const peopleMock = vi.mocked(fetchKudosPeople);
const giveMock = vi.mocked(giveKudos);

function week(overrides: Partial<KudosWeek> = {}): KudosWeek {
  return {
    since: "2026-10-26",
    until: "2026-11-01",
    top: [],
    received: 0,
    given: 0,
    my_place: null,
    today_left: 5,
    max_per_day: 5,
    can_thank: 3,
    ...overrides,
  };
}

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <KudosCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  weekMock.mockReset();
  peopleMock.mockReset();
  giveMock.mockReset();
  peopleMock.mockResolvedValue([
    {
      employee_id: 2,
      display_name: "Борис",
      department_id: 1,
      position: "Су-шеф",
      badge: null,
    },
    {
      employee_id: 3,
      display_name: "Вера",
      department_id: 1,
      position: null,
      badge: null,
    },
  ]);
});

afterEach(cleanup);

describe("KudosCard", () => {
  it("показывает каркас до ответа сервера", async () => {
    let resolveWeek: (value: KudosWeek) => void = () => {};
    weekMock.mockReturnValue(
      new Promise<KudosWeek>((resolve) => {
        resolveWeek = resolve;
      }),
    );
    const { container } = renderCard();

    expect(container.querySelector('[aria-busy="true"]')).toBeTruthy();
    resolveWeek(week());
    await waitFor(() => expect(screen.getByText("Спасибо на этой неделе")).toBeTruthy());
  });

  it("показывает числа недели, топ и своё место", async () => {
    weekMock.mockResolvedValue(
      week({
        received: 2,
        given: 1,
        today_left: 4,
        my_place: 2,
        top: [
          { employee_id: 3, display_name: "Вера", department_id: 1, count: 3 },
          { employee_id: 2, display_name: "Борис", department_id: 1, count: 2 },
        ],
      }),
    );
    renderCard();

    expect(await screen.findByText("Спасибо на этой неделе")).toBeTruthy();
    expect(screen.getByText("Ты на 2 месте")).toBeTruthy();
    expect(screen.getByText("4/5")).toBeTruthy();
    expect(screen.getByText("Вера")).toBeTruthy();
    expect(screen.getByText("3 спасибо")).toBeTruthy();
  });

  it("не показывает «топ» из одного себя", async () => {
    weekMock.mockResolvedValue(
      week({
        received: 1,
        my_place: 1,
        top: [{ employee_id: 1, display_name: "Аня", department_id: 1, count: 1 }],
      }),
    );
    renderCard();

    await screen.findByText("Спасибо на этой неделе");
    expect(screen.queryByText("Аня")).toBeNull();
    // Числа при этом на месте: сотрудник видит свои благодарности.
    expect(screen.getByText("Получено")).toBeTruthy();
  });

  it("без коллег кнопки нет — вместо неё честная причина", async () => {
    weekMock.mockResolvedValue(week({ can_thank: 0 }));
    renderCard();

    await screen.findByText("Спасибо на этой неделе");
    expect(screen.queryByRole("button", { name: /Сказать спасибо/ })).toBeNull();
    expect(
      screen.getByText("Пока некого благодарить — коллег в твоём подразделении нет."),
    ).toBeTruthy();
  });

  it("падение запроса не закрывает ленту — говорит об этом строкой", async () => {
    weekMock.mockRejectedValue(new Error("network"));
    renderCard();

    expect(
      await screen.findByText(
        "Благодарности сейчас не загрузились — остальное в ленте работает.",
      ),
    ).toBeTruthy();
  });

  it("лист отправляет выбранного коллегу и фразу", async () => {
    weekMock.mockResolvedValue(week());
    giveMock.mockResolvedValue(week({ given: 1, today_left: 4 }));
    renderCard();

    fireEvent.click(await screen.findByRole("button", { name: /Сказать спасибо/ }));
    const dialog = await screen.findByRole("dialog");

    // Пока никого не выбрали — отправлять нечего.
    const submit = within(dialog).getAllByRole("button", {
      name: /Сказать спасибо/,
    }).at(-1) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    // Список коллег приходит своим запросом — ждём его, а не считаем, что
    // лист открылся с готовыми именами.
    fireEvent.click(await within(dialog).findByText("Борис"));
    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: { value: "спасибо за подмену" },
    });
    fireEvent.click(
      within(dialog).getAllByRole("button", { name: /Сказать спасибо/ }).at(-1)!,
    );

    await waitFor(() => expect(giveMock).toHaveBeenCalledWith(2, "спасибо за подмену"));
  });

  it("объясняет отказ сервера словами, а не молчанием", async () => {
    weekMock.mockResolvedValue(week());
    giveMock.mockRejectedValue({ detail: "already_today" });
    renderCard();

    fireEvent.click(await screen.findByRole("button", { name: /Сказать спасибо/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(await within(dialog).findByText("Вера"));
    fireEvent.click(
      within(dialog).getAllByRole("button", { name: /Сказать спасибо/ }).at(-1)!,
    );

    expect(
      await screen.findByRole("alert"),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Сегодня ты уже благодарил(а) этого человека — завтра можно снова.",
      ),
    ).toBeTruthy();
  });

  it("поиск в листе оставляет только совпавших", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <KudosSheet onClose={() => {}} />
      </QueryClientProvider>,
    );

    fireEvent.change(await screen.findByRole("searchbox"), {
      target: { value: "вер" },
    });
    expect(screen.getByText("Вера")).toBeTruthy();
    expect(screen.queryByText("Борис")).toBeNull();
  });
});
