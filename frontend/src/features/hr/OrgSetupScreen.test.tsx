// @vitest-environment jsdom
/**
 * Мастер настройки организации.
 *
 * Две вещи, на которых он ломался дорого и молчаливо:
 *
 * * экран слал патч следующего шага, поэтому отрасль и подразделения не
 *   доезжали до сервера — итог показывал «Кухня, Официанты», а следующий
 *   экран пустой список отделов;
 * * мастер закрывался «готово», не заводя ни людей, ни графика: руководитель
 *   уверен, что настроил, сотрудник открывает приложение и видит нечего.
 *
 * Поэтому здесь проверяются не пиксели, а следы: что ушло на сервер с каждого
 * шага и что мастер показывает на шаге «Люди», «График» и в сводке.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { OrgSetup } from "@/api/hr";
// Статический импорт, а не `await import()` в beforeEach: в полном
// параллельном прогоне динамический импорт не укладывался в 10 с таймаута
// хука, и тест падал «Hook timed out» без единой проверки.
import OrgSetupScreen from "./OrgSetupScreen";

// `vi.hoisted`: фабрики `vi.mock` поднимаются выше импортов, поэтому моки, на
// которые они ссылаются, должны существовать уже на этом этапе — иначе
// статический импорт экрана падает на `cannot access before initialization`.
const {
  saveOrgSetup,
  fetchDepartments,
  fetchOrgSetupProgress,
  createInvitation,
  saveShiftTemplate,
  fetchShiftWeek,
  applyShiftTemplate,
} = vi.hoisted(() => ({
  saveOrgSetup: vi.fn(),
  fetchDepartments: vi.fn(),
  fetchOrgSetupProgress: vi.fn(),
  createInvitation: vi.fn(),
  saveShiftTemplate: vi.fn(),
  fetchShiftWeek: vi.fn(),
  applyShiftTemplate: vi.fn(),
}));

vi.mock("@/api/hr", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/hr")>();
  return {
    ...actual,
    saveOrgSetup,
    fetchDepartments,
    fetchOrgSetupProgress,
  };
});

vi.mock("@/api/orgs", () => ({ createInvitation }));

vi.mock("@/api/shifts", () => ({
  saveShiftTemplate,
  fetchShiftWeek,
  applyShiftTemplate,
}));

const SETUP: OrgSetup = {
  done: false,
  industry: "cafe",
  headcount: "10_30",
  departments: [],
  sections: ["team", "reports"],
  profile_visibility: "colleagues",
  cross_department_watch: false,
  allow_hide_last_seen: true,
  allow_hide_media: true,
  uz_pack: true,
  can_manage_packs: true,
  presets: [
    { name: "Кухня", emoji: "🍳" },
    { name: "Бариста", emoji: "☕" },
  ],
  positions: ["Бариста", "Повар"],
  can_edit: true,
};

function renderScreen(setup: OrgSetup = SETUP) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const Screen = OrgSetupScreen;
  return render(
    <QueryClientProvider client={qc}>
      <Screen setup={setup} onClose={() => undefined} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  saveOrgSetup.mockReset();
  fetchDepartments.mockReset().mockResolvedValue([]);
  fetchOrgSetupProgress.mockReset();
  createInvitation.mockReset();
  saveShiftTemplate.mockReset();
  fetchShiftWeek.mockReset().mockResolvedValue({
    start: "2026-11-02",
    end: "2026-11-08",
    today: "2026-11-02",
    can_edit: true,
    statuses: [],
    departments: [],
    people: [],
    shifts: [],
  });
  applyShiftTemplate.mockReset().mockResolvedValue({ saved: 0, skipped: 0 });
  saveOrgSetup.mockImplementation(async (patch: Record<string, unknown>) => ({
    ...SETUP,
    ...patch,
  }));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** Пройти мастер до нужного шага кнопкой «Далее». */
async function passSteps(count: number) {
  for (let index = 0; index < count; index += 1) {
    fireEvent.click(await screen.findByRole("button", { name: "Далее" }));
  }
}

