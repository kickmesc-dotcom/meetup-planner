// @vitest-environment jsdom
/**
 * Экран «Языки» (план, 8.3): тумблер узбекского пакета.
 *
 * Проверяем три вещи, каждая из которых ломалась бы незаметно:
 *  - включённый по умолчанию пакет показывается включённым;
 *  - выключение уходит на сервер именно как `uz_pack: false` (иначе тумблер
 *    «щёлкал» бы, ничего не меняя);
 *  - у руководителя смены тумблер неактивен: пакет — решение владельца, и
 *    клик, который всё равно получит 403, лучше не показывать рабочим.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LanguagesScreen from "./LanguagesScreen";
import { fetchOrgSetup, saveOrgSetup, type OrgSetup } from "@/api/hr";

vi.mock("@/api/hr", () => ({
  fetchOrgSetup: vi.fn(),
  saveOrgSetup: vi.fn(),
}));

const fetchMock = vi.mocked(fetchOrgSetup);
const saveMock = vi.mocked(saveOrgSetup);

const SETUP: OrgSetup = {
  done: true,
  industry: "restaurant",
  headcount: "10_30",
  departments: ["Кухня"],
  sections: ["team"],
  profile_visibility: "colleagues",
  cross_department_watch: false,
  allow_hide_last_seen: true,
  allow_hide_media: true,
  uz_pack: true,
  presets: [],
  can_edit: true,
  can_manage_packs: true,
};

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <LanguagesScreen onBack={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  saveMock.mockReset();
});
afterEach(cleanup);

describe("LanguagesScreen", () => {
  it("показывает пакет включённым по умолчанию", async () => {
    fetchMock.mockResolvedValue(SETUP);
    renderScreen();
    const sw = await screen.findByRole("switch");
    await waitFor(() => expect((sw as HTMLButtonElement).disabled).toBe(false));
    expect(sw.getAttribute("aria-checked")).toBe("true");
  });

  it("выключение уходит на сервер как uz_pack: false", async () => {
    fetchMock.mockResolvedValue(SETUP);
    saveMock.mockResolvedValue({ ...SETUP, uz_pack: false });
    renderScreen();
    const sw = await screen.findByRole("switch");
    await waitFor(() => expect((sw as HTMLButtonElement).disabled).toBe(false));

    fireEvent.click(sw);

    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1));
    expect(saveMock).toHaveBeenCalledWith({ uz_pack: false });
    await waitFor(() =>
      expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("false"),
    );
  });

  it("для руководителя смены тумблер неактивен и объяснено почему", async () => {
    fetchMock.mockResolvedValue({ ...SETUP, can_manage_packs: false });
    renderScreen();
    const sw = await screen.findByRole("switch");
    await waitFor(() => expect((sw as HTMLButtonElement).disabled).toBe(true));

    fireEvent.click(sw);
    expect(saveMock).not.toHaveBeenCalled();
    expect(
      screen.getByText(/только владелец организации/i),
    ).toBeTruthy();
  });
});
