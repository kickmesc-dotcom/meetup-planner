import { api, apiPublicUrl } from "./client";

/**
 * Фотоотчёты: снимок сжимается в браузере и уходит на сервер, а показывается
 * по подписанной ссылке.
 *
 * Зачем сжимать: камера телефона отдаёт 3–8 МБ, а лимит сервера — 8 МБ, да и
 * мобильный интернет в России не всегда быстрый. 1600 px по длинной стороне
 * хватает, чтобы разглядеть рабочую зону, и обычно это 150–400 КБ.
 */

export interface MediaItem {
  id: number;
  url: string;
  mime: string;
  width: number | null;
  height: number | null;
  size: number;
}

/** Лимит сервера (`services/hr_media.MAX_BYTES`). */
export const MAX_UPLOAD_BYTES = 8 * 1024 * 1024;
const MAX_SIDE = 1600;
const QUALITY = 0.82;

export function mediaUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  return apiPublicUrl(path);
}

/**
 * Уменьшить снимок перед отправкой. Если браузер не умеет декодировать файл
 * (например, HEIC на Android), возвращаем исходник — сервер сам решит, годится
 * ли он; главное не терять фото молча.
 */
export async function shrinkImage(file: File): Promise<Blob> {
  if (!file.type.startsWith("image/") || file.type === "image/gif") return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.size <= 900 * 1024) return file;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", QUALITY),
    );
    bitmap.close?.();
    return blob ?? file;
  } catch {
    return file;
  }
}

export async function uploadPhoto(file: File): Promise<MediaItem> {
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new Error("Фото больше 8 МБ — выбери снимок поменьше.");
  }
  const body = await shrinkImage(file);
  const form = new FormData();
  const name = file.name?.replace(/\.[^.]+$/, "") || "photo";
  form.append("file", body, `${name}.jpg`);
  return api<MediaItem>("/api/media", { method: "POST", body: form });
}

/** Фото из чата, ещё не закешированное: сервер скачает его сам. */
export function telegramPhotoUrl(url: string | null | undefined): string | null {
  return mediaUrl(url);
}