describe("OrgSetupScreen", () => {
  it("с шага «Предприятие» уходят ответы про предприятие, а не про отделы", async () => {
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Далее" }));

    await waitFor(() => expect(saveOrgSetup).toHaveBeenCalledTimes(1));
    expect(saveOrgSetup.mock.calls[0][0]).toEqual({
      industry: "cafe",
      headcount: "10_30",
    });
  });

  it("пока отделы едут, на шаге «Подразделения» виден каркас, а не пустота", async () => {
    // Медленный контур: список отделов отвечает не сразу. Пустой блок в этот
    // момент читался как «отделов нет» — и руководитель жал «Пропустить» на
    // самом важном шаге мастера.
    type Deps = Awaited<ReturnType<typeof fetchDepartments>>;
    let resolveDeps: (value: Deps) => void = () => undefined;
    fetchDepartments.mockReturnValue(
      new Promise<Deps>((resolve) => {
        resolveDeps = resolve;
      }),
    );

    saveOrgSetup.mockImplementation(async (patch: Record<string, unknown>) => ({
      ...SETUP,
      presets: [],
      ...patch,
    }));
    renderScreen({ ...SETUP, presets: [] });
    fireEvent.click(await screen.findByRole("button", { name: "Далее" }));

    expect(await screen.findByText("Из кого состоит команда?")).toBeTruthy();
    expect(await screen.findByTestId("org-setup-departments-skeleton")).toBeTruthy();

    resolveDeps([{ id: 7, name: "Бар", emoji: "🍸" } as Deps[number]]);
    await waitFor(() => expect(screen.getByRole("button", { name: /Бар/ })).toBeTruthy());
    expect(screen.queryByTestId("org-setup-departments-skeleton")).toBeNull();
  });

  it("с шага «Подразделения» отделы уходят вместе с флагом создания", async () => {
    renderScreen();
    await passSteps(1);
    fireEvent.click(await screen.findByRole("button", { name: /Бариста/ }));
    fireEvent.click(screen.getByRole("button", { name: "Далее" }));

    await waitFor(() => expect(saveOrgSetup).toHaveBeenCalledTimes(2));
    expect(saveOrgSetup.mock.calls[1][0]).toMatchObject({
      departments: ["Бариста"],
      create_departments: true,
    });
  });

  it("на шаге «Люди» ссылка создаётся и показывается, почту можно не вводить", async () => {
    createInvitation.mockResolvedValue({
      id: 11,
      email: null,
      role: "staff",
      created_at: null,
      expires_at: "2026-11-09T00:00:00Z",
      link: "https://semitaskbot.pages.dev/invite?token=abc",
    });
    renderScreen();
    await passSteps(2);

    expect(await screen.findByText("Кого позвать первым?")).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "Создать приглашение" }));

    await waitFor(() => expect(createInvitation).toHaveBeenCalledTimes(1));
    // Роль всегда «сотрудник»: владельца себе мастер не приглашает.
    expect(createInvitation.mock.calls[0][0]).toMatchObject({
      email: null,
      role: "staff",
      position: null,
    });
    expect(
      (await screen.findByTestId("org-setup-invite-link")).textContent,
    ).toContain("/invite?token=abc");
  });

  it("на шаге «График» сохраняется шаблон недели с рабочими днями", async () => {
    saveShiftTemplate.mockResolvedValue({
      id: 5,
      name: "Смена 5/2",
      department_id: null,
      department_name: null,
      days: [],
    });
    renderScreen();
    await passSteps(3);

    expect(await screen.findByText("Рабочая неделя")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить шаблон недели" }));

    await waitFor(() => expect(saveShiftTemplate).toHaveBeenCalledTimes(1));
    const body = saveShiftTemplate.mock.calls[0][0];
    expect(body.name).toBe("Смена 5/2");
    const working = body.days.filter(
      (day: { status: string }) => day.status === "planned",
    );
    expect(working).toHaveLength(5);
    expect(await screen.findByTestId("org-setup-schedule-done")).toBeTruthy();
    // Людей ещё нет — смены не ставим, но и не обещаем, что поставили.
    expect(fetchShiftWeek).toHaveBeenCalledTimes(1);
    expect(applyShiftTemplate).not.toHaveBeenCalled();
  });

  it("на последнем шаге сводка показывает, что реально завелось", async () => {
    fetchOrgSetupProgress.mockResolvedValue({
      departments: 2,
      people: 3,
      invites_pending: 1,
      shift_templates: 1,
      checklists: [
        { title: "Открытие смены", kind: "shift", department: "Кухня", items: 5 },
      ],
    });
    renderScreen();
    await passSteps(6);

    expect(await screen.findByText("Что уже готово")).toBeTruthy();
    await waitFor(() => expect(fetchOrgSetupProgress).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Сотрудники: 3/)).toBeTruthy();
    expect(
      screen.getByText(
        "Первый чек-лист уже ждёт сотрудников в разделе «Чек-лист».",
      ),
    ).toBeTruthy();
  });
});
