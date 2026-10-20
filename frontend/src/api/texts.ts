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
