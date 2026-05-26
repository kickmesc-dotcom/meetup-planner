import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import type { AvailabilityRange, Status } from "@/types";
import { deleteRange, fetchRanges, patchRange } from "@/api/availability";
import { useUI } from "@/store/ui";
import { haptic } from "@/tg/webapp";
import { addDays, format, startOfDay } from "date-fns";

interface Props {
  rangeId: number | "new";
  windowStart: Date;
  windowEnd: Date;
  meId: number;
}

/**
 * GHG6 CL8: bottom-sheet редактор range.
 *
 * Изменения относительно CL7:
 * - Чекбокс «🕓 Конкретное время» — управляет `all_day`. Off (по умолчанию) →
 *   `all_day=true`, окно сутки 00:00..23:59:59. On → `all_day=false` +
 *   два `<input type="time">` (старт/конец) на той же дате, что и `starts_at`.
 * - Дефолт confidence при смене статуса (см. handler смены status):
 *   свободен→5, занят→5, может→3 (см. ответ пользователя 2026-05-25).
 *   Шкала confidence: 5 = высокая уверенность, 1 = низкая
 *   (см. `dateUtils::pickConfidenceColor`).
 * - Подписи `CONFIDENCE_LABELS` приведены к шкале: 1=«Точно нет», 5=«Точно да».
 *   Раньше были инверсные, что вводило в заблуждение (баг наследия).
 */
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
      // Оптимистично подменяем поля в кэше ranges, чтобы пилюля/заливка
      // перекрашивались сразу. На ошибке откатываем.
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

  // CL8: дефолт confidence по новому статусу. При смене status «свободен» или
  // «занят» — выставляем максимум (5), «может» — середину (3).
  const defaultConfidenceForStatus = (s: Status): number => (s === 2 ? 3 : 5);

  const onStatusChange = (s: Status) => {
    if (!range) return;
    haptic("selection");
    const conf = defaultConfidenceForStatus(s);
    setRange({ ...range, status: s, confidence: conf });
    patchMut.mutate({ status: s, confidence: conf });
  };

  const onConfidenceChange = (c: number) => {
    if (!range) return;
    haptic("selection");
    setRange({ ...range, confidence: c });
    patchMut.mutate({ confidence: c });
  };

  // CL8: переключение all_day. Off → весь день (00:00..23:59:59 локального tz
  // того дня, в котором сейчас starts_at). On → берём текущее time-окно или
  // дефолт 09:00..18:00 на этой же дате.
  const onAllDayToggle = (allDay: boolean) => {
    if (!range) return;
    haptic("selection");
    const startDate = new Date(range.starts_at);
    const dayBase = startOfDay(startDate);
    let nextStarts: Date;
    let nextEnds: Date;
    if (allDay) {
      // Off → all_day. Окно — сутки. ends берём как 23:59:59.999 чтобы не пересечь
      // следующий день (бэк валидирует ends > starts строгим неравенством).
      nextStarts = dayBase;
      nextEnds = new Date(dayBase.getTime() + 24 * 60 * 60 * 1000 - 1);
    } else {
      // On → конкретное время. Если range уже не all_day, берём текущие
      // часы:минуты; иначе дефолт 09:00..18:00.
      if (!range.all_day) {
        nextStarts = startDate;
        nextEnds = new Date(range.ends_at);
      } else {
        nextStarts = new Date(dayBase.getTime() + 9 * 60 * 60 * 1000);
        nextEnds = new Date(dayBase.getTime() + 18 * 60 * 60 * 1000);
      }
    }
    setRange({
      ...range,
      all_day: allDay,
      starts_at: nextStarts.toISOString(),
      ends_at: nextEnds.toISOString(),
    });
    patchMut.mutate({
      all_day: allDay,
      starts_at: nextStarts.toISOString(),
      ends_at: nextEnds.toISOString(),
    });
  };

  // CL8: смена времени в pickers. timeKind = 'start' | 'end'. value — "HH:MM".
  // Сохраняем дату текущего starts_at, меняем только часы/минуты выбранного
  // конца. Бэк требует ends > starts; при нарушении (старт >= конец) патчим
  // вторую границу +30мин, чтобы не падать на валидаторе.
  const onTimeChange = (kind: "start" | "end", value: string) => {
    if (!range) return;
    const [hh, mm] = value.split(":").map((x) => Number.parseInt(x, 10));
    if (Number.isNaN(hh) || Number.isNaN(mm)) return;
    const base = startOfDay(new Date(range.starts_at));
    const baseMs = base.getTime();
    const startMs = new Date(range.starts_at).getTime();
    const endMs = new Date(range.ends_at).getTime();
    const newPointMs = baseMs + hh * 60 * 60 * 1000 + mm * 60 * 1000;
    let nextStartsMs = startMs;
    let nextEndsMs = endMs;
    if (kind === "start") {
      nextStartsMs = newPointMs;
      if (nextEndsMs <= nextStartsMs) {
        nextEndsMs = Math.min(addDays(base, 1).getTime() - 1, nextStartsMs + 30 * 60 * 1000);
      }
    } else {
      nextEndsMs = newPointMs;
      if (nextEndsMs <= nextStartsMs) {
        nextStartsMs = Math.max(baseMs, nextEndsMs - 30 * 60 * 1000);
      }
    }
    const nextStarts = new Date(nextStartsMs).toISOString();
    const nextEnds = new Date(nextEndsMs).toISOString();
    setRange({ ...range, starts_at: nextStarts, ends_at: nextEnds });
    patchMut.mutate({ starts_at: nextStarts, ends_at: nextEnds });
  };

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
              {range.all_day
                ? format(new Date(range.starts_at), "d MMM")
                : `${format(new Date(range.starts_at), "d MMM HH:mm")} → ${format(
                    new Date(range.ends_at),
                    "HH:mm",
                  )}`}
            </div>

            <StatusPicker
              value={range.status as Status}
              disabled={!isOwn}
              onChange={onStatusChange}
            />

            <ConfidencePicker
              value={range.confidence}
              status={range.status as Status}
              disabled={!isOwn}
              onChange={onConfidenceChange}
            />

            <TimePicker
              allDay={range.all_day}
              startsAt={range.starts_at}
              endsAt={range.ends_at}
              disabled={!isOwn}
              onAllDayToggle={onAllDayToggle}
              onTimeChange={onTimeChange}
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

