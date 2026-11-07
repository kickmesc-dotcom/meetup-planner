// @vitest-environment jsdom
/**
 * §11: подробность интерфейса — настройка, а не автоматическое решение.
 * Проверяем, что выбор виден, что он запоминается и что по умолчанию стоит
 * расширенный режим (приложение уже используется, скрывать разделы молча нельзя).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import SettingsScreen from "./SettingsScreen";

vi.mock("@/components/LanguageSwitcher", () => ({ default: () => <div>lang</div> }));
vi.mock("@/components/ThemeSwitcher", () => ({ default: () => <div>theme</div> }));

function renderScreen() {
  return render(<SettingsScreen onBack={() => {}} onOpen={() => {}} />);
}

beforeEach(() => localStorage.clear());
afterEach(cleanup);

describe("SettingsScreen: подробность интерфейса", () => {
  it("по умолчанию выбирает расширенный режим", () => {
    renderScreen();
    expect(
      screen.getByRole("button", { name: "Расширенный режим" }).getAttribute("aria-pressed"),
    ).toBe("true");
    expect(localStorage.getItem("ux.mode.v1")).toBeNull();
  });

  it("запоминает простой режим и показывает выбор", () => {
    renderScreen();

    fireEvent.click(screen.getByRole("button", { name: "Простой режим" }));

    expect(localStorage.getItem("ux.mode.v1")).toBe("simple");
    expect(
      screen.getByRole("button", { name: "Простой режим" }).getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      screen.getByRole("button", { name: "Расширенный режим" }).getAttribute("aria-pressed"),
    ).toBe("false");
  });
});
