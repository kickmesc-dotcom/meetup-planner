/**
 * Переключение языка без перезагрузки (B2B_PLATFORM_PLAN, шаг 2.5).
 *
 * Локаль живёт в zustand, как тема: подписанные компоненты перерисовываются сами,
 * `window.location.reload()` не нужен. Выбор хранится в localStorage и
 * переживает перезапуск.
 *
 * По умолчанию — всегда русский, и язык браузера/системы его НЕ меняет.
 * Причина не в упрямстве: английский перевод ещё неполный (экраны сотрудника
 * пока русские), и авто-переключение давало человеку английскую шапку с
 * русским содержимым — «я зашёл, а интерфейс сам стал наполовину английским».
 * Английский включается только явным нажатием RU/EN.
 *
 * Тексты — в `messages.ts`. Чего здесь сознательно нет: склонений и форматов
 * дат. Для двух локалей первый шаг — статические подписи; числа и даты уже
 * форматируются через `toLocaleString("ru-RU")` в своих экранах и переедут
 * отдельно, когда появятся английские заказчики.
 */
import { create } from "zustand";
import { ApiError, humanizeApiError } from "@/api/client";
import { EN_CONTENT } from "./content";
import { UZ_CONTENT } from "./content.uz";
import { en, ru, uz, type MessageKey } from "./messages";

export type { MessageKey };

export type Locale = "ru" | "en" | "uz";

export const LOCALE_STORAGE_KEY = "semitask.locale.v1";
export const DEFAULT_LOCALE: Locale = "ru";

const MESSAGES: Record<Locale, Record<MessageKey, string>> = { ru, en, uz };

/**
 * Языки, которые есть всегда. Узбекский — пакет организации (план, 8.3): его
 * включает владелец, а не приложение «по факту наличия перевода».
 */
export const BASE_LOCALES: readonly Locale[] = ["ru", "en"];

/** Какие языки показывать при данном состоянии пакета. */
export function localesFor(uzPackAvailable: boolean): Locale[] {
  return uzPackAvailable ? [...BASE_LOCALES, "uz"] : [...BASE_LOCALES];
}

function readStoredLocale(): Locale | null {
  try {
    if (typeof localStorage === "undefined") return null;
    const raw = localStorage.getItem(LOCALE_STORAGE_KEY);
    return raw === "ru" || raw === "en" || raw === "uz" ? raw : null;
  } catch {
    return null;
  }
}

function storeLocale(locale: Locale): void {
  try {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    // приватный режим — выбор просто не переживёт перезапуск
  }
}

/** Язык документа: от него зависят переносы, озвучка и `:lang()` в CSS. */
export function applyLocale(locale: Locale): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = locale;
  // Отдельный флаг для CSS: по нему убираем/меняем вещи, которые ломаются на
  // другом языке. Сейчас это `hyphens` — узбекские слова с апострофами
  // (`qoʻshilish`) браузер переносит по-разному, и автоперенос режет их не там.
  document.documentElement.dataset.locale = locale;
}

interface LocaleState {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  /**
   * Включён ли узбекский пакет в организации. По умолчанию `true` — ровно
   * то же, что и на сервере: выключенный по умолчанию перевод просто никто
   * не найдёт. Сервер может прислать `false`, и тогда язык пропадает из
   * переключателя.
   */
  uzPackAvailable: boolean;
  setUzPackAvailable: (available: boolean) => void;
}

export const useLocale = create<LocaleState>((set, get) => ({
  locale: DEFAULT_LOCALE,
  uzPackAvailable: true,
  setLocale: (locale) => {
    applyLocale(locale);
    storeLocale(locale);
    set({ locale });
  },
  setUzPackAvailable: (available) => {
    if (get().uzPackAvailable === available) return;
    // Выключили пакет, а человек на узбекском — возвращаем его на русский
    // сразу, а не после перезагрузки. Иначе экран остался бы на языке,
    // которого организация больше не обещает, и это выглядело бы как сбой.
    if (!available && get().locale === "uz") {
      applyLocale(DEFAULT_LOCALE);
      storeLocale(DEFAULT_LOCALE);
      set({ uzPackAvailable: available, locale: DEFAULT_LOCALE });
      return;
    }
    set({ uzPackAvailable: available });
  },
}));

