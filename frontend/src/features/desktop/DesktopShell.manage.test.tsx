// @vitest-environment jsdom
/**
 * Один каркас для обеих зон (жалоба владельца 04.11.2026).
 *
 * На десктопе навигация не должна переезжать при переключении
 * «Сотрудник | Управление»: слева всегда сайдбар, снизу ничего. Проверяем
 * именно это, а не «компонент отрисовался».
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DesktopShell from "./DesktopShell";
import ManageZone from "@/features/admin/ManageZone";
import { useUI } from "@/store/ui";

function renderManageShell() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DesktopShell
        zone="manage"
        meName="Сергей"
        meHint="Управляющий"
        canManage
      >
        <ManageZone desktop users={[]} canManage />
      </DesktopShell>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  useUI.setState({ adminSection: "root" });
});

describe("DesktopShell в зоне управления", () => {
  it("держит разделы кабинета в левом сайдбаре, а не в нижней полосе", () => {
    renderManageShell();
    for (const label of ["Кабинет", "Внимание", "Поручения", "Приёмка", "Настройки"]) {
      expect(screen.getByRole("button", { name: label })).toBeTruthy();
    }
    // Разделы сотрудника в управлении не нужны: их зона — другая.
    expect(screen.queryByRole("button", { name: "События" })).toBeNull();
    // Нижней полосы управления на десктопе нет вовсе.
    expect(screen.queryByTestId("manage-tabbar")).toBeNull();
  });

  it("переключает раздел кабинета тем же кликом, что и вкладку зоны", () => {
    renderManageShell();
    fireEvent.click(screen.getByRole("button", { name: "Приёмка" }));
    expect(useUI.getState().adminSection).toBe("review");
  });
});
