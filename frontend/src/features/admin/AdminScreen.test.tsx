// @vitest-environment jsdom
/**
 * VISUAL_AUDIT P1.9: админка — 17 карточек одним списком.
 *
 * Проверяем три обещания:
 *  - поиск фильтрует по названию/подписи и честно говорит, что ничего не нашёл;
 *  - разделы, которые открывали, переезжают в «Частое» (а не дублируются ниже);
 *  - открытие раздела увеличивает счётчик в localStorage, по нему и строится
 *    «Частое» при следующем заходе.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AdminScreen from "./AdminScreen";
import { useUI } from "@/store/ui";
import { fetchDashboard, type HrDashboard } from "@/api/hr";

vi.mock("@/api/hr", () => ({ fetchDashboard: vi.fn() }));
// Подраздел не предмет теста: важно, что переход произошёл.
vi.mock("./AppTextsScreen", () => ({ default: () => <div>тексты-экран</div> }));

const dashboardMock = vi.mocked(fetchDashboard);

/** Пустая сводка: числа, которые нужны тесту, он подставляет сам. */
const EMPTY_DASHBOARD: HrDashboard = {
  work_date: "2026-11-04",
  scope: "all",
  departments: [],
  employees: [],
  attention: [],
  activity: [],
  total_employees: 0,
  shifts_started: 0,
  shifts_done: 0,
  tasks_open: 0,
  tasks_overdue: 0,
  open_issues: 0,
};

const USAGE_KEY = "admin.usage.v1";

/**
 * `platform: true` — глазa админа платформы (видны системные разделы). По
 * умолчанию кабинет открывается владельцу организации, и системных карточек
 * там нет: см. отдельный тест ниже.
 */
function renderScreen(platform = true, canManage = false) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AdminScreen users={[]} platform={platform} canManage={canManage} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  // Раздел кабинета теперь лежит в сторе (его переключает и нижняя полоса
  // зоны управления), поэтому тесты не должны начинать с чужого раздела.
  useUI.setState({ adminSection: "root" });
  dashboardMock.mockReset();
  dashboardMock.mockResolvedValue(EMPTY_DASHBOARD);
});
afterEach(cleanup);

