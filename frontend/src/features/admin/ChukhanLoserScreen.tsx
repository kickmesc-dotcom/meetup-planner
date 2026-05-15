import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchLoserReasons,
  fetchWeights,
  forceReroll,
  resetWeight,
  updateLoserReasons,
  updateWeight,
} from "@/api/admin";
import type { User } from "@/types";
import { haptic } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";

interface Props {
  users: User[];
  onBack: () => void;
}

export default function ChukhanLoserScreen({ users, onBack }: Props) {
  const qc = useQueryClient();

  const weights = useQuery({ queryKey: ["admin", "weights"], queryFn: fetchWeights });
  const reasons = useQuery({ queryKey: ["admin", "loser-reasons"], queryFn: fetchLoserReasons });

  const setW = useMutation({
    mutationFn: ({ tg, w }: { tg: number; w: number }) => updateWeight(tg, w),
    onSuccess: () => {
      haptic("light");
      qc.invalidateQueries({ queryKey: ["admin", "weights"] });
    },
    onError: () => haptic("error"),
  });
  const resetW = useMutation({
    mutationFn: (tg: number) => resetWeight(tg),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "weights"] }),
    onError: () => haptic("error"),
  });
  const reroll = useMutation({
    mutationFn: forceReroll,
    onSuccess: () => {
      haptic("medium");
      qc.invalidateQueries({ queryKey: ["admin", "history"] });
      qc.invalidateQueries({ queryKey: ["chukhan", "leaderboard"] });
    },
    onError: () => haptic("error"),
  });
  const saveReasons = useMutation({
    mutationFn: updateLoserReasons,
    onSuccess: () => {
      haptic("light");
      qc.invalidateQueries({ queryKey: ["admin", "loser-reasons"] });
    },
    onError: () => haptic("error"),
  });

  const userByTg = Object.fromEntries(users.map((u) => [u.telegram_id, u] as const));

  return (
    <SubScreen
      title="💩 Чухан / 🤡 Лох"
      subtitle="Веса, перевыбор, кастомные фразы"
      onBack={onBack}
    >
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">⚖️ Веса чухана</div>
        <div className="text-xs text-tg-hint mb-2">
          Чем выше вес — тем чаще выпадает. База 1.0. Обнуляй, чтобы вернуть env.
        </div>
        {weights.isPending ? (
          <ListSkeleton rows={6} />
        ) : (
          <div className="space-y-2">
            {(weights.data ?? []).map((w) => (
              <WeightRow
                key={w.telegram_id}
                tg={w.telegram_id}
                name={w.display_name}
                color={userByTg[w.telegram_id]?.color_hex ?? "#888"}
                value={w.weight}
                onSet={(v) => setW.mutate({ tg: w.telegram_id, w: v })}
                onReset={() => resetW.mutate(w.telegram_id)}
              />
            ))}
          </div>
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">🎲 Принудительный re-roll</div>
        <div className="text-xs text-tg-hint mb-2">
          Удаляет запись чухана текущей недели и публикует нового в общий чат.
        </div>
        <button
          type="button"
          disabled={reroll.isPending}
          onClick={() => {
            haptic("medium");
            if (confirm("Перевыбрать чухана недели?")) reroll.mutate();
          }}
          className="w-full rounded-lg bg-tg-button py-2.5 text-sm font-medium text-tg-button-text disabled:opacity-50 active:scale-[0.98] transition-transform"
        >
          {reroll.isPending ? "Катаем…" : "Перевыбрать чухана"}
        </button>
        {reroll.isError && (
          <div className="mt-2 rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
            ⚠ {String((reroll.error as Error)?.message ?? reroll.error)}
          </div>
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">🤡 Фразы лоха</div>
        <div className="text-xs text-tg-hint mb-2">
          Бот выбирает случайную фразу при roll'е лоха. Пустой список → дефолт из кода.
        </div>
        {reasons.isPending || !reasons.data ? (
          <ListSkeleton rows={5} />
        ) : (
          <LoserReasonsEditor
            initial={reasons.data.reasons}
            isPending={saveReasons.isPending}
            onSave={(list) => saveReasons.mutate(list)}
          />
        )}
        {saveReasons.isError && (
          <div className="mt-2 rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
            ⚠ {String((saveReasons.error as Error)?.message ?? saveReasons.error)}
          </div>
        )}
      </section>
    </SubScreen>
  );
}

function LoserReasonsEditor({
  initial,
  isPending,
  onSave,
}: {
  initial: string[];
  isPending: boolean;
  onSave: (list: string[]) => void;
}) {
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
          placeholder="например: снова забыл выпить таблетки"
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
          <div className="px-2 py-3 text-xs text-tg-hint text-center">
            Пусто — будет использован дефолт из кода.
          </div>
        ) : (
          list.map((r, i) => (
            <div key={`${i}:${r}`} className="flex items-center gap-2 px-2 py-1.5">
              <div className="text-[10px] text-tg-hint w-6 tabular-nums">{i + 1}</div>
              <div className="flex-1 text-sm text-tg-text truncate">{r}</div>
              <button
                type="button"
                onClick={() => remove(i)}
                className="min-h-9 min-w-9 rounded-md bg-status-busy/15 px-2 text-xs text-status-busy"
                title="Удалить"
              >
                ✕
              </button>
            </div>
          ))
        )}
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={!dirty || isPending}
          onClick={() => onSave(list)}
          className="flex-1 min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform"
        >
          {isPending ? "Сохраняем…" : dirty ? `💾 Сохранить (${list.length})` : `✓ Сохранено (${list.length})`}
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
    </div>
  );
}

function WeightRow({
  tg,
  name,
  color,
  value,
  onSet,
  onReset,
}: {
  tg: number;
  name: string;
  color: string;
  value: number;
  onSet: (v: number) => void;
  onReset: () => void;
}) {
  const [draft, setDraft] = useState(value.toFixed(2));
  useEffect(() => {
    setDraft(value.toFixed(2));
  }, [value]);
  const dirty = parseFloat(draft) !== value;

  return (
    <div className="flex items-center gap-2">
      <div
        className="w-7 h-7 rounded-full inline-flex items-center justify-center text-white text-xs font-medium shrink-0"
        style={{ background: color }}
      >
        {name[0]}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm truncate text-tg-text">{name}</div>
        <div className="text-[10px] text-tg-hint">tg={tg}</div>
      </div>
      <input
        type="number"
        step={0.1}
        min={0}
        max={10}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        className="w-16 rounded-md bg-tg-bg/70 px-2 py-1 text-sm text-tg-text text-right tabular-nums outline-none border border-transparent focus:border-tg-link"
      />
      <button
        type="button"
        disabled={!dirty}
        onClick={() => {
          const v = parseFloat(draft);
          if (!Number.isNaN(v) && v >= 0) onSet(v);
        }}
        className="min-h-11 min-w-11 rounded-md bg-tg-link/15 px-2 text-xs text-tg-link disabled:opacity-40"
      >
        OK
      </button>
      <button
        type="button"
        onClick={onReset}
        className="min-h-11 min-w-11 rounded-md bg-tg-bg/70 px-2 text-base text-tg-hint"
        title="Сбросить к значению из env"
      >
        ↺
      </button>
    </div>
  );
}
