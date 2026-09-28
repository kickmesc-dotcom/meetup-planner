import { useQuery } from "@tanstack/react-query";
import { fetchMyGame } from "@/api/game";

/**
 * GHG10 Э8: какие ранговые функции доступны текущему пользователю.
 *
 * Источник — `unlocked` из `/me/game` (сервер сам складывает всё, что открыто
 * на уровне). Хук нужен, чтобы UI прятал/замораживал закрытые функции ДО
 * запроса, а не показывал 403.
 *
 * Важно: при выключенной игре (`enabled=false`) гейта нет — `can()` возвращает
 * true, как и сервер (`gates.check_feature`).
 */
const GAME_QUERY_KEY = ["game", "me"] as const;

export function useGameFeatures() {
  const q = useQuery({ queryKey: GAME_QUERY_KEY, queryFn: fetchMyGame });
  const data = q.data;
  const enabled = data?.enabled === true;
  const unlocked = new Set((data?.unlocked ?? []).map((f) => f.code));

  return {
    loading: q.isPending,
    enabled,
    /** Доступна ли фича. Коды — из `config.LEVEL_UNLOCKS`. */
    can: (feature: string) => !enabled || unlocked.has(feature),
  };
}
