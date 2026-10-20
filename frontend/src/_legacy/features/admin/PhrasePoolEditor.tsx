import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchPhrasesSourceMode,
  updatePhrasesSourceMode,
  type PhrasesSourceMode,
  type PhrasePool,
} from "@/api/admin";
import { haptic } from "@/tg/webapp";
import ReasonsEditor, { type ReasonsEditorProps } from "./ReasonsEditor";
import { usePhraseMeta } from "./usePhraseMeta";

/**
 * GHG8 J.2: обёртка «именованный пул → редактор фраз».
 *
 * Единственное, что она делает — подтягивает метаданные пула (источник +
 * скрытие), прокидывает их в `ReasonsEditor` и показывает ГЛОБАЛЬНЫЙ свитчер
 * источника фраз (Э19). Так экраны не тащат по хуку на каждый пул, а редактор
 * остаётся переиспользуемым.
 */
export type PhrasePoolEditorProps = Omit<
  ReasonsEditorProps,
  "meta" | "onSetMeta" | "onBulkMeta"
> & {
  pool: PhrasePool;
};

const SOURCE_MODE_LABELS: Record<PhrasesSourceMode, string> = {
  manual: "Только ручные",
  ai: "Только ИИ",
  both: "Оба (по умолчанию)",
};

/**
 * Э19: глобальный свитчер «ручные / ИИ / оба».
 *
 * Один на весь проект (значение живёт в `admin_config`, ключ
 * `phrases.source_mode`), поэтому стоит в каждом редакторе пула и влияет на ВСЕ
 * пулы сразу — именно этого оператор не находил раньше: как переключаться между
 * ручными фразами и ИИ-генерацией.
 */
function SourceModeSwitch() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "phrases-source-mode"],
    queryFn: fetchPhrasesSourceMode,
    staleTime: 10_000,
  });
  const mut = useMutation({
    mutationFn: (mode: PhrasesSourceMode) => updatePhrasesSourceMode(mode),
    onSuccess: () => {
      haptic("success");
      void qc.invalidateQueries({ queryKey: ["admin", "phrases-source-mode"] });
    },
    onError: () => haptic("error"),
  });

  const mode = q.data?.mode ?? "both";
  const options: PhrasesSourceMode[] = q.data?.modes ?? ["manual", "ai", "both"];

  return (
    <div className="mb-2 rounded-lg bg-tg-bg/40 p-2">
      <div className="text-[11px] text-tg-hint">
        Что бот шлёт из пулов фраз — глобально для всех пулов сразу:
      </div>
      <div className="mt-1 flex flex-wrap gap-1">
        {options.map((opt) => (
          <button
            key={opt}
            type="button"
            disabled={mut.isPending}
            onClick={() => {
              haptic("selection");
              mut.mutate(opt);
            }}
            className={[
              "rounded-lg px-2 py-1 text-xs font-medium active:scale-[0.98] disabled:opacity-60",
              mode === opt
                ? "bg-tg-button text-tg-button-text"
                : "bg-tg-secondary-bg/70 text-tg-text",
            ].join(" ")}
          >
            {SOURCE_MODE_LABELS[opt] ?? opt}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function PhrasePoolEditor({ pool, ...rest }: PhrasePoolEditorProps) {
  const { meta, onSetMeta, onBulkMeta } = usePhraseMeta(pool);
  return (
    <div>
      <SourceModeSwitch />
      <ReasonsEditor {...rest} meta={meta} onSetMeta={onSetMeta} onBulkMeta={onBulkMeta} />
    </div>
  );
}
