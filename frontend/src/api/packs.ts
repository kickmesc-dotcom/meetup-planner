import { api } from "./client";

/**
 * Стартовый пакет отрасли (план, фаза 3, шаг 3.2).
 *
 * Мастер настройки спрашивает отрасль, но до сих пор она влияла только на
 * подсказки подразделений: слова, чек-листы и веса опыта оставались
 * ресторанными. Экран показывает содержимое пакета целиком — «применить»
 * без списка того, что изменится, это кнопка-лотерея.
 */
export interface Pack {
  industry: string;
  title: string;
  why: string;
  /** Код текста → значение термина, например `term.hall.one` → «Кабинет». */
  terms: Record<string, string>;
  /** Подсказки должностей: что в этой отрасли пишут в поле «должность». */
  positions: string[];
  checklist_items: number;
  opening_items: string[];
  closing_items: string[];
  kpi: Record<string, number>;
}

export interface PackState {
  pack: Pack;
  can_apply: boolean;
  /** Отрасль из мастера; может не совпадать с `pack.industry` у неизвестной. */
  industry: string;
  catalog: Pack[];
}

export interface PackApplyResult {
  industry: string;
  title: string;
  terms_set: number;
  templates_created: number;
  kpi_updated: boolean;
  force: boolean;
}

export const fetchPack = () => api<PackState>("/api/pack");

export const applyPack = (body: { industry?: string; force_terms?: boolean }) =>
  api<PackApplyResult>("/api/pack/apply", {
    method: "POST",
    body: JSON.stringify(body),
  });
