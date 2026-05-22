import { useEffect, useState } from "react";
import { Spinner } from "@/components/Spinner";
import { haptic } from "@/tg/webapp";

/**
 * GHG6 AD2/AD3: универсальный редактор списка фраз — используется и для
 * loser_reasons, и для chukhan_reasons. Поведение идентично, разнятся только
 * данные/API.
 */
export interface ReasonsEditorProps {
  initial: string[];
  isPending: boolean;
  placeholder?: string;
  emptyHint?: string;
  onSave: (list: string[]) => void;
  useCounts?: Record<string, number>;
  onResetCounts?: () => void;
  resetCountsPending?: boolean;
}

export default function ReasonsEditor({
  initial,
  isPending,
  placeholder = "новая фраза…",
  emptyHint = "Пусто — будет использован дефолт из кода.",
  onSave,
  useCounts,
  onResetCounts,
  resetCountsPending = false,
}: ReasonsEditorProps) {
  const [list, setList] = useState<string[]>(initial);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    setList(initial);
  }, [initial]);

  const dirty = JSON.stringify(list) !== JSON.stringify(initial);

  const add = () => {
    const v = draft.trim();
    if (!v) return;
    if (list.includes(v)) {
      haptic("warning");
      return;
    }
    setList([...list, v]);
    setDraft("");
    haptic("selection");
  };

  const remove = (i: number) => {
    haptic("warning");
    setList(list.filter((_, j) => j !== i));
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
          className="flex-1 rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text placeholder:text-tg-hint outline-none border border-transparent focus:border-tg-link"
        />
        <button
          type="button"
          onClick={add}
          disabled={!draft.trim()}
          className="min-h-11 min-w-11 rounded-md bg-tg-link/15 px-2 text-xs text-tg-link disabled:opacity-40"
        >
          + добавить
        </button>
      </div>

      <div className="max-h-72 overflow-y-auto rounded-lg bg-tg-bg/40 divide-y divide-tg-secondary-bg/40">
        {list.length === 0 ? (
          <div className="px-2 py-3 text-xs text-tg-hint text-center">{emptyHint}</div>
        ) : (
          list.map((r, i) => {
            const count = useCounts?.[r] ?? 0;
            return (
              <div key={`${i}:${r}`} className="flex items-center gap-2 px-2 py-1.5">
                <div className="text-[10px] text-tg-hint w-6 tabular-nums">{i + 1}</div>
                <div className="flex-1 text-sm text-tg-text truncate">{r}</div>
                {useCounts !== undefined && (
                  <div
                    className="text-[10px] text-tg-hint tabular-nums shrink-0"
                    title={`Использовано ${count} раз${count === 1 ? "" : "а"}`}
                  >
                    use:{count}
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => remove(i)}
                  className="min-h-9 min-w-9 rounded-md bg-status-busy/15 px-2 text-xs text-status-busy"
                  title="Удалить"
                >
                  ✕
                </button>
              </div>
            );
          })
        )}
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={!dirty || isPending}
          onClick={() => {
            haptic("medium");
            onSave(list);
          }}
          className="flex-1 min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
        >
          {isPending && <Spinner />}
          {isPending
            ? "Сохраняем…"
            : dirty
            ? `💾 Сохранить (${list.length})`
            : `✓ Сохранено (${list.length})`}
        </button>
        {dirty && (
          <button
            type="button"
            onClick={() => {
              haptic("warning");
              setList(initial);
            }}
            className="min-h-11 min-w-11 rounded-md bg-tg-bg/70 px-2 text-xs text-tg-hint"
          >
            ↺
          </button>
        )}
      </div>

      {onResetCounts && (
        <button
          type="button"
          disabled={resetCountsPending}
          onClick={() => {
            haptic("warning");
            if (confirm("Сбросить счётчики использования всех фраз?")) {
              onResetCounts();
            }
          }}
          className="w-full min-h-9 rounded-md bg-tg-bg/70 px-2 text-[11px] text-tg-hint disabled:opacity-50 inline-flex items-center justify-center gap-2"
        >
          {resetCountsPending && <Spinner />}
          🔄 Сбросить счётчики использования
        </button>
      )}
    </div>
  );
}
