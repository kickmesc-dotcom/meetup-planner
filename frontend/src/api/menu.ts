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
  /** Цена в целых единицах валюты организации. `null` — «по запросу». */
  price_rub: number | null;
  /** Снимок блюда: подписанная ссылка и id, чтобы отправить его обратно. */
  photo_blob_id: number | null;
  photo_url: string | null;
  /**
   * `false` — позиция в стоп-листе: блюдо остаётся в меню, но с пометкой
   * «нет в наличии». Сотрудник видит её, потому что именно он говорит гостю,
   * что заказать нельзя.
   */
  is_available: boolean;
  sort_order: number;
  updated_at: string | null;
}

export interface Menu {
  items: MenuItem[];
  /** Порядок групп задаёт сервер — фронт не сортирует повторно. */
  categories: string[];
  /** Сколько позиций в стоп-листе. */
  stopped: number;
  /** Валюта цен организации (`RUB`, `KZT`, `UZS`…). */
  currency: string;
}

export interface MenuDraft {
  name: string;
  category?: string;
  description?: string | null;
  price_rub?: number | null;
  /** `null` — убрать фото с позиции. */
  photo_blob_id?: number | null;
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

/**
 * Валюта цен — свойство организации, а не позиции: официант называет гостю
 * одну цену, и две валюты в одном меню были бы ошибкой данных.
 */
export const setMenuCurrency = (currency: string) =>
  api<{ currency: string }>("/api/menu/currency", {
    method: "PATCH",
    body: JSON.stringify({ currency }),
  });
