import { api } from "./client";

/**
 * Перевод данных на язык интерфейса (план, 11).
 *
 * Отдельный модуль, а не метод в `hr.ts`: кнопку перевода можно повесить на
 * любой блок с чужими данными (задачи, чек-лист, позже — лента и стандарты), и
 * импорт не должен тянуть весь HR-слой.
 *
 * Отдельного состояния «есть ли модель» здесь нет: сервер отвечает
 * `available: false` на Amvera (0,5 ГБ RAM, модель туда не влезает) и
 * `true` на HF Space. Кнопка рисуется только при `available !== false`, поэтому
 * на хосте без модели человек не видит кнопку, которая не работает.
 */
export type TranslateTarget = "en" | "uz";

export interface TranslateItem {
  /** `null` — перевода нет: строка уже не по-русски либо модель недоступна. */
  translated: string | null;
  provider: string | null;
}

export interface TranslateResponse {
  target: TranslateTarget;
  available: boolean;
  reason: string | null;
  items: TranslateItem[];
}

export const translateTexts = (texts: string[], target: TranslateTarget) =>
  api<TranslateResponse>("/api/hr/translate", {
    // Путь целиком проверен на живом хосте: роутер HR монтируется с `/api`, и
    // без `/hr` ручка лежала бы на `/api/translate` — кнопка получала бы 404.
    method: "POST",
    body: JSON.stringify({ target, texts }),
  });
