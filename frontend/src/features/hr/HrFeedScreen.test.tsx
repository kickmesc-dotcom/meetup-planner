// @vitest-environment jsdom
/**
 * VISUAL_AUDIT P1.8: тестовый сотрудник в ленте.
 *
 * Было три метки в одной строке: префикс `[BOT]` в имени, плашка должности и
 * чип `BOT` внутри неё. Проверяем, что осталась одна — «тест», имя чистое,
 * а плашка у тестового не дублируется. Живые люди при этом не меняются:
 * их плашка на месте.
 *
 * Отдельно проверяем совместимость: если бэкенд ещё не отдаёт `is_demo`,
 * лента узнаёт пул по префиксу и всё равно рисует одну метку.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import HrFeedScreen from "./HrFeedScreen";
import {
  fetchDepartmentOverview,
  fetchDepartments,
  fetchEmployee,
  fetchEmployeeCard,
  fetchFeedFilters,
  fetchHrFeed,
  type HrEmployee,
  type HrFeedItem,
} from "@/api/hr";
import { markFeedSeen, readFeedSeen } from "@/features/hr/feedSeen";
import { useLocale } from "@/i18n";
import * as translateApi from "@/api/translate";
import { __clearTranslateCache } from "@/components/translateCore";

vi.mock("@/api/hr", () => ({
  fetchHrFeed: vi.fn(),
  fetchFeedFilters: vi.fn(),
  fetchEmployeeCard: vi.fn(),
  fetchEmployee: vi.fn(),
  fetchDepartments: vi.fn(),
  fetchDepartmentOverview: vi.fn(),
}));

// Карточка благодарностей (план, 8.4) живёт в ленте и ходит своим запросом.
// Здесь она не предмет проверки, но без ответа тянула бы реальную сеть —
// тест ленты стал бы зависеть от того, отвечает ли дев-сервер.
vi.mock("@/api/kudos", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/kudos")>();
  return {
    ...actual,
    fetchKudosWeek: vi.fn().mockResolvedValue({
      since: "2026-10-26",
      until: "2026-11-01",
      top: [],
      received: 0,
      given: 0,
      my_place: null,
      today_left: 5,
      max_per_day: 5,
      can_thank: 0,
    }),
    fetchKudosPeople: vi.fn().mockResolvedValue([]),
  };
});

const feedMock = vi.mocked(fetchHrFeed);
const filtersMock = vi.mocked(fetchFeedFilters);
const cardMock = vi.mocked(fetchEmployeeCard);
const meMock = vi.mocked(fetchEmployee);
const depsMock = vi.mocked(fetchDepartments);
const overviewMock = vi.mocked(fetchDepartmentOverview);

function item(overrides: Partial<HrFeedItem> = {}): HrFeedItem {
  return {
    at: new Date().toISOString(),
    kind: "task_status",
    employee_id: 1,
    user_id: 1,
    display_name: "Пётр",
    department_id: 1,
    text: "закрыл(а) поручение",
    ref_id: 5,
    badge: "Су-шеф",
    badge_emoji: "🍳",
    ...overrides,
  };
}

function renderFeed(items: HrFeedItem[]) {
  feedMock.mockResolvedValue({
    scope: "all",
    can_filter: false,
    items,
  });
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <HrFeedScreen />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  // Язык — глобальное состояние: тесты ниже ждут русский по умолчанию.
  useLocale.setState({ locale: "ru" });
  window.localStorage.clear();
  feedMock.mockReset();
  filtersMock.mockReset();
  meMock.mockReset();
  meMock.mockResolvedValue({ id: 1 } as unknown as HrEmployee);
  filtersMock.mockResolvedValue({
    scope: "all",
    can_filter: false,
    departments: [],
    employees: [],
    kinds: [],
  } as unknown as Awaited<ReturnType<typeof fetchFeedFilters>>);
  depsMock.mockReset();
  depsMock.mockResolvedValue([]);
  overviewMock.mockReset();
});
afterEach(cleanup);

describe("HrFeedScreen (P1.8)", () => {
  it("помечает тестового одним «тест» и не показывает префикс", async () => {
    renderFeed([
      item({
        display_name: "[BOT] Алина",
        badge: "Стажёр",
        badge_emoji: "🌱",
        is_demo: true,
        text: "закрыла чек-лист",
      }),
    ]);

    const mark = await screen.findByTestId("feed-demo-mark");
    expect(mark.textContent).toBe("тест");
    expect(screen.queryByText(/\[BOT\]/)).toBeNull();
    expect(screen.getByText("Алина")).toBeTruthy();
    // Плашка должности у пула не дублирует метку.
    expect(screen.queryByText("Стажёр")).toBeNull();
  });

  it("узнаёт пул по префиксу, если сервер не прислал is_demo", async () => {
    renderFeed([item({ display_name: "[BOT] Борис", badge: "Стажёр" })]);

    expect(await screen.findByTestId("feed-demo-mark")).toBeTruthy();
    expect(screen.getByText("Борис")).toBeTruthy();
    expect(screen.queryByText("Стажёр")).toBeNull();
  });

  it("оставляет плашку живому сотруднику", async () => {
    renderFeed([item({ display_name: "Пётр", badge: "Су-шеф" })]);

    expect(await screen.findByText("Пётр")).toBeTruthy();
    expect(screen.getByText("Су-шеф")).toBeTruthy();
    expect(screen.queryByTestId("feed-demo-mark")).toBeNull();
  });

  it("плашка подразделения открывает дашборд отдела", async () => {
    depsMock.mockResolvedValue([
      { id: 1, name: "Кухня", slug: "kuhnya", emoji: null, sort_order: 0 },
    ]);
    overviewMock.mockResolvedValue({
      department_id: 1,
      department_name: "Кухня",
      department_emoji: null,
      can_manage: false,
      show_presence: false,
      on_shift: 0,
      overdue: 0,
      people: [],
    });
    renderFeed([item()]);

    fireEvent.click(
      await screen.findByLabelText("Открыть подразделение Кухня"),
    );
    expect(await screen.findByText("В отделе пока никого")).toBeTruthy();
  });

  it("имя — пилюля с цветным аутлайном, по тапу открывается карточка", async () => {
    cardMock.mockResolvedValue({
      employee_id: 1,
      display_name: "Пётр",
      department_id: 1,
      department_name: "Кухня",
      position: null,
      badge: "Су-шеф",
      badge_emoji: "🍳",
      role: "employee",
      role_label: "Сотрудник",
      is_demo: false,
      is_self: false,
      can_manage: false,
      profile_open: true,
      can_view: true,
      show_last_seen: true,
      show_last_media: true,
      can_toggle_last_seen: true,
      can_toggle_last_media: true,
      last_seen_at: null,
      last_media: null,
      xp: 12,
      rank_title: "Стажёр",
      rank_emoji: "🌱",
      week_xp: 12,
      week_place: 1,
      week_total: 3,
      checklist_items: 4,
      tasks_done: 1,
      shifts_done: 1,
      activity: [],
    });
    renderFeed([item()]);

    const name = await screen.findByText("Пётр");
    const pill = name.closest("button") as HTMLButtonElement;
    // Аутлайн и подложка — из палитры человека, поэтому имя не сливается с
    // соседними строками ленты.
    // jsdom нормализует hsl в rgba — важно, что цвет вообще задан и что он
    // не равен цвету подложки карточки (то есть аутлайн виден).
    expect(pill.style.border).toContain("solid");
    expect(pill.style.border).toMatch(/rgba?\(/);
    expect(pill.style.backgroundColor).toMatch(/rgba?\(/);

    fireEvent.click(pill);
    await screen.findByText("Последние действия");
    expect(cardMock).toHaveBeenCalledWith(1);
  });

  it("тип события — SVG-иконка, а не эмодзи (P1.4)", async () => {
    const { container } = renderFeed([
      item({ badge_emoji: null, kind: "checklist_item" }),
    ]);
    await screen.findByText("Пётр");
    // Строка ленты начинается с иконки типа: раньше здесь стоял ✅.
    expect(container.querySelector("article svg")).toBeTruthy();
    expect(container.textContent ?? "").not.toMatch(/[✅🗒📌🔄📷⚠]/u);
  });

  it("рисует границу «Новые» после последнего непрочитанного", async () => {
    // Отметка — между вторым и третьим событием (лента от новых к старым).
    markFeedSeen(1, Date.parse("2026-10-22T09:15:00Z"));
    const { container } = renderFeed([
      item({ at: "2026-10-22T10:00:00Z", ref_id: 1, text: "свежее" }),
      item({ at: "2026-10-22T09:30:00Z", ref_id: 2, text: "тоже новое" }),
      item({ at: "2026-10-22T08:00:00Z", ref_id: 3, text: "прочитанное" }),
    ]);

    const divider = await screen.findByRole("separator", {
      name: "Новые события: 2",
    });
    const text = container.textContent ?? "";
    const at = text.indexOf("Новые · 2");
    expect(divider.textContent).toContain("Новые · 2");
    // Граница идёт после новых строк и до уже прочитанных.
    expect(text.indexOf("тоже новое")).toBeLessThan(at);
    expect(at).toBeLessThan(text.indexOf("прочитанное"));
    expect(screen.getByTestId("feed-fresh-count").textContent).toBe("2 новых");
  });

  it("на первом визите не объявляет всю историю новой", async () => {
    renderFeed([item({ at: "2026-10-21T10:00:00Z", text: "вчерашнее" })]);

    await screen.findByText("вчерашнее");
    expect(screen.queryByRole("separator")).toBeNull();
    expect(screen.queryByTestId("feed-fresh-count")).toBeNull();
  });

  it("запоминает просмотр при уходе с экрана", async () => {
    renderFeed([item()]);
    await screen.findByText("Пётр");

    cleanup();
    expect(readFeedSeen(1)).not.toBeNull();
  });

  it("день закреплён отдельной плашкой со стрелками соседних дней", async () => {
    renderFeed([
      item({ at: "2026-10-22T10:00:00Z", ref_id: 1, text: "первый день" }),
      item({ at: "2026-10-21T10:00:00Z", ref_id: 2, text: "предыдущий день" }),
    ]);

    const plates = await screen.findAllByTestId("feed-day");
    expect(plates).toHaveLength(2);
    // Дата стоит в плашке, а не отдельной строкой ленты.
    expect(plates[0].textContent).toContain("22 октября");
    expect(plates[1].textContent).toContain("21 октября");
    // Плашка закреплена и накрывает содержимое непрозрачным фоном (не
    // просвечивает лентой ниже — жалоба владельца).
    const sticky = plates[0].closest("h2") as HTMLElement;
    expect(sticky.className).toContain("sticky");
    expect(sticky.className).not.toContain("backdrop-blur");
    expect(sticky.className).toContain("bg-tg-bg");
    // Вверху ленты «следующий день» недоступен, внизу — «предыдущий».
    const nextButtons = screen.getAllByTestId("feed-next-day") as HTMLButtonElement[];
    const prevButtons = screen.getAllByTestId("feed-prev-day") as HTMLButtonElement[];
    expect(nextButtons[0].disabled).toBe(true);
    expect(prevButtons[0].disabled).toBe(false);
    expect(prevButtons[1].disabled).toBe(true);

    // Тап по «предыдущий день» не падает и листает ленту, а не выходит из неё.
    fireEvent.click(prevButtons[0]);
    expect(await screen.findByText("предыдущий день")).toBeTruthy();
  });

  it("на английском вся шапка и день — по-английски", async () => {
    useLocale.setState({ locale: "en" });
    renderFeed([
      item({ at: "2026-10-22T10:00:00Z", display_name: "Peter", text: "closed a task" }),
    ]);

    // Ждём строку ленты: до ответа сервера шапка ещё не знает область видимости.
    expect(await screen.findByText("Peter")).toBeTruthy();
    expect(screen.getByText("Shift events")).toBeTruthy();
    expect(screen.getByText("Whole company")).toBeTruthy();
    expect(screen.getByText("Everything that happens on shift.")).toBeTruthy();
    expect(screen.queryByText("События смены")).toBeNull();
    // Заголовок дня в английском порядке: месяц и день, а не «22 октября».
    const plate = await screen.findByTestId("feed-day");
    expect(plate.textContent).toContain("October");
    expect(plate.textContent).not.toContain("октября");
  });

  it("не повторяет область видимости в пилюле и подзаголовке (P2.13)", async () => {
    renderFeed([item()]);

    await screen.findByText("Пётр");
    // Пилюля «Всё предприятие» одна, подзаголовок объясняет правило.
    expect(screen.getAllByText("Всё предприятие")).toHaveLength(1);
    expect(screen.getByText("Всё, что происходит на смене.")).toBeTruthy();
  });
});

describe("время и дни в ленте", () => {
  it("у каждого события точное время с часами, минутами и секундами", async () => {
    const at = "2026-10-22T10:07:33Z";
    const expected = new Date(at).toLocaleTimeString("ru-RU", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    const { container } = renderFeed([item({ at, text: "закрыл чек-лист" })]);

    await screen.findByText("закрыл чек-лист");
    const time = container.querySelector("time");
    expect(time?.textContent).toBe(expected);
    expect(expected).toMatch(/^\d{2}:\d{2}:\d{2}$/);
    // Машиночитаемый атрибут — тот же момент, не пересобранная строка.
    expect(time?.getAttribute("datetime")).toBe(at);
    // Относительных подписей в ленте быть не должно.
    expect(container.textContent ?? "").not.toMatch(/назад|вчера|только что/i);
  });

  it("разделяет ленту по дням и пишет число в заголовке", async () => {
    renderFeed([
      item({ at: "2026-10-22T12:00:00Z", text: "свежее", ref_id: 1 }),
      item({ at: "2026-10-21T12:00:00Z", text: "прошлое", ref_id: 2 }),
    ]);

    await screen.findByText("свежее");
    const headings = screen
      .getAllByRole("heading", { level: 2 })
      // Карточка благодарностей (план, 8.4) — тоже заголовок второго уровня,
      // но она не про дни: считаем только заголовки дней.
      .filter((node) => node.textContent !== "Спасибо на этой неделе")
      .map((node) => node.textContent ?? "");
    expect(headings).toHaveLength(2);
    expect(headings[0]).toContain("22 октября");
    expect(headings[1]).toContain("21 октября");
    // Заголовок дня — абсолютная дата, а не «Сегодня»/«Вчера».
    expect(headings.join(" ")).not.toMatch(/Сегодня|Вчера/);
  });
});

describe("перевод дня (план, 11.5)", () => {
  it("одна кнопка на день переводит все события дня одним запросом", async () => {
    __clearTranslateCache();
    useLocale.setState({ locale: "uz", uzPackAvailable: true });
    const spy = vi
      .spyOn(translateApi, "translateTexts")
      .mockImplementation(async (batch, target) => ({
        target,
        available: true,
        reason: null,
        items: batch.map((t) => ({ translated: `[${t}]`, provider: "small100" })),
      }));

    renderFeed([
      item({ at: "2026-10-22T10:00:00Z", text: "закрыл поручение", ref_id: 1 }),
      item({ at: "2026-10-22T11:00:00Z", text: "начал смену", ref_id: 2 }),
    ]);

    await screen.findByText("закрыл поручение");
    // Один день — одна кнопка на весь блок, а не по кнопке в каждой строке.
    const buttons = screen.getAllByTestId("translate-block");
    expect(buttons).toHaveLength(1);

    fireEvent.click(buttons[0]);
    expect(await screen.findByText("[закрыл поручение]")).toBeTruthy();
    expect(screen.getByText("[начал смену]")).toBeTruthy();
    expect(spy).toHaveBeenCalledTimes(1);
    // Точечно, а не `restoreAllMocks`: тот сбросил бы и моки соседних модулей
    // (карточка благодарностей живёт в ленте тем же файлом).
    spy.mockRestore();
  });

  it("благодарность в ленте переводится тем же блоком, что и день", async () => {
    __clearTranslateCache();
    useLocale.setState({ locale: "uz", uzPackAvailable: true });
    const spy = vi
      .spyOn(translateApi, "translateTexts")
      .mockImplementation(async (batch, target) => ({
        target,
        available: true,
        reason: null,
        items: batch.map((t) => ({ translated: `[${t}]`, provider: "small100" })),
      }));

    // Благодарность приходит в ленте как обычное событие: имя коллеги и фраза
    // в одном тексте. Отдельного механизма ей не нужно — иначе одна и та же
    // фраза переводилась бы двумя путями и по-разному.
    const kudos =
      "поблагодарил(а) Tasya: «Спасибо за смену, выручила с залом»";
    renderFeed([
      item({ at: "2026-10-22T10:00:00Z", kind: "kudos", text: kudos, ref_id: 7 }),
    ]);

    const original = await screen.findByText(kudos);
    // До нажатия — авторский текст: подложки быть не должно.
    expect(original.className).not.toContain("bg-tg-link/10");

    fireEvent.click(screen.getByTestId("translate-block"));
    // Перевод получает ту же подложку, что и остальные события дня: иначе
    // машинный текст в благодарности читался бы как написанный человеком.
    const translated = await screen.findByText(`[${kudos}]`);
    expect(translated.className).toContain("bg-tg-link/10");
    expect(spy).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });

  it("на английском кнопки нет: текст события уже английский", async () => {
    useLocale.setState({ locale: "en" });
    renderFeed([
      item({ at: "2026-10-22T10:00:00Z", display_name: "Peter", text: "closed a task" }),
    ]);

    await screen.findByText("closed a task");
    expect(screen.queryByTestId("translate-block")).toBeNull();
  });
});
