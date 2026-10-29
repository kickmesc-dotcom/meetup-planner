import { translateTexts, type TranslateTarget } from "@/api/translate";

/**
 * Общая часть кнопки перевода данных (план, 11).
 *
 * Зачем отдельный модуль. Логика «что вообще переводить, чем резать строку и
 * где кэш» одинакова у одиночного текста (`TranslatableText`) и у блока с
 * десятком строк (лента, стандарт). Пока она жила в компоненте, второй
 * потребитель неизбежно завёл бы свою копию — и разошёлся бы с первой в
 * деталях, которые видно только на живом хосте: лимит 20 строк, предел 500
 * символов, повторный запрос за уже переведённым.
 *
 * Здесь нет React: только правила и сеть. Компоненты остаются про разметку.
 */

/** Кириллица — признак «текст ещё на русском». */
export const CYRILLIC = /[А-Яа-яЁё]/;

/** Сервер принимает до 500 символов на строку; режем заранее, чтобы не 400. */
export const MAX_CHARS = 500;

/** Сервер принимает до 20 строк за запрос (ручка под `EmployeeDep`). */
export const BATCH_LIMIT = 20;

/**
 * Кэш на время сессии: `язык + текст → перевод`.
 *
 * Нужен, потому что человек листает список и включает перевод у нескольких
 * блоков подряд, а иногда выключает и включает снова. Один и тот же текст
 * второй раз по сети не ходит — серверный кэш в базе всё равно сработал бы, но
 * это лишний круг до чужого сервера на мобильном интернете.
 *
 * `null` в кэше — не «пусто», а «перевода нет»: строка уже латиницей или на
 * этом хосте нет модели. Такой ответ тоже запоминаем, иначе кнопка честно
 * говорит «недоступно» и тут же снова стучится в сеть.
 */
const SESSION_CACHE = new Map<string, string | null>();

export function targetFor(locale: string): TranslateTarget | null {
  if (locale === "en") return "en";
  if (locale === "uz") return "uz";
  return null;
}

/** Есть ли в тексте что переводить. */
export function needsTranslation(text: string): boolean {
  return CYRILLIC.test(text);
}

function clip(text: string): string {
  return text.slice(0, MAX_CHARS);
}

function cacheKey(text: string, target: TranslateTarget): string {
  return `${target}:${clip(text)}`;
}

/**
 * Один текст. `null` — перевода нет: либо уже латиница, либо на этом контейнере
 * модели нет (Amvera, 0,5 ГБ RAM). Обе причины человеку называются одинаково:
 * «перевод недоступен», без выдуманного текста.
 */
export async function translateOne(
  text: string,
  target: TranslateTarget,
): Promise<string | null> {
  const key = cacheKey(text, target);
  if (SESSION_CACHE.has(key)) return SESSION_CACHE.get(key) ?? null;

  const response = await translateTexts([clip(text)], target);
  const value = response.items[0]?.translated ?? null;
  SESSION_CACHE.set(key, value);
  return value;
}

/**
 * Пачка текстов одной кнопкой.
 *
 * Возвращает карту `оригинал → перевод` только для тех строк, что реально
 * перевелись. Ключ — **оригинал без обрезки**, потому что вызывающий код ищет
 * по нему текст из базы; обрезка нужна лишь в запросе.
 *
 * Строки идут порциями по 20: ручка не принимает больше, а резать блок на
 * половину (первая половина узбекская, вторая русская) хуже, чем подождать
 * второй запрос. Порции последовательные, а не параллельные: модель на CPU
 * одна, и очередь из четырёх одновременных запросов только растянет первый.
 */
export async function translateBatch(
  texts: string[],
  target: TranslateTarget,
): Promise<Map<string, string>> {
  const result = new Map<string, string>();
  const pending: string[] = [];
  const seen = new Set<string>();

  for (const raw of texts) {
    if (!needsTranslation(raw) || seen.has(raw)) continue;
    seen.add(raw);
    const key = cacheKey(raw, target);
    if (SESSION_CACHE.has(key)) {
      const cached = SESSION_CACHE.get(key);
      if (cached) result.set(raw, cached);
      continue;
    }
    pending.push(raw);
  }

  for (let start = 0; start < pending.length; start += BATCH_LIMIT) {
    const chunk = pending.slice(start, start + BATCH_LIMIT);
    const response = await translateTexts(chunk.map(clip), target);
    // Хост без модели: остальные порции всё равно вернут то же самое, и
    // дёргать их — только жечь время человека.
    if (response.available === false) break;

    chunk.forEach((raw, index) => {
      const value = response.items[index]?.translated ?? null;
      SESSION_CACHE.set(cacheKey(raw, target), value);
      if (value) result.set(raw, value);
    });
  }

  return result;
}

/** Только для тестов: сбросить память между кейсами. */
export function __clearTranslateCache(): void {
  SESSION_CACHE.clear();
}