// CL8: подписи confidence по реальной шкале (5 = высокая уверенность,
// 1 = низкая). Для status=2 («может») — нейтральные «Не уверен / 50/50 /
// Уверенно», т.к. «точно нет/точно да» в контексте «может» бессмысленны
// (статус и так промежуточный).
const CONFIDENCE_LABELS_DEFAULT: Record<number, string> = {
  1: "Точно нет",
  2: "Скорее нет",
  3: "Под вопросом",
  4: "Скорее да",
  5: "Точно да",
};

const CONFIDENCE_LABELS_MAYBE: Record<number, string> = {
  1: "Едва ли",
  2: "Слабо",
  3: "50/50",
  4: "Склоняюсь",
  5: "Почти точно",
};

function ConfidencePicker({
  value,
  status,
  onChange,
  disabled,
}: {
  value: number;
  status: Status;
  onChange: (c: number) => void;
  disabled?: boolean;
}) {
  const labels = status === 2 ? CONFIDENCE_LABELS_MAYBE : CONFIDENCE_LABELS_DEFAULT;
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
              "flex-1 py-2 rounded-lg text-[11px] leading-tight",
              value === c ? "bg-tg-button text-tg-button-text" : "bg-tg-secondary-bg",
            ].join(" ")}
          >
            {labels[c]}
          </button>
        ))}
      </div>
    </div>
  );
}

// CL8: time-picker для конкретного времени range'а. Чекбокс над — «🕓
// Конкретное время». В off-режиме скрыты сами поля времени; в on — два
// `<input type="time">` (часы:минуты, native picker на iOS/Android).
function TimePicker({
  allDay,
  startsAt,
  endsAt,
  disabled,
  onAllDayToggle,
  onTimeChange,
}: {
  allDay: boolean;
  startsAt: string;
  endsAt: string;
  disabled?: boolean;
  onAllDayToggle: (v: boolean) => void;
  onTimeChange: (kind: "start" | "end", value: string) => void;
}) {
  const startHm = format(new Date(startsAt), "HH:mm");
  const endHm = format(new Date(endsAt), "HH:mm");
  return (
    <div className="my-3">
      <label className="flex items-center gap-2 select-none cursor-pointer">
        <input
          type="checkbox"
          className="h-4 w-4 accent-tg-link"
          checked={!allDay}
          disabled={disabled}
          onChange={(e) => onAllDayToggle(!e.currentTarget.checked)}
        />
        <span className="text-sm">🕓 Конкретное время</span>
      </label>
      {!allDay && (
        <div className="mt-2 flex items-center gap-2">
          <input
            type="time"
            className="flex-1 rounded-lg bg-tg-secondary-bg px-3 py-2 text-sm"
            value={startHm}
            disabled={disabled}
            onChange={(e) => onTimeChange("start", e.currentTarget.value)}
          />
          <span className="text-tg-hint text-sm">→</span>
          <input
            type="time"
            className="flex-1 rounded-lg bg-tg-secondary-bg px-3 py-2 text-sm"
            value={endHm}
            disabled={disabled}
            onChange={(e) => onTimeChange("end", e.currentTarget.value)}
          />
        </div>
      )}
    </div>
  );
}
