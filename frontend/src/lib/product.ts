import { api } from "@/api/client";
import { deviceKind } from "@/lib/device";

/**
 * Счётчик «фича + действие».
 *
 * Зачем. Телеметрия ловит ошибки, но не отвечает на вопрос «этим пользуются?».
 * После десяти сделанных фич без такого ответа нельзя ни оценить работу, ни
 * выбрать, что развивать. Здесь только пара «что открыли / что сделали» и тип
 * устройства — ни имени, ни текста, ни адреса.
 *
 * Почему не в тестах и не в dev: счётчик не должен ни шуметь в локальной
 * разработке, ни превращаться в лишние запросы в прогонах.
 *
 * Почему дедупликация: экран может перерисоваться несколько раз за секунду
 * (смена фильтра, ответ запроса). Пять секунд на пару «фича:действие» — это
 * «сколько раз человек воспользовался», а не «сколько раз React отрендерил».
 *
 * Ошибка отправки молчит намеренно: аналитика не стоит ни одного лишнего
 * алерта человеку, который просто работает.
 */
const DEDUPE_MS = 5_000;
const lastSent = new Map<string, number>();

export function trackFeature(feature: string, action: string, screen?: string): void {
  if (!import.meta.env.PROD) return;
  const key = `${feature}:${action}`;
  const now = Date.now();
  if (now - (lastSent.get(key) ?? 0) < DEDUPE_MS) return;
  lastSent.set(key, now);
  try {
    void api<void>("/api/telemetry/product", {
      method: "POST",
      body: JSON.stringify({
        feature,
        action,
        screen: screen ?? null,
        device: deviceKind(),
      }),
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    // Нет storage/сети — счётчик не важнее работы экрана.
  }
}
