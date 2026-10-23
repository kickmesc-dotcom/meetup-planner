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
import { en, ru, type MessageKey } from "./messages";

export type Locale = "ru" | "en";

export const LOCALE_STORAGE_KEY = "semitask.locale.v1";
export const DEFAULT_LOCALE: Locale = "ru";

const MESSAGES: Record<Locale, Record<MessageKey, string>> = { ru, en };

function readStoredLocale(): Locale | null {
  try {
    if (typeof localStorage === "undefined") return null;
    const raw = localStorage.getItem(LOCALE_STORAGE_KEY);
    return raw === "ru" || raw === "en" ? raw : null;
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
}

interface LocaleState {
  locale: Locale;
  setLocale: (locale: Locale) => void;
}

export const useLocale = create<LocaleState>((set) => ({
  locale: DEFAULT_LOCALE,
  setLocale: (locale) => {
    applyLocale(locale);
    storeLocale(locale);
    set({ locale });
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
