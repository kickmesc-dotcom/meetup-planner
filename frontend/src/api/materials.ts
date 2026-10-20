import { api } from "./client";

/**
 * Материалы смены: сервер отдаёт последний снимок Google Sheets из своей БД.
 * Клиент не ходит в Google напрямую — именно поэтому график и меню видны без
 * VPN и даже когда сама таблица недоступна.
 */
export interface HrMaterial {
  id: number;
  title: string;
  emoji: string | null;
  url: string;
  synced_at: string | null;
  /** Последняя ошибка обновления. Данные при этом остаются прежними. */
  sync_error: string | null;
  stale: boolean;
  rows: string[][];
  columns: number;
}

export const fetchMaterials = () => api<HrMaterial[]>("/api/materials");

export const refreshMaterial = (id: number) =>
  api<HrMaterial>(`/api/materials/${id}/refresh`, { method: "POST" });
