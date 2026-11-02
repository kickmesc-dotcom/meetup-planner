import { useQuery } from "@tanstack/react-query";
import { api } from "./client";

/**
 * Тексты интерфейса, которые правит управляющий.
 *
 * Сервер отдаёт готовую карту «код → текст» (дефолты + правки), поэтому
 * компоненту не нужно знать, меняли ли подпись: он просто берёт значение по
 * коду, а если сервер недоступен — остаётся литерал в коде.
 */
export const fetchAppTexts = () => api<Record<string, string>>("/api/texts");

export interface AppTextItem {
  code: string;
  group: string;
  title: string;
  hint: string;
  default: string;
  value: string;
}

export interface AppTextsCatalog {
  items: AppTextItem[];
  overrides: Record<string, string>;
}

export const fetchTextsCatalog = () =>
  api<AppTextsCatalog>("/api/admin/texts");

/** Сохранить правки целиком. Пустая строка возвращает дефолт. */
export const saveAppTexts = (values: Record<string, string>) =>
  api<AppTextsCatalog>("/api/admin/texts", {
    method: "PUT",
    body: JSON.stringify(values),
  });

/** Один текст: `fallback` — литерал из кода на случай, пока сервер молчит. */
export function useAppText(code: string, fallback: string): string {
  const q = useQuery({
    queryKey: ["app-texts"],
    queryFn: fetchAppTexts,
    staleTime: 5 * 60 * 1000,
  });
  return q.data?.[code] ?? fallback;
}

/**
 * Словарь отрасли: те же тексты, коды `term.*`.
 *
 * Возвращает функцию, а не значение: экрану нужно два-три термина сразу
 * («Зал» и «Залы», «Смена» и «Задачи»), и по одному хуку на слово было бы
 * три одинаковых запроса в одном рендере.
 *
 * Термин подставляется только там, где слово стоит само по себе: внутрь фразы
 * его класть нельзя — «у каждого зала» после замены на «кабинета» требует
 * другого падежа, а склейка падежей и даёт тот машинный язык, из-за которого
 * интерфейс читается как чужой.
 */
export function useTerms(): (code: string, fallback: string) => string {
  const q = useQuery({
    queryKey: ["app-texts"],
    queryFn: fetchAppTexts,
    staleTime: 5 * 60 * 1000,
  });
  return (code: string, fallback: string) => q.data?.[`term.${code}`] ?? fallback;
}
