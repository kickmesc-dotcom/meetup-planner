import { getInitData } from "@/tg/webapp";
import { useSimulation } from "@/store/simulation";

const ENV_API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";
const API_BASE_KEY = "buff.api_base";

/**
 * Адрес API можно переключить на лету (без пересборки).
 *
 * Зачем: в России основной домен может стать недоступен — провайдер, блокировка
 * Cloudflare или лежащий хостинг. Резервный контур (другой домен/свой сервер)
 * поднимается заранее, а сотрудник вводит его в профиле («Сервер»), и приложение
 * продолжает работать. Это дешевле, чем выпускать новый билд в момент аварии.
 */
/**
 * Токен входа в веб-версию (прямая ссылка на Pages, вне Telegram).
 *
 * Внутри мини-аппа личность подтверждает `initData` — его подписывает бот.
 * В обычном браузере этого нет, поэтому сервер выдаёт личный токен, а мы храним
 * его в `localStorage`: ссылка открывается один раз, дальше работают закладка
 * и обычные перезагрузки страницы.
 *
 * Токен — это пароль. Из адресной строки он сразу убирается (см.
 * `captureAccessTokenFromUrl`), чтобы не остаться в истории, закладках и логах
 * прокси.
 */
const ACCESS_TOKEN_KEY = "semitask.access_token";

