import { ApiError, api, apiPublicUrl, getApiBase } from "./client";

/**
 * Фотоотчёты: снимок сжимается в браузере и уходит на сервер, а показывается
 * по подписанной ссылке.
 *
 * Зачем сжимать: камера телефона отдаёт 3–8 МБ (а iPhone в 48 Мп — и больше),
 * а лимит сервера — 8 МБ, да и мобильный интернет в России не всегда быстрый.
 * 1440 px по длинной стороне хватает, чтобы разглядеть рабочую зону, и обычно
 * это 200–500 КБ — то есть в 10–20 раз меньше исходника.
 *
 * P3.17: раньше проверка «больше 8 МБ» стояла ДО сжатия, поэтому большой
 * снимок с камеры отклонялся, хотя после сжатия влезал с запасом. Теперь
 * сначала уменьшаем, потом проверяем — и показываем точную причину отказа.
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
const MAX_SIDE = 1440;
const QUALITY = 0.78;
/** Выше этого — жмём второй раз посильнее, чтобы не гнать по мобильной сети. */
const SOFT_LIMIT = 900 * 1024;

interface Decoded {
  image: CanvasImageSource;
  width: number;
  height: number;
  close: () => void;
}

/**
 * Абсолютный URL картинки для `<img>`.
 *
 * В проде отдаём относительный путь: `/api/media/...` обслуживает Pages
 * Function, которая кэширует байты на краю Cloudflare. Так фото не зависит от
 * `hf.space`, который в России часто «дышит», и не грузится заново при каждом
 * открытии. Если в профиле выбрали другой сервер — идём прямо туда.
 */
export function mediaUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  const base = getApiBase();
  // `import.meta.env.DEV` — потому что в dev-сервере `/api` живёт на Vite-прокси.
  if (!import.meta.env.DEV && base === (import.meta.env.VITE_API_BASE ?? "")) {
    return path;
  }
  return apiPublicUrl(path);
}

/** Декодировать файл: сначала быстрый `createImageBitmap`, потом `<img>`. */
async function decode(file: File): Promise<Decoded | null> {
  try {
    const bitmap = await createImageBitmap(file);
    return {
      image: bitmap,
      width: bitmap.width,
      height: bitmap.height,
      close: () => bitmap.close?.(),
    };
  } catch {
    // Safari/WebView старых версий не умеет createImageBitmap для HEIC —
    // пробуем обычный <img>, он умеет больше форматов.
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return {
      image: img,
      width: img.naturalWidth,
      height: img.naturalHeight,
      close: () => URL.revokeObjectURL(url),
    };
  } catch {
    URL.revokeObjectURL(url);
    return null;
  }
}

function encode(canvas: HTMLCanvasElement, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
}

/**
 * Уменьшить снимок перед отправкой.
 *
 * Если браузер не умеет декодировать файл (HEIC на iPhone, битый файл) —
 * возвращаем исходник: пусть решает сервер, а не молчаливая ошибка на клиенте.
 */
export async function shrinkImage(file: File): Promise<Blob> {
  if (!file.type.startsWith("image/") || file.type === "image/gif") return file;
  const decoded = await decode(file);
  if (!decoded) return file;

  try {
    const scale = Math.min(
      1,
      MAX_SIDE / Math.max(decoded.width, decoded.height),
    );
    const width = Math.max(1, Math.round(decoded.width * scale));
    const height = Math.max(1, Math.round(decoded.height * scale));
    if (scale === 1 && file.size <= SOFT_LIMIT) return file;

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.drawImage(decoded.image, 0, 0, width, height);

    let blob = await encode(canvas, QUALITY);
    if (blob && blob.size > SOFT_LIMIT) {
      blob = (await encode(canvas, 0.6)) ?? blob;
    }
    if (!blob) return file;
    return blob.size < file.size ? blob : file;
  } finally {
    decoded.close();
  }
}

/** Расширение по типу блоба: сервер снифает байты, но имя должно быть честным. */
function fileName(type: string): string {
  const ext =
    type === "image/png" ? "png" : type === "image/webp" ? "webp" : "jpg";
  return `photo-${Date.now()}.${ext}`;
}

async function send(form: FormData): Promise<MediaItem> {
  // Через свой домен: телефон → ближайший край Cloudflare → HF. Прямая
  // загрузка на hf.space на мобильной сети в РФ часто обрывается на середине.
  return api<MediaItem>(
    "/api/media",
    { method: "POST", body: form },
    { sameOrigin: true },
  );
}

/**
 * Отправка с одним повтором на сетевую ошибку.
 *
 * Ответ сервера (4xx) повторять бессмысленно — там уже сказано, что не так.
 * А оборванный на полпути POST в метро/на кухне — обычное дело, и второй
 * заход экономит человеку весь сценарий заново.
 */
export async function uploadPhoto(file: File): Promise<MediaItem> {
  const body = await shrinkImage(file);
  if (body.size > MAX_UPLOAD_BYTES) {
    throw new Error("Фото больше 8 МБ даже после сжатия — выбери снимок поменьше.");
  }
  const build = () => {
    const form = new FormData();
    form.append("file", body, fileName(body.type));
    return form;
  };
  try {
    return await send(build());
  } catch (error) {
    // 502–504 — это край/контейнер, а не отказ по существу: повторяем.
    const retryable =
      !(error instanceof ApiError) ||
      [502, 503, 504].includes(error.status);
    if (!retryable) throw error;
    await new Promise((resolve) => setTimeout(resolve, 800));
    return send(build());
  }
}

/** Фото из чата, ещё не закешированное: сервер скачает его сам. */
export function telegramPhotoUrl(url: string | null | undefined): string | null {
  return mediaUrl(url);
}
