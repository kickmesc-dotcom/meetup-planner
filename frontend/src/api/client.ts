import { getInitData } from "@/tg/webapp";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

/**
 * GHG11(10): абсолютный URL публичного `<img>`-ресурса (аватарка/превью медиа).
 * Медиа-превью отдаётся без tma-заголовка, как `/api/avatar/{id}`, поэтому
 * тег `<img>` работает с обычным URL — и в dev через VITE_API_BASE, и в проде.
 */
export function apiPublicUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_BASE}${path}`;
}

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(`${status}: ${detail}`);
  }
}

/**
 * GHG10-ops: ручки на сервере нет вовсе — фронт уехал впереди бэкенда.
 *
 * FastAPI на неизвестный путь отдаёт 404 с голым `detail="Not Found"` (у наших
 * осмысленных отказов всегда свой код в detail). Признак важен, потому что
 * бэкенд на Amvera пересобирается вручную и может отставать на несколько
 * сборок — именно так кнопка, которой ещё нет на сервере, отвечала 404.
 */
export function isEndpointMissing(e: unknown): boolean {
  return e instanceof ApiError && e.status === 404 && (!e.detail || e.detail === "Not Found");
}

/**
 * Превращает технический detail/status в человечный русский текст.
 * Возвращает короткую строку, которую можно показать через showAlert или inline.
 */
export function humanizeApiError(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail || "";
    // GHG10 Э8: функция закрыта рангом (`rank_required:<N>`).
    if (d.startsWith("rank_required:")) {
      const lvl = Number(d.split(":")[1] ?? 0);
      return lvl > 0
        ? `🔒 Откроется с ${lvl} ранга — качай опыт в чате и календаре.`
        : "🔒 Эта функция пока недоступна.";
    }
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
    if (d === "no_recent_media") {
      return "Бот ещё не видел ни одного мема такого типа — нужно, чтобы кто-то скинул медиа в чат после запуска бота.";
    }
    // GHG10 Э10.3/Э11: отказы игровых ручек. Сервер отдаёт коды, а не тексты
    // (текст праздника/сумму доната фронт знает сам), поэтому переводим здесь.
    if (d === "game_disabled") {
      return "Игровая система сейчас выключена.";
    }
    if (d === "holiday_date_taken") {
      return "На эту дату праздник уже есть.";
    }
    if (d === "holiday_day_invalid" || d === "holiday_month_invalid") {
      return "Такой даты не существует — проверь день и месяц.";
    }
    if (d === "holiday_message_empty") {
      return "Напиши текст поздравления — без него праздник некуда публиковать.";
    }
    if (d === "holiday_not_found") {
      return "Праздник уже удалён.";
    }
    if (d === "self_donation") {
      return "Себе дарить опыт не получится 🙂";
    }
    if (d === "not_today_birthday") {
      return "Донат доступен только в сам день рождения именинника.";
    }
    if (d === "already_donated") {
      return "Ты уже дарил опыт этому участнику в этом году.";
    }
    if (d === "not_enough_xp") {
      return "Своих очков не хватает: чтобы подарить 100 XP, надо их иметь. В чат уже улетела насмешка 😈";
    }
    if (e.status === 502 || e.status === 503 || e.status === 504) {
      return "Сервис временно недоступен. Попробуй через минуту.";
    }
    if (e.status === 401 || e.status === 403) {
      return "Нет доступа.";
    }
    if (e.status === 404) {
      if (isEndpointMissing(e)) {
        return "Сервер ещё не обновился: функция появится после пересборки бэкенда.";
      }
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
