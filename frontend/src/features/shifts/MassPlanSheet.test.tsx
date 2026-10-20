// @vitest-environment jsdom
/**
 * Массовое планирование смен: шаблон недели.
 *
 * Проверяем обещания листа: без выбранных дней записывать нечего, дни недели
 * превращаются в даты именно этой недели, «заменить существующие» по умолчанию
 * выключено (массовая запись не должна случаться от одного тапа), а очистка и
 * копирование получают ровно тот же выбор людей.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import MassPlanSheet from "./MassPlanSheet";
import type { ShiftPerson, ShiftStatusMeta } from "@/api/shifts";

vi.mock("@/tg/webapp", () => ({ haptic: vi.fn() }));

const PEOPLE: ShiftPerson[] = [
  {
    employee_id: 1,
    display_name: "Алина",
    position: "Официант",
    department_id: 1,
    department_name: "Зал",
  },
  {
    employee_id: 2,
    display_name: "Борис",
    position: "Бармен",
    department_id: 1,
    department_name: "Бар",
  },
];

const STATUSES: ShiftStatusMeta[] = [
  { value: "planned", label: "Запланирована", short: "П" },
  { value: "worked", label: "Отработана", short: "О" },
  { value: "dayoff", label: "Выходной", short: "В" },
];

const WEEK_START = new Date(2026, 9, 19); // понедельник, 19.10.2026

function renderSheet(overrides: Partial<Parameters<typeof MassPlanSheet>[0]> = {}) {
  const onApply = vi.fn();
  const onClear = vi.fn();
  const onCopyPrevious = vi.fn();
  const onClose = vi.fn();
  render(
    <MassPlanSheet
      people={PEOPLE}
      weekStart={WEEK_START}
      statuses={STATUSES}
      busy={false}
      copyBusy={false}
      clearBusy={false}
      onClose={onClose}
      onApply={onApply}
      onClear={onClear}
      onCopyPrevious={onCopyPrevious}
      {...overrides}
    />,
  );
  return { onApply, onClear, onCopyPrevious, onClose };
}

afterEach(cleanup);

describe("MassPlanSheet", () => {
  it("без выбранных дней не даёт применить шаблон", () => {
    renderSheet();

    expect(screen.getByText("Выбери людей и дни")).toBeTruthy();
    const apply = screen.getByRole("button", { name: /Применить/ });
    expect((apply as HTMLButtonElement).disabled).toBe(true);
  });

  it("переводит пн и ср в даты этой недели и не затирает по умолчанию", () => {
    const { onApply } = renderSheet();

    fireEvent.click(screen.getByRole("button", { name: "Пн" }));
    fireEvent.click(screen.getByRole("button", { name: "Ср" }));
    fireEvent.click(screen.getByRole("button", { name: /Применить/ }));

    expect(onApply).toHaveBeenCalledTimes(1);
    const input = onApply.mock.calls[0][0];
    // Люди выбраны все по умолчанию, дни — по возрастанию, без дублей.
    expect(input.employeeIds).toEqual([1, 2]);
    expect(input.days).toEqual(["2026-10-19", "2026-10-21"]);
    expect(input.status).toBe("planned");
    expect(input.overwrite).toBe(false);
  });

  it("меняет статус и передаёт часы с заметкой", () => {
    const { onApply } = renderSheet();

    fireEvent.click(screen.getByRole("button", { name: "Пт" }));
    fireEvent.click(screen.getByRole("button", { name: "Отработана" }));
    fireEvent.change(screen.getByLabelText("Начало"), {
      target: { value: "10:00" },
    });
    fireEvent.change(screen.getByLabelText("Конец"), {
      target: { value: "18:00" },
    });
    fireEvent.change(screen.getByPlaceholderText("Заметка (необязательно)"), {
      target: { value: " подмена " },
    });
    fireEvent.click(screen.getByRole("button", { name: /Применить/ }));

    const input = onApply.mock.calls[0][0];
    expect(input.days).toEqual(["2026-10-23"]);
    expect(input.status).toBe("worked");
    expect(input.startsAt).toBe("10:00");
    expect(input.endsAt).toBe("18:00");
    expect(input.note).toBe(" подмена ");
    // Обрезку заметки делает вызывающий код — здесь она как есть.
  });

  it("замена существующих включается только галочкой", () => {
    const { onApply } = renderSheet();

    fireEvent.click(screen.getByRole("button", { name: "Вт" }));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /Применить/ }));

    expect(onApply.mock.calls[0][0].overwrite).toBe(true);
  });

  it("«Снять всех» оставляет лист без людей и без действия", () => {
    renderSheet();

    fireEvent.click(screen.getByRole("button", { name: "Снять всех" }));
    fireEvent.click(screen.getByRole("button", { name: "Пн" }));

    expect(screen.getByText("Выбери людей и дни")).toBeTruthy();
    const apply = screen.getByRole("button", { name: /Применить/ });
    expect((apply as HTMLButtonElement).disabled).toBe(true);
  });

  it("копирует прошлую неделю и снимает смены тем же выбором людей", () => {
    const { onClear, onCopyPrevious } = renderSheet();

    fireEvent.click(screen.getByRole("button", { name: "Снять всех" }));
    fireEvent.click(screen.getByRole("button", { name: "Алина" }));
    fireEvent.click(screen.getByRole("button", { name: "Ср" }));

    fireEvent.click(
      screen.getByRole("button", { name: "Скопировать прошлую неделю" }),
    );
    expect(onCopyPrevious).toHaveBeenCalledWith([1]);

    fireEvent.click(screen.getByRole("button", { name: "Снять смены" }));
    expect(onClear).toHaveBeenCalledWith({
      employeeIds: [1],
      days: ["2026-10-21"],
    });
  });
});
