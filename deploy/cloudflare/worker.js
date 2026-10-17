// Тонкий Worker поверх контейнера: вся логика остаётся в FastAPI.
//
// Зачем прокси, а не «контейнер сам наружу»: Cloudflare Containers не имеют
// публичного адреса. Worker — единственная точка входа, он же даёт HTTPS,
// домен и логи запросов, а контейнер слушает свой внутренний порт.
import { Container, getContainer } from "@cloudflare/containers";

export class BackendContainer extends Container {
  // Uvicorn в образе слушает $PORT (7860, см. backend/Dockerfile).
  defaultPort = 7860;
  // Сон после простоя: платим за запущенный контейнер, а не за простой.
  // Первый запрос после сна поднимает его заново (холодный старт ~10–20 с).
  sleepAfter = "15m";
  // Проверка живости: контейнер считается готовым, когда отвечает /healthz.
  enableInternet = true;
}

export default {
  async fetch(request, env) {
    // Один экземпляр на всё приложение: in-process планировщик (APScheduler)
    // и кэш настроек не рассчитаны на несколько реплик. Масштабировать нужно
    // вместе с выносом планировщика в отдельный воркер.
    return getContainer(env.BACKEND).fetch(request);
  },
};
