import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { fetchLoserStats, rollLoser } from "@/api/meetings";
import { fetchUsers } from "@/api/availability";
import { useUI } from "@/store/ui";
import { haptic } from "@/tg/webapp";
import { ApiError } from "@/api/client";
import BottomSheet from "./BottomSheet";

function fmtRemaining(seconds: number): string {
  if (seconds <= 0) return "готово";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}ч ${m}мин` : `${m}мин`;
}

export default function LoserSheet() {
  const close = () => useUI.getState().setShowLoserSheet(false);
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [spinName, setSpinName] = useState<string | null>(null);
  const spinTimer = useRef<number | null>(null);

  const usersQ = useQuery({ queryKey: ["users"], queryFn: fetchUsers, staleTime: 60_000 });
  const statsQ = useQuery({ queryKey: ["loser-stats"], queryFn: fetchLoserStats });

  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => () => {
    if (spinTimer.current != null) {
      window.clearInterval(spinTimer.current);
    }
  }, []);

  const usersById = new Map((usersQ.data ?? []).map((u) => [u.id, u]));
  const baseRemaining = statsQ.data?.cooldown_remaining_seconds ?? 0;
  const fetchedAt = statsQ.dataUpdatedAt;
  const elapsedSinceFetch = (Date.now() - fetchedAt) / 1000;
  const remaining = Math.max(0, Math.ceil(baseRemaining - elapsedSinceFetch));
  void tick;

  const stopSpin = () => {
    if (spinTimer.current != null) {
      window.clearInterval(spinTimer.current);
      spinTimer.current = null;
    }
    setSpinName(null);
  };

  const mut = useMutation({
    mutationFn: async () => {
      const allUsers = usersQ.data ?? [];
      if (allUsers.length > 0) {
        let i = 0;
        spinTimer.current = window.setInterval(() => {
          const u = allUsers[i % allUsers.length];
          setSpinName(u.display_name);
          haptic("light");
          i += 1;
        }, 90);
      }
      const result = await rollLoser();
      // дать рулетке покрутиться минимум ~1.1s, даже если API быстрее
      await new Promise((r) => setTimeout(r, 1100));
      return result;
    },
    onSuccess: () => {
      stopSpin();
      haptic("heavy");
      qc.invalidateQueries({ queryKey: ["loser-stats"] });
      qc.invalidateQueries({ queryKey: ["loser", "stats"] });
      setError(null);
    },
    onError: (e) => {
      stopSpin();
      if (e instanceof ApiError && e.detail.startsWith("cooldown:")) {
        const sec = Number(e.detail.split(":")[1] ?? 0);
        setError(`Подожди ещё ${fmtRemaining(sec)}.`);
      } else {
        setError(e instanceof Error ? e.message : "Ошибка");
      }
    },
  });

  const counts = statsQ.data?.counts ?? {};
  const ranked = Object.entries(counts)
    .map(([id, c]) => ({ id: Number(id), c }))
    .sort((a, b) => b.c - a.c);

  const last = statsQ.data?.last;
  const lastUser = last ? usersById.get(last.loser_user_id) : null;
  const isSpinning = mut.isPending;

  return (
    <BottomSheet title="🎲 Лох дня" onClose={close}>
      <button
        type="button"
        onClick={() => mut.mutate()}
        disabled={mut.isPending || remaining > 0}
        className="w-full rounded-xl bg-tg-button py-4 text-base font-bold text-tg-button-text disabled:opacity-50"
      >
        {remaining > 0
          ? `Кулдаун: ${fmtRemaining(remaining)}`
          : mut.isPending
            ? "Крутим…"
            : "Крутить рулетку"}
      </button>

      {(isSpinning || (mut.isSuccess && spinName == null)) && (
        <div className="mt-4 rounded-xl bg-tg-secondary-bg p-4 text-center overflow-hidden">
          <div className="text-xs text-tg-hint mb-1">
            {isSpinning ? "Барабан крутится…" : "🥁 Победитель"}
          </div>
          <motion.div
            key={spinName ?? "result"}
            initial={{ y: isSpinning ? 12 : 0, opacity: isSpinning ? 0 : 1, scale: 1 }}
            animate={{ y: 0, opacity: 1, scale: isSpinning ? 1 : 1.15 }}
            transition={{ type: "spring", damping: 20, stiffness: 320 }}
            className="text-2xl font-bold"
          >
            {spinName ??
              (mut.data
                ? (usersById.get(mut.data.roll.loser_user_id)?.display_name ?? "???")
                : "…")}
          </motion.div>
          {!isSpinning && mut.data?.roll.reason_text && (
            <div className="mt-1 text-sm text-tg-hint">
              «{mut.data.roll.reason_text}»
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="mt-2 rounded-lg bg-status-busy/15 p-2 text-center text-sm text-status-busy">
          {error}
        </div>
      )}

      {!isSpinning && !mut.isSuccess && last && (
        <div className="mt-4 rounded-xl bg-tg-secondary-bg p-3">
          <div className="text-xs text-tg-hint">Последний раз</div>
          <div className="font-medium">{lastUser?.display_name ?? "???"}</div>
          {last.reason_text && (
            <div className="text-sm text-tg-hint">«{last.reason_text}»</div>
          )}
        </div>
      )}

      <div className="mt-4">
        <div className="mb-2 text-xs text-tg-hint">Зал позора</div>
        <ul className="space-y-1">
          {ranked.length === 0 && (
            <li className="text-sm text-tg-hint">Пока никого. Будь первым.</li>
          )}
          {ranked.map(({ id, c }, i) => {
            const u = usersById.get(id);
            return (
              <li
                key={id}
                className="flex items-center justify-between rounded-lg bg-tg-secondary-bg/50 px-3 py-2"
              >
                <span>
                  {i + 1}. {u?.display_name ?? `#${id}`}
                </span>
                <span className="font-mono text-sm">×{c}</span>
              </li>
            );
          })}
        </ul>
      </div>

      <button
        type="button"
        onClick={close}
        className="mt-4 w-full rounded-xl bg-tg-secondary-bg py-3 font-medium"
      >
        Закрыть
      </button>
    </BottomSheet>
  );
}
