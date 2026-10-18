// Cron-Worker, который не даёт бесплатному Hugging Face Space уснуть.
//
// Бесплатный Space уходит в сон после 48 часов без запросов, и вместе с ним
// замолкает бот: вебхук Telegram бьётся в спящий контейнер и ждёт холодного
// старта. Пинг раз в полчаса сбрасывает таймер сна, а заодно проверяет, что
// хост жив: результат видно в логах воркера (Workers → Logs).
//
// Стоит ноль: Cron Triggers входят в бесплатный план, а сам запрос — один
// лёгкий GET на /healthz.
export default {
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(ping(env.TARGET_URL));
  },

  async fetch(request, env) {
    // Нужен для ручной проверки из браузера: /?url=... или просто / .
    const url = new URL(request.url);
    const target = url.searchParams.get("url") || env.TARGET_URL;
    const result = await ping(target);
    return Response.json(result, { status: result.ok ? 200 : 503 });
  },
};

async function ping(target) {
  if (!target) return { ok: false, error: "TARGET_URL не задан" };
  const started = Date.now();
  try {
    const response = await fetch(target, {
      // Кэш нам не нужен: цель — сам факт входящего запроса.
      cf: { cacheTtl: 0 },
      headers: { "user-agent": "semitask-keepalive" },
    });
    const body = await response.text();
    return {
      ok: response.ok,
      status: response.status,
      ms: Date.now() - started,
      body: body.slice(0, 80),
      at: new Date().toISOString(),
    };
  } catch (error) {
    return {
      ok: false,
      error: String(error && error.message ? error.message : error),
      ms: Date.now() - started,
      at: new Date().toISOString(),
    };
  }
}
