/*
 * Service worker SemiTaskBot: оболочка приложения и офлайн-старт.
 *
 * Зачем вообще. Приложение ставят на домашний экран; без service worker оно
 * открывается только при живой сети, а при плохом мобильном интернете человек
 * видит белую страницу вместо «нет связи». С SW оболочка (HTML, JS, CSS, шрифт
 * иконок) уже лежит в кеше, и приложение стартует даже в метро.
 *
 * Что НЕ кешируем сознательно:
 *  • `/api/*` — данные смены. Показывать вчерашние задачи как сегодняшние хуже,
 *    чем честную ошибку: сервер отвечает, приложение показывает своё состояние
 *    «нет связи» и кнопку «повторить»;
 *  • `/tg/*` — вебхук и служебные ручки;
 *  • чужие origin (Telegram SDK, HF) — их кеш не наш.
 *
 * Стратегии:
 *  • переход по странице — сеть, при ошибке кешированный `index.html`. Так
 *    баннер «доступна новая версия» не нужен: свежий HTML подхватывается сам;
 *  • файлы сборки (`/assets/…`, иконки, манифест) — из кеша, иначе сеть. У них
 *    в имени хеш, поэтому кеш не может «устареть»;
 *  • иконки/манифест попадают в кеш ещё при установке.
 *
 * Обновление: при изменении этого файла браузер ставит новый SW, `activate`
 * чистит кеши прошлых версий. Версию поднимать руками при правке списка SHELL.
 */
const VERSION = "v1";
const SHELL_CACHE = `semi-shell-${VERSION}`;
const ASSET_CACHE = `semi-assets-${VERSION}`;

const SHELL = [
  "/",
  "/index.html",
  "/manifest.webmanifest",
  "/icon-192.png",
  "/icon-512.png",
  "/apple-touch-icon.png",
  "/favicon.ico",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((key) => key !== SHELL_CACHE && key !== ASSET_CACHE)
          .map((key) => caches.delete(key)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  let url;
  try {
    url = new URL(request.url);
  } catch {
    return;
  }
  if (url.origin !== self.location.origin) return;
  // Данные всегда из сети: устаревшая смена опаснее ошибки.
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/tg/")) return;

  if (request.mode === "navigate") {
    event.respondWith(networkFirst(request));
    return;
  }

  if (
    url.pathname.startsWith("/assets/") ||
    SHELL.includes(url.pathname) ||
    /\.(png|ico|svg|webmanifest|woff2?)$/.test(url.pathname)
  ) {
    event.respondWith(cacheFirst(request));
  }
});

async function networkFirst(request) {
  const cache = await caches.open(SHELL_CACHE);
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      // Кешируем именно оболочку по корневому адресу: любой маршрут SPA
      // (/invite, /reset) отдаёт тот же index.html.
      await cache.put("/index.html", response.clone());
    }
    return response;
  } catch {
    const cached = await cache.match("/index.html");
    if (cached) return cached;
    return new Response(
      "Нет сети, а оболочка ещё не сохранена. Открой приложение один раз с интернетом.",
      {
        status: 503,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      },
    );
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(ASSET_CACHE);
  const hit = await cache.match(request);
  if (hit) return hit;
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      await cache.put(request, response.clone());
    }
    return response;
  } catch {
    return Response.error();
  }
}
