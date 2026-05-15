import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import type { AvailabilityRange, Status } from "@/types";
import { deleteRange, fetchRanges, patchRange } from "@/api/availability";
import { useUI } from "@/store/ui";
import { haptic } from "@/tg/webapp";
import { format } from "date-fns";

interface Props {
  rangeId: number | "new";
  windowStart: Date;
  windowEnd: Date;
  meId: number;
}

export default function RangeEditorSheet({ rangeId, windowStart, windowEnd, meId }: Props) {
  const setEditing = useUI((s) => s.setEditingRangeId);
  const qc = useQueryClient();
  const [range, setRange] = useState<AvailabilityRange | null>(null);

  useEffect(() => {
    if (rangeId === "new" || rangeId === null) return;
    fetchRanges(windowStart, windowEnd).then((rows) => {
      const r = rows.find((x) => x.id === rangeId) ?? null;
      setRange(r);
    });
  }, [rangeId, windowStart, windowEnd]);

  const patchMut = useMutation({
    mutationFn: (body: Partial<AvailabilityRange>) =>
      patchRange(rangeId as number, body as never),
    onMutate: async (body) => {
      // Оптимистично подменяем поля в кэше ranges, чтобы пилюля перекрашивалась
      // сразу. На ошибке откатываем — пилюля вернётся в старое состояние.
      await qc.cancelQueries({ queryKey: ["ranges"] });
      const snapshot = qc.getQueriesData<AvailabilityRange[]>({ queryKey: ["ranges"] });
      qc.setQueriesData<AvailabilityRange[] | undefined>({ queryKey: ["ranges"] }, (old) => {
        if (!old) return old;
        return old.map((r) => (r.id === rangeId ? { ...r, ...body } : r));
      });
      return { snapshot };
    },
    onSuccess: () => haptic("light"),
    onError: (_e, _v, ctx) => {
      haptic("error");
      if (ctx?.snapshot) {
        for (const [key, data] of ctx.snapshot) qc.setQueryData(key, data);
      }
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["ranges"] }),
  });

  const deleteMut = useMutation({
    mutationFn: () => deleteRange(rangeId as number),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ["ranges"] });
      const snapshot = qc.getQueriesData<AvailabilityRange[]>({ queryKey: ["ranges"] });
      qc.setQueriesData<AvailabilityRange[] | undefined>({ queryKey: ["ranges"] }, (old) => {
        if (!old) return old;
        return old.filter((r) => r.id !== rangeId);
      });
      return { snapshot };
    },
    onSuccess: () => {
      haptic("medium");
      setEditing(null);
    },
    onError: (_e, _v, ctx) => {
      haptic("error");
      if (ctx?.snapshot) {
        for (const [key, data] of ctx.snapshot) qc.setQueryData(key, data);
      }
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["ranges"] }),
  });

  if (rangeId === null) return null;

  const isOwn = range?.user_id === meId;

  return (
    <AnimatePresence>
      <motion.div
        key="backdrop"
        className="fixed inset-0 bg-black/40 z-40"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={() => setEditing(null)}
      />
      <motion.div
        key="sheet"
        className="fixed inset-x-0 bottom-0 z-50 rounded-t-2xl bg-tg-bg p-4 pb-8 shadow-xl"
        initial={{ y: "100%" }}
        animate={{ y: 0 }}
        exit={{ y: "100%" }}
        transition={{ type: "spring", damping: 30, stiffness: 320 }}
      >
        <div className="mx-auto mb-3 h-1.5 w-10 rounded-full bg-tg-hint/40" />

        {!range && <div className="text-tg-hint">Загрузка…</div>}

        {range && (
          <>
            <div className="text-sm text-tg-hint mb-1">
              {format(new Date(range.starts_at), "d MMM HH:mm")} →{" "}
              {format(new Date(range.ends_at), "d MMM HH:mm")}
            </div>

            <StatusPicker
              value={range.status}
              disabled={!isOwn}
              onChange={(s) => {
                haptic("selection");
                setRange({ ...range, status: s });
                patchMut.mutate({ status: s });
              }}
            />

            <ConfidencePicker
              value={range.confidence}
              disabled={!isOwn}
              onChange={(c) => {
                haptic("selection");
                setRange({ ...range, confidence: c });
                patchMut.mutate({ confidence: c });
              }}
            />

            {isOwn && (
              <button
                onClick={() => {
                  haptic("warning");
                  deleteMut.mutate();
                }}
                className="mt-4 w-full rounded-xl bg-status-busy/15 text-status-busy py-3 font-medium"
              >
                Удалить
              </button>
            )}

            <button
              onClick={() => {
                haptic("light");
                setEditing(null);
              }}
              className="mt-2 w-full rounded-xl bg-tg-button text-tg-button-text py-3 font-medium"
            >
              Готово
            </button>
          </>
        )}
      </motion.div>
    </AnimatePresence>
  );
}

const STATUSES: { value: Status; label: string; color: string }[] = [
  { value: 1, label: "Свободен", color: "bg-status-free" },
  { value: 2, label: "Может", color: "bg-status-maybe" },
  { value: 3, label: "Занят", color: "bg-status-busy" },
];

function StatusPicker({
  value,
  onChange,
  disabled,
}: {
  value: Status;
  onChange: (s: Status) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex gap-2 my-3">
      {STATUSES.map((s) => (
        <button
          key={s.value}
          type="button"
          disabled={disabled}
          onClick={() => onChange(s.value)}
          className={[
            "flex-1 py-3 rounded-xl text-white font-medium transition-opacity",
            s.color,
            value === s.value ? "opacity-100" : "opacity-40",
          ].join(" ")}
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}

const CONFIDENCE_LABELS: Record<number, string> = {
  1: "Точно да",
  2: "Скорее да",
  3: "Под вопросом",
  4: "Скорее нет",
  5: "Точно нет",
};

function ConfidencePicker({
  value,
  onChange,
  disabled,
}: {
  value: number;
  onChange: (c: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="my-3">
      <div className="text-xs text-tg-hint mb-1">Уверенность</div>
      <div className="flex gap-1">
        {[1, 2, 3, 4, 5].map((c) => (
          <button
            key={c}
            type="button"
            disabled={disabled}
            onClick={() => onChange(c)}
            className={[
              "flex-1 py-2 rounded-lg text-xs",
              value === c ? "bg-tg-button text-tg-button-text" : "bg-tg-secondary-bg",
            ].join(" ")}
          >
            {CONFIDENCE_LABELS[c]}
          </button>
        ))}
      </div>
    </div>
  );
}
