import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  adminLoserRollNow,
  fetchLoserHistory,
  fetchLoserReasons,
  updateLoserReasons,
} from "@/api/admin";
import type { User } from "@/types";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import { Spinner } from "@/components/Spinner";
import SubScreen from "../SubScreen";
import ReasonsEditor from "../ReasonsEditor";

interface Props {
  users: User[];
  onBack: () => void;
}

export default function LoserScreen({ users, onBack }: Props) {
  const qc = useQueryClient();

  const reasons = useQuery({
    queryKey: ["admin", "loser-reasons"],
    queryFn: fetchLoserReasons,
  });
  const history = useQuery({
    queryKey: ["admin", "loser-history"],
    queryFn: fetchLoserHistory,
  });

  const rollNow = useMutation({
    mutationFn: adminLoserRollNow,
    onSuccess: (res) => {
      haptic(res.ok ? "success" : "warning");
      qc.invalidateQueries({ queryKey: ["admin", "loser-history"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const saveReasons = useMutation({
    mutationFn: updateLoserReasons,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "loser-reasons"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const userById = Object.fromEntries(users.map((u) => [u.id, u] as const));

  return (
    <SubScreen title="🤡 Лох" subtitle="Force-reroll, история, шаблоны фраз" onBack={onBack}>
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">🎲 Принудительный re-roll</div>
        <div className="text-xs text-tg-hint mb-2">
          Прокручивает выбор лоха прямо сейчас и публикует результат в общий чат.
        </div>
        <button
          type="button"
          disabled={rollNow.isPending}
          onClick={() => {
            haptic("medium");
            if (confirm("Крутануть лоха сейчас?")) rollNow.mutate();
          }}
          className="w-full min-h-11 rounded-lg bg-tg-button py-2.5 text-sm font-medium text-tg-button-text disabled:opacity-50 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
        >
          {rollNow.isPending && <Spinner />}
          {rollNow.isPending ? "Катаем…" : "🎲 Крутануть лоха"}
        </button>
        {rollNow.isError && (
          <div className="mt-2 rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
            ⚠ {String((rollNow.error as Error)?.message ?? rollNow.error)}
          </div>
        )}
        {rollNow.isSuccess && !rollNow.isPending && (
          <div
            className={`mt-2 rounded-md p-2 text-xs ${
              rollNow.data.ok
                ? "bg-status-free/10 text-status-free"
                : "bg-status-busy/10 text-status-busy"
            }`}
          >
            {rollNow.data.ok
              ? "✓ Готово — лох уже в чате."
              : `⚠ ${rollNow.data.error ?? "Не удалось крутануть"}`}
          </div>
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">📜 История лохов</div>
        <div className="text-xs text-tg-hint mb-2">Последние roll'ы.</div>
        {history.isPending ? (
          <ListSkeleton rows={5} />
        ) : (history.data ?? []).length === 0 ? (
          <div className="text-xs text-tg-hint">Пока пусто.</div>
        ) : (
          <div className="divide-y divide-tg-bg/40">
            {(history.data ?? []).map((h) => {
              const u = userById[h.loser_user_id];
              const color = u?.color_hex ?? "#888";
              return (
                <div key={h.id} className="flex items-start gap-2 py-1.5">
                  <div
                    className="w-7 h-7 rounded-full inline-flex items-center justify-center text-white text-xs font-medium shrink-0 mt-0.5"
                    style={{ background: color }}
                  >
                    {(u?.display_name ?? "?")[0]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-tg-text">{u?.display_name ?? `#${h.loser_user_id}`}</div>
                    {h.reason_text && (
                      <div className="text-[11px] text-tg-hint italic">{h.reason_text}</div>
                    )}
                  </div>
                  <div className="text-[10px] text-tg-hint tabular-nums whitespace-nowrap mt-1">
                    {format(new Date(h.rolled_at), "dd.MM HH:mm")}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-base font-semibold mb-1">🤡 Шаблоны фраз</div>
        <div className="text-xs text-tg-hint mb-2">
          Бот выбирает случайную фразу при roll'е лоха. Пустой список → дефолт из кода.
        </div>
        {reasons.isPending || !reasons.data ? (
          <ListSkeleton rows={5} />
        ) : (
          <ReasonsEditor
            initial={reasons.data.reasons}
            isPending={saveReasons.isPending}
            placeholder="например: снова забыл выпить таблетки"
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
