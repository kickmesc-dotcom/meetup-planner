/**
 * Фотографии через свой домен: `/api/media/*` → бэкенд (по умолчанию Amvera).
 *
 * Зачем прокси, если `<img>` умеет ходить на `hf.space` напрямую:
 *
 * 1. **Ближе к телефону.** Мини-апп живёт на `semitaskbot.pages.dev`, его
 *    отдаёт Cloudflare. Байты фото с `hf.space` в России идут медленно и
 *    иногда обрываются — маленький JSON это переживает, снимок на 300–500 КБ
 *    нет. Через этот прокси фото идёт с того же домена, что и приложение.
 * 2. **Кэш на краю.** Ссылка на фото неизменна (`/api/media/{id}?s=...`),
 *    поэтому после первого скачивания ответ лежит в кэше Cloudflare: повторный
 *    просмотр не ходит в HF вообще, даже если контейнер спит.
 * 3. **Подпись остаётся серверной.** Прокси не проверяет и не подделывает
 *    `s`: он просто пересылает запрос, а решает бэкенд.
 *
 * Если апстрим недоступен — отвечаем редиректом на прямой адрес того же
 * бэкенда. Такой ответ браузер всё равно покажет, то есть прокси не
 * становится единственной точкой отказа для уже работающих ссылок.
 */

interface Env {
  /** Переопределяется в настройках Pages, по умолчанию — текущий бэкенд. */
  API_ORIGIN?: string;
}

/**
 * Типы Cloudflare Pages держим локально: `@cloudflare/workers-types` в проект
 * не тянем, а глобальные `PagesFunction`/`caches.default` без него не
 * резолвятся. Функция исполняется на краю, поэтому контракт здесь минимальный.
 */
interface PagesContext<E> {
  request: Request;
  env: E;
  waitUntil(promise: Promise<unknown>): void;
}

type PagesHandler<E> = (context: PagesContext<E>) => Promise<Response>;

interface EdgeCache {
  match(request: Request): Promise<Response | undefined>;
  put(request: Request, response: Response): Promise<void>;
}

/**
 * Тот же хост, что и у API-прокси: фото и JSON должны идти с одного бэкенда,
 * иначе подпись ссылки и данные разъедутся между двумя базами-зеркалами.
 * Переключено с HF (США) на Amvera (Варшава) — см. `docs/RELOCATION.md`.
 */
const FALLBACK_ORIGIN = "https://meetup-planner-youmakemefry.waw0.amvera.tech";
/** Фото по id неизменны: кэшируем надолго. */
const CACHE_SECONDS = 7 * 24 * 60 * 60;

export const onRequest: PagesHandler<Env> = async (context) => {
  const request = context.request;
  const url = new URL(request.url);
  const origin = (context.env.API_ORIGIN || FALLBACK_ORIGIN).replace(/\/$/, "");
  const upstreamUrl = `${origin}${url.pathname}${url.search}`;

  if (request.method === "POST") {
    // Загрузка снимка: телефон отдаёт тело на край Cloudflare, а не напрямую
    // на HF. Заголовки авторизации — часть контракта бэкенда, их не трогаем.
    const headers = new Headers();
    for (const name of [
      "authorization",
      "content-type",
      "accept",
      "x-simulation-session",
    ]) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    let upstream: Response;
    try {
      upstream = await fetch(upstreamUrl, {
        method: "POST",
        headers,
        body: request.body,
        // Cloudflare принимает потоковое тело без `duplex`, а типы RequestInit
        // в DOM-библиотеке его ещё не знают.
      } as RequestInit);
    } catch {
      return new Response('{"detail":"media_proxy_unavailable"}', {
        status: 502,
        headers: { "content-type": "application/json", "cache-control": "no-store" },
      });
    }
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "content-type":
          upstream.headers.get("content-type") ?? "application/json",
        "cache-control": "no-store",
      },
    });
  }

  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("Method not allowed", { status: 405 });
  }

  // Ключ кэша без `retry`-параметра: повтор после сбоя не должен плодить
  // копии одного и того же файла.
  const cacheKey = new Request(
    `${url.origin}${url.pathname}${url.search.replace(/[?&]retry=\d+/g, "")}`,
    { method: "GET" },
  );
  const cache = (caches as unknown as { default: EdgeCache }).default;
  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
      method: request.method,
      headers: {
        accept: request.headers.get("accept") ?? "image/*",
      },
    });
  } catch {
    return Response.redirect(upstreamUrl, 302);
  }

  if (!upstream.ok) {
    // 403/404 повторять и кэшировать нечего, а 5xx лучше отдать прямой ссылкой:
    // апстрим поднимется — фото откроется.
    if (upstream.status >= 500) return Response.redirect(upstreamUrl, 302);
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "text/plain" },
    });
  }

  const response = new Response(upstream.body, upstream);
  response.headers.set("cache-control", `public, max-age=${CACHE_SECONDS}, immutable`);
  response.headers.set("x-media-proxy", "pages");
  context.waitUntil(cache.put(cacheKey, response.clone()));
  return response;
};
