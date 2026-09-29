import { useQuery } from "@tanstack/react-query";
import { fetchMeta, type ServerMeta } from "@/api/meta";

/**
 * GHG10-ops: какие игровые ручки реально есть на живом бэкенде.
 *
 * Контекст: фронт (Cloudflare) и бэкенд (Amvera) деплоятся независимо, и фронт
 * регулярно уезжает вперёд. Тогда кнопка, обещающая функцию, на живом сервере
 * отвечает 404. Здесь мы спрашиваем у бэкенда его тир-лист и прячем обещания.
 *
 * Приоритет — не спрятать работающую функцию:
 * - пока ответ не пришёл или запрос упал, считаем, что функция ЕСТЬ
 *   (оптимистично, как было до этого хука);
 * - прячем только когда сервер явно ответил своим списком и функции там нет.
 * Кэш бессрочный: список меняется только вместе с пересборкой бэкенда, а
 * лишний запрос к `/api/meta` тянет за собой запрос к базе.
 */
const META_QUERY_KEY = ["meta"] as const;

export const META_QUERY_OPTIONS = {
  queryKey: META_QUERY_KEY,
  queryFn: fetchMeta,
  staleTime: Infinity,
  retry: false,
} as const;

export function useServerCapabilities() {
  const q = useQuery<ServerMeta>(META_QUERY_OPTIONS);
  const features = q.data?.features;

  return {
    loading: q.isPending,
    /** Есть ли ручка на живом бэкенде. Неизвестность трактуем как «есть». */
    has: (feature: string) => (features ? features.includes(feature) : true),
  };
}
