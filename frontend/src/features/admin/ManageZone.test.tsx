// @vitest-environment jsdom
/**
 * Каркас зоны управления (02.11.2026, после жалобы владельца на верхний блок).
 *
 * Что здесь зафиксировано:
 *  - в шапке нет ни языка, ни темы: они настройки, а не вкладки зон. Раньше
 *    EN/UZ стояли вплотную к «Сотрудник | Управление» и читались как третья
 *    вкладка;
 *  - декоративного значка с гаечным ключом больше нет — он выглядел кнопкой,
 *    но не делал ничего;
 *  - внизу появляется полоса разделов управления, а самая правая кнопка —
 *    «Настройки»;
 *  - кнопка ведёт в раздел кабинета через стор, поэтому кабинет и полоса не
 *    расходятся в том, что открыто.
 *
 * Сам кабинет подменён заглушкой: здесь проверяется каркас, а не его содержимое.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { useUI } from "@/store/ui";

vi.mock("./AdminScreen", () => ({
  default: () => <div data-testid="admin-screen-stub" />,
}));

import ManageZone from "./ManageZone";

/** Шапка зоны спрашивает счётчики через react-query — как и приложение. */
function renderZone(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  useUI.setState({ mode: "manage", tab: "feed", adminSection: "root" });
});

afterEach(() => {
  cleanup();
  useUI.setState({ mode: "staff", adminSection: "root" });
});

describe("ManageZone", () => {
  it("держит в шапке только переключатель зон", () => {
    renderZone(<ManageZone users={[]} canManage platform={false} />);

    expect(screen.getByTestId("mode-switch")).toBeTruthy();
    // Язык и тема — настройки, их место в «Настройках», а не рядом с вкладками.
    expect(screen.queryByTestId("language-switcher")).toBeNull();
    expect(screen.queryByTestId("theme-switcher")).toBeNull();
  });

  it("показывает нижнюю полосу и ведёт из неё в разделы кабинета", async () => {
    renderZone(<ManageZone users={[]} canManage platform={false} />);
    await screen.findByTestId("admin-screen-stub");

    const bar = screen.getByTestId("manage-tabbar");
    expect(bar).toBeTruthy();

    fireEvent.click(screen.getByTestId("manage-tab-admin-tasks"));
    expect(useUI.getState().adminSection).toBe("admin-tasks");

    fireEvent.click(screen.getByTestId("manage-tab-settings"));
    expect(useUI.getState().adminSection).toBe("settings");
    expect(screen.getByTestId("manage-tab-settings").getAttribute("aria-current")).toBe(
      "page",
    );
  });

  it("без права управления не показывает приёмку, но настройки оставляет", async () => {
    renderZone(<ManageZone users={[]} canManage={false} platform={false} />);
    await screen.findByTestId("admin-screen-stub");

    expect(screen.queryByTestId("manage-tab-review")).toBeNull();
    expect(screen.getByTestId("manage-tab-settings")).toBeTruthy();
  });
});
