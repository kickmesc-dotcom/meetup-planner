import { currentIntlLocale } from "@/i18n";

/**
 * Форматирование чисел и дат в одном месте.
 *
 * Зачем. По экранам было полсотни `toLocaleString("ru-RU")`: на английской и
 * узбекской поверхности даты оставались русскими, а деньги считались двумя
 * одинаковыми локальными `money`. Одна функция держит локаль и запасной путь
 * для битой даты, поэтому экран не решает это заново.
 */

const DEFAULT_DATE: Intl.DateTimeFormatOptions = {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
};

const DEFAULT_TIME: Intl.DateTimeFormatOptions = {
  hour: "2-digit",
  minute: "2-digit",
};

const DEFAULT_DATE_TIME: Intl.DateTimeFormatOptions = {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
};

function toDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatNumber(
  value: number,
  options?: Intl.NumberFormatOptions,
): string {
  if (!Number.isFinite(value)) return "—";
  return value.toLocaleString(currentIntlLocale(), options);
}

export function formatMoney(amount: number, currency = "₽"): string {
  if (!Number.isFinite(amount)) return "—";
  return `${formatNumber(amount)} ${currency}`;
}

export function formatDate(
  value: string | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = DEFAULT_DATE,
): string {
  const date = toDate(value);
  return date ? date.toLocaleDateString(currentIntlLocale(), options) : "—";
}

export function formatTime(
  value: string | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = DEFAULT_TIME,
): string {
  const date = toDate(value);
  return date ? date.toLocaleTimeString(currentIntlLocale(), options) : "—";
}

export function formatDateTime(
  value: string | Date | null | undefined,
  options: Intl.DateTimeFormatOptions = DEFAULT_DATE_TIME,
): string {
  const date = toDate(value);
  return date ? date.toLocaleString(currentIntlLocale(), options) : "—";
}