describe("AdminScreen (P1.9)", () => {
  it("показывает сводку внимания первым экраном", async () => {
    // Пункт плана «качество жизни»: числа не должны прятаться в разделе —
    // иначе руководитель снова собирает их глазами по трём экранам.
    dashboardMock.mockResolvedValue({
      ...EMPTY_DASHBOARD,
      total_employees: 4,
      shifts_started: 2,
      tasks_overdue: 2,
      open_issues: 1,
    });
    renderScreen();

    const strip = await screen.findByTestId("attention-strip");
    // Сначала на месте стоит каркас загрузки с тем же testid — ждём ответ.
    await waitFor(() =>
      expect(strip.textContent).toContain("Смена: 2 из 4 начали"),
    );
    expect(strip.textContent).toContain("Просрочено");
    expect(strip.textContent).toContain("Проблемы");
  });

  it("делит «Смену и люди» на подгруппы без потери карточек", () => {
    renderScreen();

    const shift = screen.getByTestId("admin-subgroup-shift");
    expect(within(shift).getByText("Чек-листы")).toBeTruthy();
    expect(within(shift).getByText("Поручения")).toBeTruthy();
    expect(within(shift).getByText("Журнал событий")).toBeTruthy();

    const people = screen.getByTestId("admin-subgroup-people");
    expect(within(people).getByText("Сотрудники")).toBeTruthy();
    expect(within(people).getByText("Приглашения")).toBeTruthy();
    expect(within(people).getByText("Загрузить из таблицы")).toBeTruthy();

    const content = screen.getByTestId("admin-subgroup-content");
    expect(within(content).getByText("Вид ленты")).toBeTruthy();
    expect(within(content).getByText("Языки")).toBeTruthy();
    expect(within(content).getByText("Пакет отрасли")).toBeTruthy();

    // 13 карточек ровно по одному разу: подгруппы — навигация, а не фильтр.
    const buttons = [shift, people, content].flatMap((group) =>
      Array.from(group.querySelectorAll("button")),
    );
    expect(buttons).toHaveLength(13);
  });

  it("ищет по названию раздела и убирает остальные", () => {
    renderScreen();

    const search = screen.getByTestId("admin-search") as HTMLInputElement;
    fireEvent.change(search, { target: { value: "чек" } });

    expect(screen.getByText("Чек-листы")).toBeTruthy();
    expect(screen.queryByText("Прокси")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Найдено: 1");
  });

  it("честно сообщает о пустом поиске и сбрасывается", () => {
    renderScreen();

    fireEvent.change(screen.getByTestId("admin-search"), {
      target: { value: "иии" },
    });
    expect(screen.queryByText("Прокси")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Ничего не нашли");

    fireEvent.click(screen.getByText("Сбросить поиск"));
    expect(screen.getByText("Прокси")).toBeTruthy();
  });

  it("поднимает частые разделы вверх без дублей", () => {
    localStorage.setItem(USAGE_KEY, JSON.stringify({ texts: 4 }));
    renderScreen();

    expect(screen.getByText("Частое")).toBeTruthy();
    // Раздел переехал, а не скопировался: одна карточка и нет пустой группы.
    expect(screen.getAllByText("Тексты приложения")).toHaveLength(1);
    expect(screen.queryByText("Тексты")).toBeNull();
  });

  it("владельцу организации не показывает системные разделы платформы", () => {
    renderScreen(false);

    expect(screen.getByText("Чек-листы")).toBeTruthy();
    expect(screen.getByText("Приглашения")).toBeTruthy();
    expect(screen.queryByText("Прокси")).toBeNull();
    expect(screen.queryByText("Рестарт Space")).toBeNull();
    expect(screen.queryByText("Тексты приложения")).toBeNull();
  });

  it("держит документы смены в кабинете у того, кто ими управляет", () => {
    // 02.11.2026: меню, график и методички сотрудник читает у себя, а правит
    // руководитель — поэтому правка живёт в зоне управления, а не в экране
    // сотрудника «по совместительству».
    renderScreen(false, true);
    expect(screen.getByText("Материалы")).toBeTruthy();
    expect(screen.getByText("Стандарты")).toBeTruthy();
  });

  it("не показывает документы тому, кому управлять нечем", () => {
    renderScreen(false, false);
    expect(screen.queryByText("Материалы")).toBeNull();
    expect(screen.queryByText("Стандарты")).toBeNull();
    // Сотрудник читает их в своём профиле — из кабинета они ему не нужны.
    expect(screen.getByText("Чек-листы")).toBeTruthy();
  });

  it("открывает настройки и уводит из них в разделы вида", () => {
    // Язык и тема переехали сюда из шапки зоны управления: в шапке они стояли
    // рядом с вкладками зон и читались как их продолжение.
    useUI.setState({ adminSection: "settings" });
    renderScreen();

    expect(screen.getByTestId("language-switcher")).toBeTruthy();
    expect(screen.getByTestId("theme-switcher")).toBeTruthy();

    fireEvent.click(screen.getByText("Вид ленты"));
    expect(useUI.getState().adminSection).toBe("feed-settings");
  });

  it("прячет системные тексты от владельца организации", () => {
    useUI.setState({ adminSection: "settings" });
    renderScreen(false, true);

    expect(screen.queryByText("Тексты приложения")).toBeNull();
  });

  it("запоминает открытый раздел в localStorage", () => {
    renderScreen();

    fireEvent.click(screen.getByText("Тексты приложения"));

    expect(screen.getByText("тексты-экран")).toBeTruthy();
    const stored = JSON.parse(localStorage.getItem(USAGE_KEY) ?? "{}");
    expect(stored.texts).toBe(1);
  });
});
