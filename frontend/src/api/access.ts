import { api } from "./client";

/**
 * Ссылки входа в веб-версию (браузер снаружи Telegram).
 *
 * Сам токен приходит один раз — в `url` при выпуске. В списке его нет никогда:
 * только даты и признак «жива», иначе смысл отзыва пропадает.
 */
export interface AccessLink {
  id: number;
  label: string;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  is_active: boolean;
  /** Эта ссылка — та, по которой сейчас открыто приложение. */
  is_current: boolean;
}

export interface AccessLinkCreated {
  id: number;
  url: string;
  expires_at: string;
}

export const fetchAccessLinks = () => api<AccessLink[]>("/api/me/access-links");

export const createAccessLink = (label = "Открыть на компьютере") =>
  api<AccessLinkCreated>("/api/me/access-links", {
    method: "POST",
    body: JSON.stringify({ label }),
  });

export const revokeAccessLink = (id: number) =>
  api<void>(`/api/me/access-links/${id}`, { method: "DELETE" });
