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
  presets: [
    { name: "Кухня", emoji: "🍳" },
    { name: "Бариста", emoji: "☕" },
  ],
  can_edit: true,
};

function renderScreen() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <OrgSetupScreenLazy />
    </QueryClientProvider>,
  );
}

let OrgSetupScreenLazy: () => JSX.Element;

beforeEach(async () => {
  saveOrgSetup.mockReset();
  fetchDepartments.mockReset().mockResolvedValue([]);
  saveOrgSetup.mockImplementation(async (patch: Record<string, unknown>) => ({
    ...SETUP,
    ...patch,
  }));
  const mod = await import("./OrgSetupScreen");
  OrgSetupScreenLazy = () => <mod.default setup={SETUP} onClose={() => undefined} />;
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
