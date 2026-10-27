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
  currentIntlLocale,
  initLocale,
  translate,
  tx,
  useErrorMessage,
  useLocale,
  useT,
  useTx,
} from ".";
import { en, ru } from "./messages";

const reload = vi.fn();

beforeEach(() => {
  localStorage.clear();
  // Пакет сбрасываем вместе с локалью: иначе тест, выключивший узбекский,
  // влиял бы на следующий — и проверка «третий язык есть» падала бы через раз.
  useLocale.setState({ locale: "ru", uzPackAvailable: true });
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

  it("без выбора оставляет русский, даже если браузер английский", () => {
    // Симптом из приложения: человек открыл мини-апп и получил английскую
    // шапку при русском содержимом. Язык системы больше ничего не решает.
    const original = Object.getOwnPropertyDescriptor(window, "navigator");
    Object.defineProperty(window, "navigator", {
      configurable: true,
      value: { ...window.navigator, language: "en-US", languages: ["en-US"] },
    });
    try {
      expect(initLocale()).toBe("ru");
      expect(useLocale.getState().locale).toBe("ru");
      expect(document.documentElement.lang).toBe("ru");
    } finally {
      if (original) Object.defineProperty(window, "navigator", original);
    }
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

describe("узбекский пакет организации", () => {
  it("третий язык есть, пока пакет включён", () => {
    render(<LanguageSwitcher />);
    expect(screen.getByRole("button", { name: "Oʻzbekcha" })).toBeTruthy();
  });

  it("выключенный пакет прячет язык, а не гасит кнопку", () => {
    // «Есть, но не для тебя» — вопрос без ответа внутри приложения. Поэтому
    // кнопки просто нет.
    useLocale.setState({ uzPackAvailable: false });
    render(<LanguageSwitcher />);
    expect(screen.queryByRole("button", { name: "Oʻzbekcha" })).toBeNull();
    expect(screen.getByRole("button", { name: "English" })).toBeTruthy();
  });

  it("выключение пакета возвращает человека на русский сразу", () => {
    useLocale.getState().setLocale("uz");
    expect(document.documentElement.lang).toBe("uz");

    useLocale.getState().setUzPackAvailable(false);

    expect(useLocale.getState().locale).toBe("ru");
    expect(document.documentElement.lang).toBe("ru");
    // И в хранилище: иначе после перезапуска человек снова оказался бы на
    // языке, которого организация больше не обещает.
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("ru");
  });

  it("переводит интерфейс без перезагрузки", () => {
    render(
      <>
        <LanguageSwitcher />
        <Probe />
      </>
    );
    fireEvent.click(screen.getByRole("button", { name: "Oʻzbekcha" }));
    expect(screen.getByTestId("probe").textContent).toBe("Voqealar");
    expect(reload).not.toHaveBeenCalled();
  });

  it("переводит тексты экранов, а непереведённое оставляет русским", () => {
    expect(tx("uz", "Открыть чек-лист")).toBe("Chek-listni ochish");
    expect(tx("uz", "Чек-лист смены")).toBe("Smena chek-listi");
    // Строка без перевода — русская, а не ключ и не пустота.
    expect(tx("uz", "Строка, которой нет в пакете")).toBe(
      "Строка, которой нет в пакете",
    );
  });

  it("даты и числа идут по узбекской локали", () => {
    const original = Object.getOwnPropertyDescriptor(window, "navigator");
    Object.defineProperty(window, "navigator", {
      configurable: true,
      value: { ...window.navigator, language: "uz-UZ", languages: ["uz-UZ"] },
    });
    try {
      useLocale.getState().setLocale("uz");
      expect(currentIntlLocale()).toBe("uz-UZ");
      // Январь узбекского календаря — не «январь» и не «January».
      const month = new Date(2026, 0, 15).toLocaleDateString(
        currentIntlLocale(),
        { month: "long" },
      );
      expect(month.toLowerCase()).toContain("yanvar");
    } finally {
      if (original) Object.defineProperty(window, "navigator", original);
    }
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

describe("перевод содержимого экранов", () => {
  function ScreenProbe() {
    const { tx: translate } = useTx();
    return (
      <div data-testid="probe">
        {translate("События смены")}|{translate("задач {count}", { count: 3 })}|
        {translate("Такого текста нет в словаре")}
      </div>
    );
  }

  it("переводит известный текст и подставляет значения", () => {
    useLocale.setState({ locale: "en" });
    render(<ScreenProbe />);

    expect(screen.getByTestId("probe").textContent).toBe(
      "Shift events|3 tasks|Такого текста нет в словаре",
    );
  });

  it("по-русски отдаёт оригинал с подстановкой", () => {
    render(<ScreenProbe />);

    expect(screen.getByTestId("probe").textContent).toBe(
      "События смены|задач 3|Такого текста нет в словаре",
    );
  });

  it("неизвестная строка остаётся русской, а не превращается в ключ", () => {
    // Главное свойство словаря: непереведённый экран читается, а не ломается.
    expect(tx("en", "Пока без перевода")).toBe("Пока без перевода");
    expect(tx("ru", "Пока без перевода")).toBe("Пока без перевода");
  });
});
