import type { PhrasePool } from "@/api/admin";
import ReasonsEditor, { type ReasonsEditorProps } from "./ReasonsEditor";
import { usePhraseMeta } from "./usePhraseMeta";

/**
 * GHG8 J.2: обёртка «именованный пул → редактор фраз».
 *
 * Единственное, что она делает — подтягивает метаданные пула (источник +
 * скрытие) и прокидывает их в `ReasonsEditor`. Так экраны не тащат по хуку на
 * каждый пул, а редактор остаётся переиспользуемым (им же пользуются места, где
 * метаданные не нужны и передавать `pool` нечем).
 */
export type PhrasePoolEditorProps = Omit<
  ReasonsEditorProps,
  "meta" | "onSetMeta" | "onBulkMeta"
> & {
  pool: PhrasePool;
};

export default function PhrasePoolEditor({ pool, ...rest }: PhrasePoolEditorProps) {
  const { meta, onSetMeta, onBulkMeta } = usePhraseMeta(pool);
  return (
    <ReasonsEditor {...rest} meta={meta} onSetMeta={onSetMeta} onBulkMeta={onBulkMeta} />
  );
}
