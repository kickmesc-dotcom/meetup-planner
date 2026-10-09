// @vitest-environment jsdom
/**
 * GHG11(12): задания в ленте.
 *
 * Требование оператора:
 *  - открытые задания — манящая зелёная подсветка;
 *  - закрытые — тускнеют, но с ЧЁТКО видимым замком;
 *  - закрытые без заявок — красноватые и крупно «поучаствовало 0»;
 *  - закрытые с заявками — жёлтые, с пометкой «не смотрено»; после просмотра —
 *    «просмотрено» и затухание;
 *  - кнопка-глазик разворачивает/сворачивает подробности (как тап по записи);
 *  - скрытие/удаление — свайпом влево (плашка минуса), удаление только админу.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FeedRow, pluralRu, taskVisual } from "./FeedScreen";
import type { FeedItem, FeedTask } from "@/api/game";

afterEach(cleanup);

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("taskVisual: цвета и пометки состояния задания", () => {
  it("открытое задание — зелёное и без замка", () => {
    const v = taskVisual({ state: "open", closed: false, participants: 0, seen: false })!;
    expect(v.card).toContain("status-free");
    expect(v.badge).toContain("идёт");
    expect(v.badgeClass).toContain("var(--status-free-pill)");
    expect(v.lock).toBe(false);
    expect(v.dim).toBe(false);
    // Счётчик у идущего приёма не показываем — там ещё нечего считать.
    expect(v.count).toBe(false);
  });

  it("закрытое без заявок — красноватое, с замком и крупным счётчиком", () => {
    const v = taskVisual({ state: "empty", closed: true, participants: 0, seen: false })!;
    expect(v.card).toContain("status-busy");
    expect(v.lock).toBe(true);
    expect(v.count).toBe(true);
    expect(v.dim).toBe(true);
    expect(v.countBg).toContain("status-busy");
    // Текст плашки — темой (`text-tg-text`), а не ярким статус-цветом: на
    // светлой теме #ef4444/#22c55e/#f59e0b нечитаемы как текст.
    expect(v.badgeClass).toContain("var(--status-busy-pill)");
    expect(v.badgeClass).toContain("text-white");
  });

  it("закрытое с заявками и непросмотренное — жёлтое и не тускнеет", () => {
    const v = taskVisual({ state: "filled", closed: true, participants: 2, seen: false })!;
    expect(v.card).toContain("status-maybe");
    expect(v.badge).toContain("не смотрено");
    expect(v.badgeClass).toContain("var(--status-maybe-pill)");
    expect(v.lock).toBe(true);
    expect(v.count).toBe(true);
    expect(v.dim).toBe(false);
  });

  it("просмотренное затухает, но пока раскрыто — читается спокойно", () => {
    const task: FeedTask = { state: "filled", closed: true, participants: 1, seen: true };
    expect(taskVisual(task, false, true)!.dim).toBe(true);
    expect(taskVisual(task, true, true)!.dim).toBe(false);
    expect(taskVisual(task, false, true)!.badge).toContain("просмотрено");
  });

  it("обычная запись (без задания) тон не получает", () => {
    expect(taskVisual(undefined)).toBeNull();
  });
});

describe("pluralRu", () => {
  it("согласует числительное", () => {
    expect(pluralRu(0, "вариант", "варианта", "вариантов")).toBe("вариантов");
    expect(pluralRu(1, "вариант", "варианта", "вариантов")).toBe("вариант");
    expect(pluralRu(2, "вариант", "варианта", "вариантов")).toBe("варианта");
    expect(pluralRu(5, "вариант", "варианта", "вариантов")).toBe("вариантов");
    expect(pluralRu(11, "вариант", "варианта", "вариантов")).toBe("вариантов");
    expect(pluralRu(21, "вариант", "варианта", "вариантов")).toBe("вариант");
  });
});

// ------------------------------------------------------------------ FeedRow ---

function voiceItem(task: FeedTask, extra: Record<string, unknown> = {}): FeedItem {
  return {
    id: "voice:7",
    source: "voice",
    kind: "voice",
    icon: "🎙",
    title: "Голосовое задание",
    text: "«Кряканье утки» — +50 XP",
    at: new Date("2026-10-08T16:00:00Z").toISOString(),
    user_id: null,
    user_name: null,
    user_telegram_id: null,
    avatar_url: null,
    badges: [],
    detail: {
      task_id: 7,
      condition: "Задание: запиши голосовуху",
      reward: 50,
      closed: task.closed,
      closed_at: null,
      expires_at: null,
      submissions: [],
      task,
      ...extra,
    },
  };
}

function renderRow(item: FeedItem, isAdmin = false) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <FeedRow
        item={item}
        meId={5}
        isAdmin={isAdmin}
        onOpenUser={() => {}}
        onModerated={() => {}}
        compact
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FeedRow: задания", () => {
  it("закрытое без заявок: замок, бейдж и «поучаствовало 0»", () => {
    renderRow(
      voiceItem({ state: "empty", closed: true, participants: 0, seen: false }),
    );
    expect(screen.getByTestId("feed-task-lock")).toBeTruthy();
    expect(screen.getByTestId("feed-task-badge").textContent).toContain("без заявок");
    expect(screen.getByTestId("feed-task-count").textContent).toContain("поучаствовало 0");
  });

  it("закрытое с заявками показывает счёт и слово «вариант» в нужной форме", () => {
    renderRow(
      voiceItem({
        state: "filled",
        closed: true,
        participants: 2,
        seen: false,
      }, {
        submissions: [
          { id: 1, user_id: 6, user_name: "Сомов", duration: 5 },
          { id: 2, user_id: 9, user_name: "Митян", duration: 7 },
        ],
      }),
    );
    const count = screen.getByTestId("feed-task-count");
    expect(count.textContent).toContain("поучаствовало 2");
    expect(count.textContent).toContain("варианта");
    expect(screen.getByTestId("feed-task-badge").textContent).toContain("не смотрено");
  });

  it("открытое задание зелёное и без замка", () => {
    const { container } = renderRow(
      voiceItem({ state: "open", closed: false, participants: 0, seen: false }),
    );
    expect(container.textContent).toContain("идёт приём");
    expect(screen.queryByTestId("feed-task-lock")).toBeNull();
    expect(container.innerHTML).toContain("status-free");
  });
});

describe("FeedRow: глазик разворачивает подробности", () => {
  it("тап по глазику разворачивает и сворачивает панель", async () => {
    renderRow(
      voiceItem({ state: "open", closed: false, participants: 0, seen: false }),
    );
    const eye = screen.getByTestId("feed-eye");
    expect(eye.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(eye);
    // Раскрылось: появилось условие задания и кнопка участия.
    expect(screen.getByText(/Задание: запиши голосовуху/)).toBeTruthy();
    expect(screen.getByTestId("feed-eye").getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(screen.getByTestId("feed-eye"));
    expect(screen.queryByText(/Задание: запиши голосовуху/)).toBeNull();
  });

  it("глазик не открывает меню модерации (он переехал в свайп)", () => {
    renderRow(
      voiceItem({ state: "open", closed: false, participants: 0, seen: false }),
    );
    fireEvent.click(screen.getByTestId("feed-eye"));
    expect(screen.queryByText(/Скрыть у себя/)).toBeNull();
    expect(screen.queryByText(/🗑 Удалить/)).toBeNull();
  });

  it("разворот закрытого задания с вариантами помечает его просмотренным", async () => {
    renderRow(
      voiceItem({ state: "filled", closed: true, participants: 1, seen: false }, {
        submissions: [{ id: 3, user_id: 6, user_name: "Сомов", duration: 5 }],
      }),
    );
    expect(screen.getByTestId("feed-task-badge").textContent).toContain("не смотрено");
    fireEvent.click(screen.getByTestId("feed-eye"));
    await flush();
    expect(screen.getByTestId("feed-task-badge").textContent).toContain("просмотрено");
    // На сервер улетела пометка именно этой записи.
    const call = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(
      (c) => String(c[0]).includes("/api/game/feed/seen"),
    );
    expect(call).toBeTruthy();
    expect(JSON.parse((call![1] as RequestInit).body as string)).toEqual({
      item_id: "voice:7",
    });
  });
});

describe("FeedRow: свайп влево — скрыть/удалить", () => {
  it("плашка минуса есть у любого участника", () => {
    renderRow(voiceItem({ state: "open", closed: false, participants: 0, seen: false }));
    expect(screen.getByTestId("feed-swipe-hide").getAttribute("aria-label")).toContain(
      "Скрыть",
    );
    expect(screen.queryByTestId("feed-swipe-delete")).toBeNull();
  });

  it("удаление из ленты доступно только админу", () => {
    renderRow(
      voiceItem({ state: "open", closed: false, participants: 0, seen: false }),
      true,
    );
    expect(screen.getByTestId("feed-swipe-delete")).toBeTruthy();
  });

  it("свайп влево вытягивает карточку и открывает плашку действий", () => {
    const { container } = renderRow(
      voiceItem({ state: "open", closed: false, participants: 0, seen: false }),
    );
    const row = container.querySelector('[data-testid="feed-row"]')!;
    const sliding = row.lastElementChild as HTMLElement;
    // Пока не свайпали — плашка спрятана и карточка на месте.
    expect(sliding.style.transform).toBe("translateX(0px)");

    fireEvent.touchStart(sliding, { touches: [{ clientX: 300, clientY: 100 }] });
    fireEvent.touchMove(sliding, { touches: [{ clientX: 250, clientY: 104 }] });
    expect(sliding.style.transform).toMatch(/translateX\(-50px\)/);
    fireEvent.touchEnd(sliding);
    // Протянули больше трети — карточка «защёлкивается» в открытом виде.
    expect(sliding.style.transform).toMatch(/translateX\(-104px\)/);

    fireEvent.click(screen.getByTestId("feed-swipe-hide"));
  });

  it("вертикальный жест (скролл/пулл) карточку не двигает", () => {
    const { container } = renderRow(
      voiceItem({ state: "open", closed: false, participants: 0, seen: false }),
    );
    const sliding = (container.querySelector('[data-testid="feed-row"]')!
      .lastElementChild as HTMLElement);
    fireEvent.touchStart(sliding, { touches: [{ clientX: 200, clientY: 300 }] });
    fireEvent.touchMove(sliding, { touches: [{ clientX: 205, clientY: 200 }] });
    expect(sliding.style.transform).toBe("translateX(0px)");
  });
});
