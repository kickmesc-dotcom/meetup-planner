/**
 * RUM: реальные метрики Core Web Vitals от устройства человека (этап 5).
 *
 * Зачем. Lighthouse меряет наш стенд в CI, но не телефон официанта в зале с
 * чужим Wi-Fi. Здесь браузер сам присылает LCP/INP/CLS/FCP/TTFB, а мы видим
 * p75 по устройствам — то, что ощущает человек, а не синтетика.
 *
 * Почему без идентификаторов. Метрика привязана к устройству (mobile/desktop),
 * платформе Telegram и пути экрана, но не к человеку, организации или сессии.
 * Этого достаточно, чтобы увидеть «на Android лента тормозит», и недостаточно,
 * чтобы следить за конкретным сотрудником.
 *
 * Почему `reportAllChanges: false`. Для CLS и INP важна финальная величина:
 * промежуточные значения завышают картину (страница ещё грузится). Колбэк
 * web-vitals вызывается на скрытии страницы, то есть когда число устойчиво.
 */
import { onCLS, onFCP, onINP, onLCP, onTTFB, type Metric } from "web-vitals";
import { getApiBase } from "@/api/client";
import { cleanPath } from "@/lib/telemetry";
import { deviceKind, platformName, type DeviceKind } from "@/lib/device";

export { deviceKind, platformName };
export type { DeviceKind };

/** Тело отчёта. Вынесено отдельно, чтобы тест проверял его без сети. */
export function buildVitalBody(metric: Metric, device: DeviceKind = deviceKind()) {
  return {
    name: metric.name,
    value: Math.round(metric.value * 1000) / 1000,
    rating: metric.rating,
    device,
    platform: platformName(),
    path: typeof window === "undefined" ? "" : cleanPath(window.location.pathname),
    build: String((import.meta.env.VITE_BUILD_ID as string | undefined) ?? "").slice(0, 40),
  };
}

/** Отправить одну метрику. Ошибка сети — молча: RUM не должен мешать работе. */
export function sendVital(metric: Metric, device: DeviceKind = deviceKind()): boolean {
  if (typeof window === "undefined" || typeof fetch !== "function") return false;
  try {
    void fetch(`${getApiBase()}/api/telemetry/vitals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildVitalBody(metric, device)),
      // Метрика часто финализируется при уходе со страницы: обычный запрос
      // браузер отменил бы ровно в этот момент.
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    return false;
  }
  return true;
}

let installed = false;

/** Подписаться на метрики. Повторный вызов из React StrictMode безопасен. */
export function installVitals(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  const options = { reportAllChanges: false } as const;
  onLCP(sendVital, options);
  onINP(sendVital, options);
  onCLS(sendVital, options);
  onFCP(sendVital, options);
  onTTFB(sendVital, options);
}
