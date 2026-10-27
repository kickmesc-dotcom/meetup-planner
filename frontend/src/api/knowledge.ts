import { api } from "./client";

/**
 * Поиск по знаниям заведения (стандарты и пункты чек-листов).
 *
 * Зачем отдельный модуль, а не метод в `hr.ts`: этот ответ — не часть рабочего
 * экрана, а «спросить и открыть». Его потребитель может быть любым (задачи,
 * профиль, лента), поэтому импорт не должен тянуть весь HR-слой.
 */
export interface KnowledgeHit {
  kind: "standard" | "checklist";
  id: number;
  title: string;
  snippet: string;
  /** Категория стандарта или название чек-листа — чтобы понять контекст. */
  subtitle: string;
}

export interface KnowledgeSearch {
  query: string;
  /** Слова, по которым реально искали: видно, что осталось после стоп-слов. */
  words: string[];
  hits: KnowledgeHit[];
  /**
   * Ничего не нашлось при непустом запросе. Отличать это от «ещё не искали»
   * нужно, чтобы показать «спросите руководителя», а не пустой экран.
   */
  empty: boolean;
}

export const searchKnowledge = (query: string, limit = 12) =>
  api<KnowledgeSearch>(
    `/api/knowledge/search?q=${encodeURIComponent(query)}&limit=${limit}`,
  );
