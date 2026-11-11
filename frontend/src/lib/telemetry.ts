/**
 * Отправка ошибок фронта в `POST /api/telemetry`.
 *
 * Зачем. Падение рендера или отклонённый промис раньше оставались в консоли
 * чужого браузера: узнать о нём можно было только со слов человека. Здесь
 * ошибка уходит на сервер с типом, текстом, стеком, путём и меткой сборки.
 *
 * Чего здесь нет и не должно быть: идентификатора пользователя, текстов
 * форм, query-строки и куки. Телеметрия — сигнал «что сломалось», а не канал
 * наблюдения за людьми.
 *
 * Почему не через `api()`: тот ставит токен и разбирает ответ как JSON. У
 * телеметрии нет ни пользователя, ни тела ответа, а ошибка часто случается
 * до входа — токена ещё нет.
 */
import { getApiBase } from "@/api/client";
import { deviceKind, platformName, tgVersion } from "@/lib/device";

const MAX_REPORTS = 5;
const DEDUPE_MS = 30_000;
const MAX_MESSAGE = 300;
const MAX_STACK = 4000;
const MAX_COMPONENT_STACK = 1500;
const MAX_PATH = 200;

export type ErrorKind = "render" | "error" | "rejection";

export interface ErrorReport {
  kind: ErrorKind;
  message: string;
  stack: string;
  component_stack: string;
  path: string;
  build: string;
  /** Тип устройства и платформа: «на Android у ленты» и «на ПК» — разные баги. */
  device: string;
  platform: string;
  tg_version: string;
  count: number;
}

let sent = 0;
const seen = new Map<string, number>();

/** Сброс состояния между тестами и после смены пользователя. */
export function resetTelemetry(): void {
  sent = 0;
  seen.clear();
}

/** Путь без query и якоря: `?access=…` в отчёт не попадает. */
export function cleanPath(path: string): string {
  return path.split("?")[0].split("#")[0].slice(0, MAX_PATH);
}

/**
 * Убрать из стека значения, похожие на токены.
 *
 * Стек обычно приходит без query, но ссылки в сообщениях об ошибках бывают
 * любые. Дешевле вычистить по шаблону, чем объяснять клиенту утечку.
 */
export function cleanStack(stack: string): string {
  return stack
    .replace(/(access|token|password|secret)=[^&\s)]+/gi, "$1=***")
    .slice(0, MAX_STACK);
}

export function buildReport(
  kind: ErrorKind,
  error: unknown,
  componentStack = "",
): ErrorReport {
  const message =
    error instanceof Error ? error.message : String(error ?? "Неизвестная ошибка");
  const stack = error instanceof Error && error.stack ? error.stack : "";
  const path =
    typeof window !== "undefined" ? cleanPath(window.location.pathname) : "";
  const build = (import.meta.env.VITE_BUILD_ID as string | undefined) ?? "";
  return {
    kind,
    message: message.slice(0, MAX_MESSAGE),
    stack: cleanStack(stack),
    component_stack: cleanStack(componentStack).slice(0, MAX_COMPONENT_STACK),
    path,
    build: build.slice(0, 40),
    device: deviceKind(),
    platform: platformName(),
    tg_version: tgVersion(),
    count: 1,
  };
}

/**
 * Отправить отчёт. Повторы одного и того же схлопываются: цикл перерисовки
 * иначе превратился бы в поток запросов с телефона клиента.
 *
 * @returns `true`, если запрос действительно ушёл.
 */
export function reportClientError(
  kind: ErrorKind,
  error: unknown,
  componentStack = "",
): boolean {
  if (typeof window === "undefined" || typeof fetch !== "function") return false;
  const report = buildReport(kind, error, componentStack);
  // Ключ — тип, сообщение и путь. Стек в ключ не идёт: у двух одинаковых
  // ошибок из разных мест он различается, и дедупликация перестала бы
  // работать именно в цикле перерисовки, ради которого она и нужна.
  const key = `${report.kind}|${report.message}|${report.path}`;
  const now = Date.now();
  const last = seen.get(key);
  if (last !== undefined && now - last < DEDUPE_MS) return false;
  if (sent >= MAX_REPORTS) return false;
  seen.set(key, now);
  sent += 1;

  try {
    void fetch(`${getApiBase()}/api/telemetry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(report),
      // `keepalive`: при падении человек часто сразу закрывает вкладку или
      // нажимает «Обновить» — обычный запрос браузер отменил бы.
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    // Приватный режим/запрет сети: телеметрия не должна ломать приложение.
    return false;
  }
  return true;
}

let installed = false;

/** Глобальные обработчики: ошибки вне React-дерева и отклонённые промисы. */
export function installGlobalErrorHandlers(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;

  window.addEventListener("error", (event) => {
    const error = event.error ?? new Error(event.message || "Ошибка окна");
    reportClientError("error", error);
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason =
      event.reason instanceof Error
        ? event.reason
        : new Error(String(event.reason ?? "Отклонённый промис"));
    reportClientError("rejection", reason);
  });
}