/**
 * Стартовая локаль: сохранённый выбор, иначе русский.
 *
 * Язык браузера здесь сознательно не читается — см. комментарий в начале
 * файла: полупереведённый английский хуже, чем предсказуемый русский.
 */
export function initLocale(): Locale {
  const locale = readStoredLocale() ?? DEFAULT_LOCALE;
  applyLocale(locale);
  useLocale.setState({ locale });
  return locale;
}

/**
 * Перевод по ключу с подстановкой `{name}`. Неизвестный ключ возвращает сам
 * ключ: так пропуск видно в интерфейсе и в тесте, а не получается пустая строка.
 */
export function translate(
  locale: Locale,
  key: MessageKey,
  vars?: Record<string, string | number>,
): string {
  const template =
    MESSAGES[locale]?.[key] ?? MESSAGES[DEFAULT_LOCALE][key] ?? key;
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  );
}

/** Хук экрана: `t` для подписей и `setLocale` для переключателя. */
export function useT() {
  const locale = useLocale((s) => s.locale);
  return {
    locale,
    t: (key: MessageKey, vars?: Record<string, string | number>) =>
      translate(locale, key, vars),
  };
}

/**
 * Текст экрана на языке интерфейса: ключ — русский оригинал (`content.ts`).
 *
 * Если перевода нет, возвращается сам оригинал: непереведённая строка
 * остаётся русской, но экран не ломается и не показывает ключ вроде
 * `feed.title`. Проверка покрытия — в `i18n/coverage.test.ts`.
 *
 * Подстановки (`{name}`) работают в обоих языках: русский текст тоже может
 * содержать плейсхолдер, и он подставляется так же, как в переводе.
 */
const CONTENT: Record<Exclude<Locale, "ru">, Record<string, string>> = {
  en: EN_CONTENT,
  uz: UZ_CONTENT,
};

export function tx(
  locale: Locale,
  text: string,
  vars?: Record<string, string | number>,
): string {
  // Русский — оригинал и заодно запасной вариант: если строки нет в пакете,
  // она остаётся русской. Для узбекского это важнее, чем для английского:
  // русский в команде понимает каждый, а непереведённая английская строка
  // посреди узбекского экрана ничего не объяснит.
  const template = locale === "ru" ? text : (CONTENT[locale][text] ?? text);
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  );
}

/**
 * Текущая локаль вне компонента.
 *
 * Нужна там, где текст собирается в обычной функции (`fmtDue`, описание
 * события в журнале), а не в разметке: хук туда не поставить. Локаль читается
 * из того же стора, поэтому смена языка перерисовывает и такие места — их
 * вызывают из компонента.
 */
export function currentLocale(): Locale {
  return useLocale.getState().locale;
}

/**
 * Тег `Intl` для локали: `en-GB` (день до месяца), `uz-UZ` или `ru-RU`.
 *
 * Важно для узбекского: `toLocaleString` на нём даёт узбекские названия
 * месяцев и дней. Без этого тега дата «переехала» бы на русский лад посреди
 * узбекского экрана — и экран снова стал бы наполовину русским.
 *
 * Чистая функция: экраны, у которых локаль пришла пропом, не читают стор.
 */
export function intlLocaleFor(locale: Locale): string {
  if (locale === "en") return "en-GB";
  if (locale === "uz") return "uz-UZ";
  return "ru-RU";
}

/** Тег `Intl` для текущей локали (см. `intlLocaleFor`). */
export function currentIntlLocale(): string {
  return intlLocaleFor(currentLocale());
}

/** Хук экрана: `tx` для текстов и текущая локаль для дат и чисел. */
export function useTx() {
  const locale = useLocale((s) => s.locale);
  return {
    locale,
    tx: (text: string, vars?: Record<string, string | number>) =>
      tx(locale, text, vars),
  };
}

/**
 * Текст ошибки API на языке интерфейса.
 *
 * Сервер отдаёт коды, а не фразы, поэтому переводятся именно коды из
 * `messages.ts`. Если код незнакомый — остаётся общий разбор
 * (`humanizeApiError`), лучше русский текст, чем `invite_limit` на экране.
 */
export function useErrorMessage() {
  const locale = useLocale((s) => s.locale);
  return (error: unknown): string => {
    if (error instanceof ApiError) {
      const key = `error.${error.detail}` as MessageKey;
      if (key in MESSAGES[locale]) return translate(locale, key);
    }
    return humanizeApiError(error);
  };
}
