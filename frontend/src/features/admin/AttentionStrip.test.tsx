// @vitest-environment jsdom
/**
 * Сводка «требует внимания» на корне кабинета.
 *
 * Проверяем три обещания, которые легко потерять при правках:
 *  - числа приходят из одного ответа `/api/admin/dashboard` и не считаются
 *    повторно на клиенте по-своему;
 *  - «не начали смену» — это `has_run`, а не статус (иначе до вечера число
 *    падало бы, хотя люди так и не открыли чек-лист);
 *  - без ответа сводка молчит, а не показывает нули как «всё хорошо».
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { HrDashboard, HrDashboardEmployee } from "@/api/hr";
import AttentionStrip from "./AttentionStrip";

function employee(patch: Partial<HrDashboardEmployee> = {}): HrDashboardEmployee {
  return {
    employee_id: 1,
    display_name: "Аня",
    telegram_id: null,
    department_id: 1,
    department_name: "Кухня",
    department_emoji: "🍳",
    position: "повар",
    role: "employee",
    badge: null,
    badge_emoji: null,
    checklist_done: 0,
    checklist_total: 3,
    tasks_open: 0,
    tasks_overdue: 0,
    has_run: true,
    last_activity_at: null,
    status: "in_progress",
    ...patch,
  };
}

function dashboard(patch: Partial<HrDashboard> = {}): HrDashboard {
  return {
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
    ...patch,
  };
}

afterEach(cleanup);

describe("AttentionStrip", () => {
  it("показывает числа и ведёт в раздел разбора", () => {
    const onOpen = vi.fn();
    render(
      <AttentionStrip
        data={dashboard({
          total_employees: 4,
          shifts_started: 1,
          tasks_overdue: 2,
          open_issues: 1,
          employees: [
            employee({ employee_id: 1, has_run: false }),
            employee({ employee_id: 2, checklist_done: 1 }),
          ],
        })}
        onOpen={onOpen}
      />,
    );

    const strip = screen.getByTestId("attention-strip");
    expect(strip.textContent).toContain("Смена: 1 из 4 начали");
    expect(screen.getByTestId("attention-overdue").textContent).toContain("2");
    expect(screen.getByTestId("attention-issues").textContent).toContain("1");
    // Один человек без прогона и один с незакрытым чек-листом.
    expect(screen.getByTestId("attention-not-started").textContent).toContain("1");
    expect(screen.getByTestId("attention-unfinished").textContent).toContain("1");

    fireEvent.click(screen.getByTestId("attention-not-started"));
    expect(onOpen).toHaveBeenCalledWith("team");
    fireEvent.click(screen.getByTestId("attention-overdue"));
    expect(onOpen).toHaveBeenCalledWith("admin-tasks");
  });

  it("при нулях говорит, что всё под контролем", () => {
    render(
      <AttentionStrip
        data={dashboard({ total_employees: 3, shifts_started: 3 })}
        onOpen={() => {}}
      />,
    );

    const strip = screen.getByTestId("attention-strip");
    expect(strip.textContent).toContain("Всё под контролем");
    expect(screen.queryByTestId("attention-overdue")).toBeNull();
  });

  it("без ответа сервера не рисует нули", () => {
    const { container } = render(
      <AttentionStrip data={undefined} onOpen={() => {}} />,
    );
    expect(container.querySelector('[data-testid="attention-strip"]')).toBeNull();
  });
});
