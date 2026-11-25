// @vitest-environment jsdom
/**
 * Фильтр меню (13.11.2026).
 *
 * Стоп-лист теперь виден сотруднику — значит список стал длиннее, и нужен
 * способ оставить только «чего нет» или только «что есть». Проверяем именно
 * переключение: без него фильтр — это кнопки, которые ничего не меняют.
 *
 * Второе: без стоп-листа фильтр не рисуется вовсе. Кнопка «Стоп-лист (0)» —
 * обещание пустого экрана, а не помощь.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useLocale } from "@/i18n";
import type { MenuItem } from "@/api/menu";
import MenuList from "./MenuList";

const ITEMS: MenuItem[] = [
  {
    id: 1,
    name: "Борщ",
    category: "Супы",
    description: null,
    price_rub: 320,
    photo_blob_id: null,
    photo_url: null,
    is_available: true,
    sort_order: 0,
    updated_at: null,
  },
  {
    id: 2,
    name: "Рыба дня",
    category: "Горячее",
    description: null,
    price_rub: null,
    photo_blob_id: null,
    photo_url: null,
    is_available: false,
    sort_order: 0,
    updated_at: null,
  },
];

const CATEGORIES = ["Супы", "Горячее"];

beforeEach(() => {
  useLocale.setState({ locale: "ru" });
  cleanup();
});

describe("MenuList", () => {
  it("фильтр оставляет только стоп-лист или только доступное", () => {
    render(<MenuList items={ITEMS} categories={CATEGORIES} />);

    // По умолчанию видно всё: сотрудник должен знать и то, что есть, и то, чего нет.
    expect(screen.getByText("Борщ")).toBeTruthy();
    expect(screen.getByText("Рыба дня")).toBeTruthy();

    fireEvent.click(screen.getByText("Стоп-лист (1)"));
    expect(screen.getByText("Рыба дня")).toBeTruthy();
    expect(screen.queryByText("Борщ")).toBeNull();

    fireEvent.click(screen.getByText("В наличии"));
    expect(screen.getByText("Борщ")).toBeTruthy();
    expect(screen.queryByText("Рыба дня")).toBeNull();

    fireEvent.click(screen.getByText("Все"));
    expect(screen.getByText("Борщ")).toBeTruthy();
    expect(screen.getByText("Рыба дня")).toBeTruthy();
  });

  it("цена показывается в валюте организации", () => {
    render(<MenuList items={[ITEMS[0]]} categories={CATEGORIES} currency="KZT" />);

    // Число остаётся числом, меняется только подпись: рубль в тенге был бы
    // ошибкой цены, а не оформления.
    expect(screen.getByText(/320/)).toBeTruthy();
    expect(screen.queryByText(/₽/)).toBeNull();
  });

  it("без стоп-листа фильтр не показывается", () => {
    render(<MenuList items={[ITEMS[0]]} categories={CATEGORIES} />);

    expect(screen.getByText("Борщ")).toBeTruthy();
    expect(screen.queryByText("В наличии")).toBeNull();
    expect(screen.queryByText(/Стоп-лист/)).toBeNull();
  });

  it("фильтр остаётся, когда стоп-лист опустел", () => {
    const { rerender } = render(<MenuList items={ITEMS} categories={CATEGORIES} />);
    fireEvent.click(screen.getByText("Стоп-лист (1)"));

    // Позицию вернули в меню: фильтр включён, показывать нечего — но экран
    // объясняет это, а не остаётся белым.
    rerender(
      <MenuList
        items={[{ ...ITEMS[0] }, { ...ITEMS[1], is_available: true }]}
        categories={CATEGORIES}
      />,
    );
    expect(screen.getByText("В стоп-листе сейчас ничего нет.")).toBeTruthy();
  });
});
