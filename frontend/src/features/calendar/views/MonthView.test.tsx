// @vitest-environment jsdom
/**
 * Месяц на медленном канале: сетка настоящая сразу, плотность — когда приедут
 * отметки.
 *
 * Почему это проверяется. В `MonthView` работает правило «не размечено = занят»:
 * день без единой отметки считается занятым. Пока запрос диапазонов не ответил,
 * это правило красило ВЕСЬ месяц в «занято» — человек открывал календарь на
 * холодном старте контейнера, видел сплошную занятость и уходил с неверным
 * выводом. Здесь два обещания:
 *
 *  - до ответа видно каркас: месяцы, дни недели и числа уже на своих местах,
 *    вместо точек плотности — строка-скелетон;
 *  - после ответа точки плотности возвращаются (иначе фикс «навсегда спрятал»
 *    бы главную информацию экрана).
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import MonthView from "./MonthView";
import type { AvailabilityRange, User } from "@/types";

afterEach(cleanup);

const USERS: User[] = [
  {
    id: 1,
    display_name: "Азиз",
    color_hex: "#e07a5f",
    avatar_url: null,
  } as User,
];

const RANGES: AvailabilityRange[] = [
  {
    id: 1,
    user_id: 1,
    starts_at: new Date().toISOString(),
    ends_at: new Date(Date.now() + 3600_000).toISOString(),
    status: 1,
    confidence: 3,
    all_day: false,
  } as AvailabilityRange,
];

describe("MonthView: каркас до данных", () => {
  it("пока отметки едут, сетка и числа уже на экране", () => {
    render(
      <MonthView
        months={1}
        anchor={new Date(2026, 9, 15)}
        ranges={[]}
        users={USERS}
        isPending
      />,
    );

    // Статика месяца — до любых данных.
    expect(screen.getByText("Октябрь 2026")).toBeTruthy();
    expect(screen.getByText("пн")).toBeTruthy();
    expect(screen.getByRole("button", { name: /^15$/ })).toBeTruthy();
    // И каркас вместо плотности.
    expect(screen.getAllByTestId("month-day-skeleton").length).toBeGreaterThan(0);
  });

  it("после ответа точки плотности возвращаются", () => {
    render(
      <MonthView
        months={1}
        anchor={new Date(2026, 9, 15)}
        ranges={RANGES}
        users={USERS}
      />,
    );

    expect(screen.queryAllByTestId("month-day-skeleton")).toHaveLength(0);
  });
});