export function getAccessToken(): string | null {
  try {
    return localStorage.getItem(ACCESS_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setAccessToken(token: string): void {
  try {
    localStorage.setItem(ACCESS_TOKEN_KEY, token.trim());
  } catch {
    // приватный режим — вход будет работать до перезагрузки
  }
}

export function clearAccessToken(): void {
  try {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
  } catch {
    // ignore
  }
}

/**
 * Забрать `?access=…` из адреса в `localStorage` и вычистить его из строки.
 *
 * Возвращает `true`, если токен пришёл: вызывающий может перерисоваться.
 * `history.replaceState` не перезагружает страницу и не создаёт запись в
 * истории — ссылка с секретом нигде не оседает.
 */
export function captureAccessTokenFromUrl(): boolean {
  if (typeof window === "undefined") return false;
  let url: URL;
  try {
    url = new URL(window.location.href);
  } catch {
    return false;
  }
  const token = url.searchParams.get("access");
  if (!token) return false;
  setAccessToken(token);
  url.searchParams.delete("access");
  try {
    const next = `${url.pathname}${url.search}${url.hash}`;
    window.history.replaceState(null, "", next);
  } catch {
    // старый webview без history API — токен уже сохранён, это главное
  }
  return true;
}

export function getApiBase(): string {
  try {
    const saved = localStorage.getItem(API_BASE_KEY);
    if (saved && /^https?:\/\//.test(saved)) return saved.replace(/\/+$/, "");
  } catch {
    // приватный режим/запрет storage — работаем на адресе из сборки
  }
  return ENV_API_BASE;
}

/** Сохранить адрес API. `null` — вернуть адрес из сборки. */
export function setApiBase(value: string | null): void {
  try {
    if (!value) localStorage.removeItem(API_BASE_KEY);
    else localStorage.setItem(API_BASE_KEY, value.replace(/\/+$/, ""));
  } catch {
    // ignore
  }
}

export function apiBaseLabel(): string {
  return getApiBase() || "текущий сайт";
}

/**
 * GHG11(10): абсолютный URL публичного `<img>`-ресурса (аватарка/превью медиа).
 * Медиа-превью отдаётся без tma-заголовка, как `/api/avatar/{id}`, поэтому
 * тег `<img>` работает с обычным URL — и в dev через VITE_API_BASE, и в проде.
 */
export function apiPublicUrl(path: string): string {
  return path.startsWith("http") ? path : `${getApiBase()}${path}`;
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
    // Пул сотрудников: ручное заведение по ID и снапшоты состава. Коды
    // серверные, поэтому текст живёт здесь — одна правка на все экраны.
    const roster: Record<string, string> = {
      bad_telegram_id: "ID состоит только из цифр — скопируй его из профиля Telegram.",
      demo_id_reserved: "Этот диапазон ID занят тестовым пулом: для человека он не подойдёт.",
      already_exists: "Такой ID уже заведён в боте.",
      employee_fired: "Этот человек уволен — верни его из корзины в списке ниже.",
      bad_role: "Такой роли нет.",
      department_not_found: "Подразделение не найдено — обнови список.",
      snapshot_not_found: "Снимок уже удалён.",
    };
    if (d in roster) return roster[d];
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
    // Админские операции и увольнение: коды вместо текстов, чтобы их можно
    // было показать в диалоге подтверждения.
    if (d === "employee_fired") {
      return "Доступ закрыт: профиль уволен. Обратись к управляющему.";
    }
    if (d === "already_fired") return "Этот сотрудник уже уволен.";
    if (d === "already_purged") {
      return "Данные уже удалены: восстановить нельзя.";
    }
    if (d === "not_fired") return "Сотрудник не в корзине — восстанавливать нечего.";
    if (d === "cannot_fire_self") return "Себя уволить нельзя.";
    if (d === "cannot_fire_admin") {
      return "Управляющего увольняет только администратор.";
    }
    if (d === "already_done") return "Поручение уже зачтено.";
    // Фото: сервер отвечает кодами, текст — здесь, чтобы человек понимал,
    // что делать дальше (особенно с HEIC из галереи iPhone).
    if (d === "not_an_image") {
      return "Это не изображение или формат не поддерживается. Нужен JPEG, PNG или WebP.";
    }
    if (d === "file_too_large") {
      return "Фото больше 8 МБ — выбери снимок поменьше.";
    }
    if (d === "empty_file") return "Файл пустой — выбери другой снимок.";
    if (d === "media_not_found") return "Фото не найдено — приложи его заново.";
    if (d === "assignment_not_found") {
      return "У этого поручения нет такого исполнителя.";
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
  /**
   * `sameOrigin` — гнать запрос через свой домен (Pages Function), а не прямо
   * на бэкенд. Нужно фото: POST снимка идёт с телефона на край Cloudflare,
   * а уже оттуда в HF — так слабый мобильный канал не теряет загрузку.
   * В dev-сервере запрос всё равно идёт на Vite-прокси.
   */
  options: { sameOrigin?: boolean } = {},
): Promise<T> {
  const initData = getInitData();
  const accessToken = initData ? null : getAccessToken();
  const headers = new Headers(init.headers);
  // Внутри Telegram главнее `initData`: локальный токен браузера (мог
  // остаться от прошлого входа) не должен подменять личность.
  if (initData) headers.set("Authorization", `tma ${initData}`);
  else if (accessToken) headers.set("X-Access-Token", accessToken);
  // Режим проверки: сервер подменяет профиль на теневой. Без заголовка это
  // обычный запрос настоящего пользователя.
  const simulationId = useSimulation.getState().sessionId;
  if (simulationId) headers.set("X-Simulation-Session", String(simulationId));
  // FormData сам ставит boundary: если перезаписать заголовок JSON'ом,
  // multipart-загрузка фото ломается на разборе тела.
  if (
    init.body &&
    !headers.has("Content-Type") &&
    !(init.body instanceof FormData)
  ) {
    headers.set("Content-Type", "application/json");
  }

  const sameOrigin = options.sameOrigin && !import.meta.env.DEV;
  const url = path.startsWith("http")
    ? path
    : `${sameOrigin ? "" : getApiBase()}${path}`;
  const res = await fetch(url, { ...init, headers });

  if (!res.ok) {
    // Токен веб-версии отозвали или истёк срок: забываем его, чтобы приложение
    // показало «нужен вход», а не долбило сервер мёртвым заголовком.
    if (res.status === 401 && accessToken && !initData) clearAccessToken();
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore
    }
    // Сеанс проверки мог закончиться, пока приложение было свёрнуто (сервер
    // перезапустили, базу подменили). Заголовок с мёртвым ID вешал бы все
    // запросы в 409, поэтому забываем сеанс и повторяем уже как себя.
    if (
      simulationId &&
      res.status === 409 &&
      (detail === "simulation_inactive" || detail === "simulation_not_found")
    ) {
      useSimulation.getState().clear();
      return api<T>(path, init);
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
