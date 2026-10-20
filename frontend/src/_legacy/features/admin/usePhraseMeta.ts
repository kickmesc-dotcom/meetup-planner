import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  bulkPhraseMeta,
  fetchPhraseMeta,
  updatePhraseMeta,
  type PhraseMetaItem,
  type PhrasePool,
  type PhraseSource,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";

/**
 * GHG8 J.1/J.2: метаданные пула фраз (источник + мягкое скрытие).
 *
 * Возвращает `meta` — словарь «текст фразы → {source, hidden}» для передачи в
 * `ReasonsEditor`, плюс колбэки точечного и массового изменения флагов.
 */
export function usePhraseMeta(pool: PhrasePool) {
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ["admin", "phrases-meta", pool],
    queryFn: () => fetchPhraseMeta(pool),
    staleTime: 10_000,
  });

  const meta: Record<string, PhraseMetaItem> = {};
  for (const it of q.data?.items ?? []) meta[it.phrase] = it;

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["admin", "phrases-meta", pool] });

  type Patch = { source?: PhraseSource; hidden?: boolean };

  const setMut = useMutation({
    mutationFn: ({ phrase, patch }: { phrase: string; patch: Patch }) =>
      updatePhraseMeta(pool, phrase, patch),
    onSuccess: () => {
      haptic("success");
      void invalidate();
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const bulkMut = useMutation({
    mutationFn: ({ phrases, patch }: { phrases: string[]; patch: Patch }) =>
      bulkPhraseMeta(pool, phrases, patch),
    onSuccess: () => {
      haptic("success");
      void invalidate();
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  return {
    meta,
    isLoading: q.isPending,
    onSetMeta: (phrase: string, patch: Patch) => setMut.mutate({ phrase, patch }),
    onBulkMeta: (phrases: string[], patch: Patch) =>
      bulkMut.mutate({ phrases, patch }),
  };
}
