// @vitest-environment jsdom
/**
 * B2B_PLATFORM_PLAN, шаг 2.5: язык переключается без перезагрузки.
 *
 * Что держим тестом:
 *  - словари не разъезжаются: в `en` есть каждый ключ `ru` и наоборот пустых
 *    значений нет (типы ловят пропуск, но не пустую строку);
 *  - `translate` подставляет `{name}` и не теряет незнакомый плейсхолдер;
 *  - переключатель меняет текст живьём, без `location.reload()`;
 *  - `<html lang>` и localStorage обновляются — по ним браузер выбирает
 *    переносы, озвучку и запоминает выбор;
 *  - код ошибки сервера переводится, а незнакомый не превращается в пустоту.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ApiError } from "@/api/client";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import {
  LOCALE_STORAGE_KEY,
  initLocale,
  translate,
  useErrorMessage,
  useLocale,
  useT,
} from ".";
import { en, ru } from "./messages";

const reload = vi.fn();

beforeEach(() => {
  localStorage.clear();
  useLocale.setState({ locale: "ru" });
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, reload },
  });
});

afterEach(() => {
  cleanup();
  reload.mockClear();
});

function Probe() {
  const { t } = useT();
  return <span data-testid="probe">{t("nav.feed")}</span>;
}

describe("словари", () => {
  it("английский покрывает все русские ключи", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(ru).sort());
  });

  it("не содержит пустых строк", () => {
    for (const dictionary of [ru, en]) {
      const empty = Object.entries(dictionary)
        .filter(([, value]) => !value.trim())
        .map(([key]) => key);
      expect(empty).toEqual([]);
    }
  });
});

describe("translate", () => {
  it("берёт язык и подставляет переменные", () => {
    expect(translate("ru", "nav.tasks")).toBe("Задачи");
    expect(translate("en", "nav.tasks")).toBe("Tasks");
    expect(
      translate("ru", "invite.role", { role: "Управляющий", until: "1 ноября" }),
    ).toContain("до 1 ноября");
    expect(translate("en", "nav.tasksOpen", { label: "Tasks", count: 3 })).toBe(
      "Tasks, open: 3",
    );
  });

  it("оставляет незнакомый плейсхолдер как есть", () => {
    expect(translate("en", "invite.joined.text", { org: "Acme" })).toContain(
      "{role}",
    );
  });
});

describe("переключение языка", () => {
  it("меняет текст без перезагрузки страницы", () => {
    render(
      <>
        <LanguageSwitcher />
        <Probe />
      </>,
    );
    expect(screen.getByTestId("probe").textContent).toBe("События");

    fireEvent.click(screen.getByRole("button", { name: "English" }));

    expect(screen.getByTestId("probe").textContent).toBe("Events");
    expect(reload).not.toHaveBeenCalled();
  });

  it("запоминает выбор и язык документа", () => {
    useLocale.getState().setLocale("en");
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("en");
    expect(document.documentElement.lang).toBe("en");
  });

  it("на старте берёт сохранённый язык", () => {
    localStorage.setItem(LOCALE_STORAGE_KEY, "en");
    expect(initLocale()).toBe("en");
    expect(useLocale.getState().locale).toBe("en");
  });

  it("отмечает выбранный язык для скринридера", () => {
    render(<LanguageSwitcher />);
    expect(
      screen.getByRole("button", { name: "Русский" }).getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    expect(
      screen.getByRole("button", { name: "English" }).getAttribute("aria-pressed"),
    ).toBe("true");
  });
});

describe("перевод ошибок", () => {
  function ErrorProbe({ error }: { error: unknown }) {
    const errorText = useErrorMessage();
    return <span data-testid="error">{errorText(error)}</span>;
  }

  it("переводит известный код", () => {
    useLocale.getState().setLocale("en");
    render(<ErrorProbe error={new ApiError(403, "invite_expired")} />);
    expect(screen.getByTestId("error").textContent).toContain("expired");
  });

  it("незнакомый код не оставляет пустой экран", () => {
    render(<ErrorProbe error={new ApiError(500, "weird_thing")} />);
    expect(screen.getByTestId("error").textContent?.trim()).not.toBe("");
  });
});
