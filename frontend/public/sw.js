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
 *  • сборка (JS/CSS) кладётся в кеш при установке: список файлов читается из
 *    `index.html`. Без этого офлайн-старт после **первого** визита дал бы HTML
 *    без скриптов — пустой экран вместо приложения;
 *  • иконки/манифест попадают в кеш ещё при установке.
 *
 * Обновление: при изменении этого файла браузер ставит новый SW, `activate`
 * чистит кеши прошлых версий. Версию поднимать руками при правке списка SHELL.
 */
const VERSION = "v2";
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
    (async () => {
      const shell = await caches.open(SHELL_CACHE);
      await shell.addAll(SHELL);
      await precacheBuild(shell);
      await self.skipWaiting();
    })(),
  );
});

/**
 * Достаём хешированные `/assets/*.js|css` из сохранённого `index.html` и кладём
 * их в кеш. Имена с хешем, поэтому список не нужно поддерживать руками — при
 * новой сборке HTML изменится, а с ним и список. Ошибка загрузки отдельного
 * файла не отменяет установку: лучше неполный офлайн, чем отсутствие SW.
 */
async function precacheBuild(shell) {
  try {
    const page = await shell.match("/index.html");
    if (!page) return;
    const html = await page.text();
    const paths = new Set();
    for (const [tag] of html.matchAll(/<(?:script|link)\b[^>]*>/gi)) {
      const isScript = /^<script/i.test(tag);
      const isStyle = /rel=["']?stylesheet/i.test(tag);
      if (!isScript && !isStyle) continue;
      const attr = tag.match(/(?:src|href)=["']([^"']+)["']/i);
      if (!attr) continue;
      const url = new URL(attr[1], self.location.origin);
      if (url.origin !== self.location.origin) continue;
      if (url.pathname.startsWith("/assets/")) paths.add(url.pathname);
    }
    const assets = await caches.open(ASSET_CACHE);
    await Promise.all(
      [...paths].map(async (path) => {
        if (await assets.match(path)) return;
        const response = await fetch(path).catch(() => null);
        if (response && response.ok) await assets.put(path, response);
      }),
    );
  } catch {
    // Офлайн-старт без ассетов хуже, но рабочее приложение важнее установки.
  }
}

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

  // Оболочка лежит в SHELL_CACHE, сборка — в ASSET_CACHE. Проверять не тот
  // кеш — значит при офлайне отдавать `Response.error()` для манифеста и
  // иконок, хотя они уже сохранены.
  if (SHELL.includes(url.pathname)) {
    event.respondWith(cacheFirst(request, SHELL_CACHE));
    return;
  }

  if (
    url.pathname.startsWith("/assets/") ||
    /\.(png|ico|svg|webmanifest|woff2?)$/.test(url.pathname)
  ) {
    event.respondWith(cacheFirst(request, ASSET_CACHE));
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

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
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
