import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  clearChukhanReasonUseCounts,
  setChukhanReasonUseCount,
  fetchChukhanHistory,
  fetchChukhanReasons,
  fetchChukhanReasonsRaw,
  fetchChukhanReasonUseCounts,
  fetchWeights,
  forceReroll,
  resetChukhanReasons,
  resetWeight,
  updateChukhanReasons,
  updateWeight,
} from "@/api/admin";
import type { User } from "@/types";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import { Spinner } from "@/components/Spinner";
import SubScreen from "./SubScreen";
import ReasonsEditor from "./ReasonsEditor";

interface Props {
  users: User[];
  onBack: () => void;
}

export default function ChukhanScreen({ users, onBack }: Props) {
  const qc = useQueryClient();

  const weights = useQuery({ queryKey: ["admin", "weights"], queryFn: fetchWeights });
  const reasons = useQuery({ queryKey: ["admin", "chukhan-reasons"], queryFn: fetchChukhanReasons });
  const useCounts = useQuery({
    queryKey: ["admin", "chukhan-reasons-use-counts"],
    queryFn: fetchChukhanReasonUseCounts,
  });
  const history = useQuery({ queryKey: ["admin", "history"], queryFn: fetchChukhanHistory });

  const setW = useMutation({
    mutationFn: ({ tg, w }: { tg: number; w: number }) => updateWeight(tg, w),
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "weights"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });
  const resetW = useMutation({
    mutationFn: (tg: number) => resetWeight(tg),
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "weights"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });
  const reroll = useMutation({
    mutationFn: forceReroll,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "history"] });
      qc.invalidateQueries({ queryKey: ["chukhan", "leaderboard"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });
  const saveReasons = useMutation({
    mutationFn: updateChukhanReasons,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "chukhan-reasons"] });
      qc.invalidateQueries({ queryKey: ["admin", "chukhan-reasons-use-counts"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });
  const resetCounts = useMutation({
    mutationFn: clearChukhanReasonUseCounts,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "chukhan-reasons-use-counts"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });
  const setCount = useMutation({
    mutationFn: ({ phrase, count }: { phrase: string; count: number }) =>
      setChukhanReasonUseCount(phrase, count),
    onSuccess: (res) => {
      haptic("success");
      qc.setQueryData(["admin", "chukhan-reasons-use-counts"], res);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });
  // GHG8 Q5: диагностика «почему 6 старых причин» + сброс к дефолтам из кода.
  const reasonsRaw = useQuery({
    queryKey: ["admin", "chukhan-reasons-raw"],
    queryFn: fetchChukhanReasonsRaw,
  });
  const resetReasons = useMutation({
    mutationFn: resetChukhanReasons,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "chukhan-reasons"] });
      qc.invalidateQueries({ queryKey: ["admin", "chukhan-reasons-raw"] });
      qc.invalidateQueries({ queryKey: ["admin", "chukhan-reasons-use-counts"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const userByTg = Object.fromEntries(users.map((u) => [u.telegram_id, u] as const));
  const userById = Object.fromEntries(users.map((u) => [u.id, u] as const));

  return (
    <SubScreen
      title="💩 Чухан недели"
      subtitle="Веса, ре-ролл, история, шаблоны фраз"
      onBack={onBack}
    >
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">⚖️ Веса</div>
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
          className="w-full rounded-lg bg-tg-button py-2.5 text-sm font-medium text-tg-button-text disabled:opacity-50 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
        >
          {reroll.isPending && <Spinner />}
          {reroll.isPending ? "Катаем…" : "Перевыбрать чухана"}
        </button>
        {reroll.isError && (
          <div className="mt-2 rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
            ⚠ {String((reroll.error as Error)?.message ?? reroll.error)}
          </div>
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">💩 Шаблоны фраз чухана</div>
        <div className="text-xs text-tg-hint mb-2">
          Используются при объявлении чухана недели. Пустой список → дефолт из кода.
        </div>
        {reasons.isPending || !reasons.data ? (
          <ListSkeleton rows={5} />
        ) : (
          <ReasonsEditor
            initial={reasons.data.reasons}
            isPending={saveReasons.isPending}
            placeholder="например: на этой неделе вообще пропал"
            onSave={(list) => saveReasons.mutate(list)}
            useCounts={useCounts.data?.counts}
            onResetCounts={() => resetCounts.mutate()}
            resetCountsPending={resetCounts.isPending}
            onSetCount={(phrase, count) => setCount.mutate({ phrase, count })}
          />
        )}
        {saveReasons.isError && (
          <div className="mt-2 rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
            ⚠ {String((saveReasons.error as Error)?.message ?? saveReasons.error)}
          </div>
        )}

        {/* GHG8 Q5: диагностика + сброс. Чинит «правлю Neon, а в приложении 6
            старых фраз» — показывает что реально в admin_config и даёт залить
            дефолты одной кнопкой (вытесняет кривой/пустой ключ валидным JSON). */}
        {reasonsRaw.data && (
          <div className="mt-3 rounded-md bg-tg-bg/40 p-2 text-[11px] text-tg-hint">
            <div className="font-medium text-tg-text mb-1">🔍 Диагностика</div>
            {reasonsRaw.data.using_default ? (
              <div className="text-status-busy">
                Сейчас активны дефолтные {reasonsRaw.data.default_count} фраз из
                кода
                {reasonsRaw.data.key_present
                  ? !reasonsRaw.data.parse_ok
                    ? ` — в базе под «${reasonsRaw.data.key}» лежит НЕвалидный JSON (${reasonsRaw.data.raw_len} симв.), он игнорируется.`
                    : ` — ключ есть, но не распознан как список строк.`
                  : ` — кастомного списка в базе нет (ключ «${reasonsRaw.data.key}» отсутствует).`}
              </div>
            ) : (
              <div className="text-status-free">
                Активен кастомный список: {reasonsRaw.data.parsed_count} фраз из
                базы. ✓
              </div>
            )}
          </div>
        )}
        <button
          type="button"
          onClick={() => {
            haptic("light");
            void (async () => {
              const ok = await showConfirm(
                "Перезаписать причины чухана дефолтами из кода? Текущий список в базе будет заменён.",
              );
              if (ok) resetReasons.mutate();
            })();
          }}
          disabled={resetReasons.isPending}
          className="mt-2 w-full rounded-lg border border-tg-hint/30 py-2 text-xs text-tg-text active:scale-[0.99] disabled:opacity-50"
        >
          {resetReasons.isPending ? "Сбрасываю…" : "↩ Сбросить к дефолтам из кода"}
        </button>
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">📜 История чуханов</div>
        <div className="text-xs text-tg-hint mb-2">Последние записи по неделям.</div>
        {history.isPending ? (
          <ListSkeleton rows={5} />
        ) : (history.data ?? []).length === 0 ? (
          <div className="text-xs text-tg-hint">Пока пусто.</div>
        ) : (
          <div className="divide-y divide-tg-bg/40">
            {(history.data ?? []).map((h) => {
              const u = userById[h.user_id];
              const color = u?.color_hex ?? "#888";
              return (
                <div key={h.id} className="flex items-center gap-2 py-1.5">
                  <div
                    className="w-7 h-7 rounded-full inline-flex items-center justify-center text-white text-xs font-medium shrink-0"
                    style={{ background: color }}
                  >
                    {(u?.display_name ?? "?")[0]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-tg-text truncate">
                      {u?.display_name ?? `#${h.user_id}`}
                    </div>
                  </div>
                  <div className="text-[10px] text-tg-hint tabular-nums whitespace-nowrap">
                    {format(new Date(h.week_start), "dd.MM.yyyy")}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </SubScreen>
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
