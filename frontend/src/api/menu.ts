import { api } from "./client";

/**
 * Меню смены. Раньше оно приходило снимком Google Sheets вместе с графиком,
 * и чтобы убрать блюдо, руководитель шёл в таблицу. Теперь это обычные данные
 * организации: сотрудник читает, руководитель правит здесь же.
 */
export interface MenuItem {
  id: number;
  name: string;
  category: string;
  description: string | null;
  /** Цена в целых рублях. `null` — «по запросу». */
  price_rub: number | null;
  /** `false` — «сегодня этого нет»: строка остаётся, сотруднику не видна. */
  is_available: boolean;
  sort_order: number;
  updated_at: string | null;
}

export interface Menu {
  items: MenuItem[];
  /** Порядок групп задаёт сервер — фронт не сортирует повторно. */
  categories: string[];
  /** Сколько позиций скрыто. У сотрудника всегда 0: он их не видит. */
  hidden: number;
}

export interface MenuDraft {
  name: string;
  category?: string;
  description?: string | null;
  price_rub?: number | null;
  sort_order?: number;
  is_available?: boolean;
}

export const fetchMenu = () => api<Menu>("/api/menu");

export const createMenuItem = (draft: MenuDraft) =>
  api<MenuItem>("/api/menu", { method: "POST", body: JSON.stringify(draft) });

export const updateMenuItem = (
  id: number,
  patch: Partial<MenuDraft>,
) =>
  api<MenuItem>(`/api/menu/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const deleteMenuItem = (id: number) =>
  api<void>(`/api/menu/${id}`, { method: "DELETE" });
