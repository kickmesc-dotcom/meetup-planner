import { api } from "./client";
import type { User } from "@/types";

/**
 * Вход по почте и паролю (B2B_PLATFORM_PLAN, шаг 2.1).
 *
 * Ручки `/api/auth/*` не требуют организации: она появляется только после
 * приглашения (шаг 2.2). Поэтому здесь нет ни одного запроса «за сотрудника» —
 * только про саму личность и её устройства.
 */

export interface AuthSession {
  /** Токен сессии. Показывается один раз — дальше живёт в localStorage. */
  token: string;
  expires_at: string;
  user: User;
}

export interface AuthDevice {
  id: number;
  created_at: string | null;
  last_seen_at: string | null;
  expires_at: string | null;
  user_agent: string | null;
  current: boolean;
}

export const loginRequest = (email: string, password: string) =>
  api<AuthSession>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const registerRequest = (
  email: string,
  password: string,
  displayName?: string,
) =>
  api<AuthSession>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({
      email,
      password,
      display_name: displayName?.trim() || null,
    }),
  });

/** Выход только с этого устройства. Сервер ответит `ok` и без валидного токена. */
export const logoutRequest = () =>
  api<{ ok: boolean }>("/api/auth/logout", { method: "POST" });

/** «Выйти везде»: гасит все живые сессии человека, включая текущую. */
export const logoutAllRequest = () =>
  api<{ revoked: number }>("/api/auth/logout-all", { method: "POST" });

export const fetchDevices = () => api<AuthDevice[]>("/api/auth/sessions");

export const revokeDevice = (id: number) =>
  api<void>(`/api/auth/sessions/${id}`, { method: "DELETE" });

/**
 * Запрос ссылки сброса. Сервер всегда отвечает `ok` — существование адреса не
 * подтверждается, поэтому и интерфейс не должен обещать «письмо отправлено
 * именно вам»: пишем «если адрес зарегистрирован, письмо ушло».
 */
export const requestPasswordReset = (email: string) =>
  api<{ ok: boolean }>("/api/auth/password/reset/request", {
    method: "POST",
    body: JSON.stringify({ email }),
  });

export const confirmPasswordReset = (token: string, password: string) =>
  api<{ ok: boolean }>("/api/auth/password/reset/confirm", {
    method: "POST",
    body: JSON.stringify({ token, password }),
  });

/**
 * Подтверждение адреса (шаг 2.1). Письмо приходит один раз при регистрации;
 * эту ручку зовём, если оно потерялось или попало в спам.
 */
export const requestEmailVerification = () =>
  api<{ ok: boolean; already: boolean }>("/api/auth/email/verify/request", {
    method: "POST",
  });

/** Подтвердить по токену из письма. Вход не нужен: письмо может открыть другое
 * устройство, где сессии ещё нет. */
export const confirmEmailVerification = (token: string) =>
  api<{ ok: boolean }>("/api/auth/email/verify/confirm", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
