// @vitest-environment jsdom
/**
 * Мастер настройки организации: на выходе с шага сохраняются ОТВЕТЫ ЭТОГО
 * ШАГА. Регрессия была дорогой и молчаливой: экран слал патч следующего шага,
 * поэтому отрасль и подразделения не доезжали до сервера. Итоговая сводка
 * показывала «Кухня, Официанты», а следующий экран — пустой список отделов, и
 * первый запуск заканчивался тупиком «Где ты работаешь?» без вариантов.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { OrgSetup } from "@/api/hr";

const saveOrgSetup = vi.fn();
const fetchDepartments = vi.fn();

vi.mock("@/api/hr", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/hr")>();
  return { ...actual, saveOrgSetup, fetchDepartments };
});

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
  can_edit: true,
};

function renderScreen(setup: OrgSetup = SETUP) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const Screen = OrgSetupScreenLazy;
  return render(
    <QueryClientProvider client={qc}>
      <Screen setup={setup} onClose={() => undefined} />
    </QueryClientProvider>,
  );
}

let OrgSetupScreenLazy: typeof import("./OrgSetupScreen").default;

beforeEach(async () => {
  saveOrgSetup.mockReset();
  fetchDepartments.mockReset().mockResolvedValue([]);
  saveOrgSetup.mockImplementation(async (patch: Record<string, unknown>) => ({
    ...SETUP,
    ...patch,
  }));
  const mod = await import("./OrgSetupScreen");
  OrgSetupScreenLazy = mod.default;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

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

    // Организация без подсказок сервера: ни готовых отделов, ни пресетов —
    // единственный случай, когда шаг остался бы пустым без каркаса. Сохранение
    // первого шага тоже возвращает ответ без пресетов (иначе `setDraft`
    // вернул бы подсказки из фикстуры и шаг перестал бы быть пустым).
    saveOrgSetup.mockImplementation(async (patch: Record<string, unknown>) => ({
      ...SETUP,
      presets: [],
      ...patch,
    }));
    renderScreen({ ...SETUP, presets: [] });
    fireEvent.click(await screen.findByRole("button", { name: "Далее" }));

    // Статика шага уже на экране, пока данных нет.
    expect(await screen.findByText("Из кого состоит команда?")).toBeTruthy();
    expect(await screen.findByTestId("org-setup-departments-skeleton")).toBeTruthy();

    resolveDeps([{ id: 7, name: "Бар", emoji: "🍸" } as Deps[number]]);
    await waitFor(() => expect(screen.getByRole("button", { name: /Бар/ })).toBeTruthy());
    expect(screen.queryByTestId("org-setup-departments-skeleton")).toBeNull();
  });

  it("с шага «Подразделения» отделы уходят вместе с флагом создания", async () => {
    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Далее" }));
    fireEvent.click(await screen.findByRole("button", { name: /Бариста/ }));
    fireEvent.click(screen.getByRole("button", { name: "Далее" }));

    await waitFor(() => expect(saveOrgSetup).toHaveBeenCalledTimes(2));
    expect(saveOrgSetup.mock.calls[1][0]).toMatchObject({
      departments: ["Бариста"],
      create_departments: true,
    });
  });
});
