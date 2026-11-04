/**
 * Импорт людей и графика из CSV (B2B_PLATFORM_PLAN, шаг 6.3).
 *
 * Путь держится тестом `imports.paths.test.ts`: сервер монтирует роутер под
 * `/api`, а ручки внутри объявлены как `/import/*`. Ровно на этом разъехались
 * благодарности (31.10) и подписки на сводку (04.11) — третий раз не надо.
 */
import { api } from "./client";

export type ImportKind = "people" | "shifts";

export interface ImportRow {
  row: number;
  /** create | update | skip | error */
  action: string;
  name: string;
  detail: string;
  errors: string[];
}

export interface ImportPreview {
  kind: ImportKind;
  /** Разделитель, который угадал сервер: `;` или `,`. Показываем человеку. */
  delimiter: string;
  total: number;
  create: number;
  update: number;
  skip: number;
  error: number;
  departments: string[];
  rows: ImportRow[];
}

export interface ImportResult {
  kind: ImportKind;
  created: number;
  updated: number;
  skipped: number;
  errors: number;
  rows: ImportRow[];
}

export interface ImportPayload {
  text: string;
  filename?: string | null;
  kind?: ImportKind | null;
  overwrite?: boolean;
}

export const previewImport = (body: ImportPayload) =>
  api<ImportPreview>("/api/import/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const applyImport = (body: ImportPayload) =>
  api<ImportResult>("/api/import/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

/** Пример CSV: с ним импорт занимает одну минуту, а не «попробуй угадать». */
export function sampleCsv(kind: ImportKind): string {
  if (kind === "shifts") {
    const day = new Date();
    day.setDate(day.getDate() + 1);
    const iso = day.toISOString().slice(0, 10);
    return [
      "имя;дата;статус;начало;конец",
      `Сергей Петров;${iso};смена;10:00;18:00`,
      `Анна Смирнова;${iso};выходной;;`,
    ].join("\n");
  }
  return [
    "имя;должность;подразделение;роль;telegram_id",
    "Сергей Петров;Управляющий;Зал;руководитель;",
    "Анна Смирнова;Официант;Зал;сотрудник;",
  ].join("\n");
}
