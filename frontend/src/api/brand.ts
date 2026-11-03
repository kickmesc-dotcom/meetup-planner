import { api } from "./client";

/**
 * Бренд организации (B2B_PLATFORM_PLAN, шаг 4.4).
 *
 * `name`, `color` и `logo_url` — то, что клиент видит вместо имени платформы.
 * Пустой бренд не ошибка: сервер в этом случае отдаёт имя организации, поэтому
 * интерфейс не решает сам, что показать.
 */
export interface OrgBrand {
  name: string;
  color: string;
  logo_url: string | null;
  bot_username: string | null;
  /** `true` — это имя клиента, `false` — имя организации по умолчанию. */
  is_custom: boolean;
}

export const fetchBrand = () => api<OrgBrand>("/api/brand");

/**
 * Сохранить бренд. Отсутствующее поле не меняется, пустая строка у логотипа —
 * сброс: форма присылает только то, что человек реально правил.
 */
export const updateBrand = (body: {
  name?: string;
  color?: string;
  logo_url?: string;
}) =>
  api<OrgBrand>("/api/org/brand", {
    method: "PATCH",
    body: JSON.stringify(body),
  });

/** Сбросить бренд к имени организации. */
export const resetBrand = () =>
  api<OrgBrand>("/api/org/brand", { method: "DELETE" });
