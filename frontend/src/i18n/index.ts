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
  /**
   * Счётчик догруженных словарей экранов (`loadContent`).
   *
   * Нужен только как повод перерисовать: локаль ставится сразу, а пакет
   * английского или узбекского приезжает отдельным чанком позже. Без этого
   * поля экран остался бы на русских оригиналах до следующего действия.
   */
  contentVersion: number;
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
  contentVersion: 0,
  setLocale: (locale) => {
    applyLocale(locale);
    storeLocale(locale);
    set({ locale });
    // Словари экранов — отдельные чанки: см. `loadContent`. Локаль уже
    // переключена (шапка и подписи меняются сразу), а переводы придут и
    // перерисуют экран, когда загрузятся.
    void loadContent(locale);
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
  // Сохранённый английский (или узбекский) — это ещё не словарь экранов:
  // он приедет чанком и перерисует первый экран, когда загрузится.
  void loadContent(locale);
  return locale;
}

/** Словари экранов по языкам; заполняются по требованию (`loadContent`). */
const CONTENT: Partial<Record<Locale, Record<string, string>>> = {};
const CONTENT_LOADS = new Map<Locale, Promise<void>>();

/**
 * Догрузить словарь экранов для языка.
 *
 * Зачем по требованию. `content.ts` — это 1854 английские строки, ~160 КБ
 * исходника. Раньше он лежал в главном чанке и грузился каждому, включая тех,
 * кто весь день работает по-русски и никогда не нажимал EN. Русскому словарь
 * не нужен вовсе: `tx` возвращает оригинал, то есть сам русский текст.
 *
 * Возвращает промис: его ждут тесты и предзагрузка; в приложении он не
 * блокирует переключение — локаль ставится сразу, а экран перерисуется, когда
 * пакет придёт (`contentVersion` в сторе).
 */
export function loadContent(locale: Locale): Promise<void> {
  if (locale === "ru") return Promise.resolve();
  const pending = CONTENT_LOADS.get(locale);
  if (pending) return pending;
  const loading = (
    locale === "en"
      ? import("./content").then((module) => module.EN_CONTENT)
      : import("./content.uz").then((module) => module.UZ_CONTENT)
  )
    .then((pack) => {
      CONTENT[locale] = pack;
      useLocale.setState((state) => ({
        contentVersion: state.contentVersion + 1,
      }));
    })
    .catch(() => {
      // Сеть пропала — экран читается на русских оригиналах, а не падает.
      // Запись убираем: следующая попытка выбора языка попробует снова.
      CONTENT_LOADS.delete(locale);
    });
  CONTENT_LOADS.set(locale, loading);
  return loading;
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
export function tx(
  locale: Locale,
  text: string,
  vars?: Record<string, string | number>,
): string {
  // Русский — оригинал и заодно запасной вариант: если строки нет в пакете,
  // она остаётся русской. Для узбекского это важнее, чем для английского:
  // русский в команде понимает каждый, а непереведённая английская строка
  // посреди узбекского экрана ничего не объяснит.
  // Словарь мог ещё не приехать — тогда экран читается на русском оригинале.
  const template = locale === "ru" ? text : (CONTENT[locale]?.[text] ?? text);
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
  // Подписка на догрузку словаря: язык мог быть выбран раньше, чем приехал его
  // пакет, и без этого экран не перерисовался бы сам.
  useLocale((s) => s.contentVersion);
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
 * (`humanizeApiError`), и он тоже проходит через словарь экранов: без этого
 * на английском экране появлялся русский абзац про интернет и лимиты.
 */
export function useErrorMessage() {
  const locale = useLocale((s) => s.locale);
  // Пакет языка мог приехать после первого отказа: подписка перерисует текст.
  useLocale((s) => s.contentVersion);
  return (error: unknown): string => {
    if (error instanceof ApiError) {
      const key = `error.${error.detail}` as MessageKey;
      if (key in MESSAGES[locale]) return translate(locale, key);
    }
    return tx(locale, humanizeApiError(error));
  };
}
