import { api } from "./client";
import type {
  AvailabilityRange,
  NewAvailabilityRange,
  User,
} from "@/types";

export const fetchMe = () => api<User>("/api/me");
export const fetchUsers = () => api<User[]>("/api/users");

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
