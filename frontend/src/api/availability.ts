import { api } from "./client";
import type {
  AvailabilityRange,
  NewAvailabilityRange,
  User,
} from "@/types";

export const fetchMe = () => api<User>("/api/me");
export const fetchUsers = () => api<User[]>("/api/users");

// E7: per-user UI prefs (hide_greeting на главной)
// GHG8 P4.1.b: + welcome_format — единый формат юзера в welcome-блоках.
export type WelcomeFormat = "name" | "avatar" | "both";
export interface UiPrefs {
  hide_greeting: boolean;
  welcome_format: WelcomeFormat;
}
export const fetchUiPrefs = () => api<UiPrefs>("/api/me/ui-prefs");
export const updateUiPrefs = (prefs: Partial<UiPrefs>) =>
  api<UiPrefs>("/api/me/ui-prefs", {
    method: "PUT",
    body: JSON.stringify(prefs),
  });

export const fetchRanges = (from: Date, to: Date) =>
  api<AvailabilityRange[]>(
    `/api/availability?from=${from.toISOString()}&to=${to.toISOString()}`,
  );

export const createRange = (body: NewAvailabilityRange) =>
  api<AvailabilityRange>("/api/availability", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const patchRange = (
  id: number,
  body: Partial<NewAvailabilityRange> & { expected_updated_at?: string },
) =>
  api<AvailabilityRange>(`/api/availability/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteRange = (id: number) =>
  api<void>(`/api/availability/${id}`, { method: "DELETE" });
