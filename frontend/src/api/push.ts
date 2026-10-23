import { api } from "./client";

/** Что сервер сообщает браузеру: включён ли канал и с каким ключом подписываться. */
export interface PushConfig {
  enabled: boolean;
  public_key: string;
}

export interface PushDevice {
  id: number;
  user_agent: string | null;
  created_at: string;
  last_seen_at: string | null;
}

export interface PushSubscribeBody {
  endpoint: string;
  keys: { p256dh: string; auth: string };
  user_agent?: string;
}

export function fetchPushConfig(): Promise<PushConfig> {
  return api<PushConfig>("/push/config");
}

export function fetchPushDevices(): Promise<PushDevice[]> {
  return api<PushDevice[]>("/push/subscriptions");
}

export function subscribePush(body: PushSubscribeBody): Promise<{ ok: boolean }> {
  return api<{ ok: boolean }>("/push/subscriptions", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function unsubscribePush(endpoint: string): Promise<{ ok: boolean }> {
  return api<{ ok: boolean }>("/push/subscriptions", {
    method: "DELETE",
    body: JSON.stringify({ endpoint }),
  });
}

/** Тестовое уведомление на свои устройства: проверка цепочки, не «напоминание». */
export function sendTestPush(): Promise<{ ok: boolean; sent: number }> {
  return api<{ ok: boolean; sent: number }>("/push/test", { method: "POST" });
}

/**
 * VAPID-ключ приходит из API строкой base64url, а `PushManager.subscribe`
 * ждёт байты. Декодируем вручную: `atob` в старых webview есть, но
 * `Uint8Array.fromBase64` — нет.
 */
export function urlBase64ToUint8Array(
  base64: string,
): Uint8Array<ArrayBuffer> {
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
  const normalized = padded.replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(normalized);
  // Явный ArrayBuffer: браузерное API не принимает view поверх SharedArrayBuffer.
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}
