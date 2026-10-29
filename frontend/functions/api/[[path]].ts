/**
 * API через свой домен: `/api/*` → бэкенд (по умолчанию HF Space).
 *
 * Зачем. Приложение живёт на `semitaskbot.pages.dev`, API — на чужом домене.
 * Каждый запрос с `Authorization` — «непростой» по CORS, поэтому браузер
 * сначала спрашивает разрешение отдельным `OPTIONS`, и только потом делает сам
 * запрос: два круга до сервера на каждый адрес. На канале с RTT ~0,3–0,5 с это
 * половина времени открытия экрана (замеры — `docs/DESKTOP_PERF.md`).
 * Через этот прокси браузер видит СВОЙ origin: preflight'а нет вовсе.
 *
 * Что прокси НЕ делает:
 *
 * * **не кэширует.** Личные данные (профиль, поручения, настройки) в общем
 *   кэше — это чужие данные в чужой сессии. Поэтому ответы уходят с
 *   `private, no-store`, а кэш фото остаётся там, где он безопасен, — в
 *   отдельной функции `functions/api/media/[[path]].ts` (там URL неизменен и
 *   подпись проверяет бэкенд).
 * * **не переписывает авторизацию.** `Authorization`, `X-Access-Token`,
 *   `X-Simulation-Session` уходят как есть: личность подтверждает сервер.
 * * **не решает, что можно.** Права, роли и тенант живут на бэкенде; прокси —
 *   транспорт, а не второй слой правил (иначе однажды разошёлся бы с ними).
 *
 * Тело запроса и ответа передаётся потоком: фото и выгрузки не буферизуются в
 * память воркера.
 */

interface Env {
  /** Переопределяется в настройках Pages; по умолчанию — текущий бэкенд. */
  API_ORIGIN?: string;
}

/**
 * Типы Cloudflare Pages держим локально: `@cloudflare/workers-types` в проект
 * не тянем, а глобальные `PagesFunction` без него не резолвятся (тот же приём,
 * что в медиа-прокси).
 */
interface PagesContext<E> {
  request: Request;
  env: E;
  waitUntil(promise: Promise<unknown>): void;
}

type PagesHandler<E> = (context: PagesContext<E>) => Promise<Response>;

const FALLBACK_ORIGIN = "https://fryesw-meetup-planner-backend.hf.space";

/**
 * Заголовки, которые нельзя пересылать как есть.
 *
 * `content-encoding` и `content-length` описывают ТЕЛО на проводе, а `fetch`
 * уже распаковал его — с ними браузер получил бы битый ответ или оборванную
 * загрузку. Остальные — hop-by-hop: они относятся к конкретному соединению.
 */
const DROP = new Set([
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
  "keep-alive",
  "upgrade",
  "host",
  // CORS-заголовки апстрима тут не нужны: запрос пришёл со своего же origin,
  // а лишний `allow-origin` только путает диагностику.
  "access-control-allow-origin",
  "access-control-allow-credentials",
  "access-control-allow-methods",
  "access-control-allow-headers",
  "access-control-max-age",
  "access-control-expose-headers",
]);

function copyHeaders(from: Headers, { drop }: { drop: Set<string> }): Headers {
  const out = new Headers();
  from.forEach((value, name) => {
    const key = name.toLowerCase();
    if (drop.has(key)) return;
    // `set-cookie` приходит списком, а `Headers.forEach` склеил бы его в одну
    // строку — несколько печенек превратились бы в одну битую.
    if (key === "set-cookie") return;
    out.set(name, value);
  });
  const cookies = (from as unknown as { getSetCookie?: () => string[] }).getSetCookie?.();
  for (const cookie of cookies ?? []) out.append("set-cookie", cookie);
  return out;
}

export const onRequest: PagesHandler<Env> = async (context) => {
  const request = context.request;
  const url = new URL(request.url);
  const origin = (context.env.API_ORIGIN || FALLBACK_ORIGIN).replace(/\/$/, "");
  const upstreamUrl = `${origin}${url.pathname}${url.search}`;

  const headers = copyHeaders(request.headers, { drop: DROP });
  // Origin/referer нашего домена апстриму не нужны: его CORS проверяет список
  // из настроек, а прокси — не браузер. Оставляем только то, что описывает
  // запрос и личность.
  headers.delete("origin");
  headers.delete("referer");

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
      method: request.method,
      headers,
      // Потоковое тело: большие загрузки не проходят через память целиком.
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      redirect: "manual",
    } as RequestInit);
  } catch {
    return new Response('{"detail":"proxy_unavailable"}', {
      status: 502,
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    });
  }

  const responseHeaders = copyHeaders(upstream.headers, { drop: DROP });
  // По умолчанию — ничего личного в кэш: ответ зависит от человека и от смены.
  // Исключение — когда САМ бэкенд явно объявил ответ публичным (аватарки и
  // подписка на календарь): это его решение, и прокси не должен его тихо
  // отменять. Иначе аватарки в списках перестали бы кэшироваться и грузились
  // бы заново на каждом экране.
  const upstreamCache = (upstream.headers.get("cache-control") ?? "")
    .trim()
    .toLowerCase();
  if (!upstreamCache.startsWith("public")) {
    responseHeaders.set("cache-control", "private, no-store");
  }
  responseHeaders.set("x-api-proxy", "pages");

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
};
