import { getInitData } from "@/tg/webapp";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(`${status}: ${detail}`);
  }
}

/**
 * Превращает технический detail/status в человечный русский текст.
 * Возвращает короткую строку, которую можно показать через showAlert или inline.
 */
export function humanizeApiError(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail || "";
    if (d.startsWith("cooldown:")) {
      const sec = Number(d.split(":")[1] ?? 0);
      const m = Math.ceil(sec / 60);
      return `Кулдаун ещё ${m} мин.`;
    }
    if (d.startsWith("telegram_retry_after:")) {
      const sec = Number(d.split(":")[1] ?? 0);
      return `Telegram просит подождать ${sec} с — попробуй ещё раз.`;
    }
    if (d === "telegram_network_timeout") {
      return "Telegram сейчас недоступен (таймаут сети). Попробуй через минуту.";
    }
    if (d === "telegram_forbidden") {
      return "Бот не может писать в групповой чат. Проверь права бота.";
    }
    if (d.startsWith("telegram_api_error")) {
      return "Ошибка Telegram API. Попробуй ещё раз.";
    }
    if (d === "telegram_send_failed") {
      return "Не получилось отправить сообщение в чат. Попробуй ещё раз.";
    }
    if (e.status === 502 || e.status === 503 || e.status === 504) {
      return "Сервис временно недоступен. Попробуй через минуту.";
    }
    if (e.status === 401 || e.status === 403) {
      return "Нет доступа.";
    }
    if (e.status === 404) {
      return "Не найдено.";
    }
    return d || `Ошибка ${e.status}`;
  }
  if (e instanceof Error) return e.message;
  return "Неизвестная ошибка";
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const initData = getInitData();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `tma ${initData}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const res = await fetch(url, { ...init, headers });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
