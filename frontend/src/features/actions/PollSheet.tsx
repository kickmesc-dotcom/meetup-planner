import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { addDays, addHours, addMinutes, format, parseISO, startOfDay } from "date-fns";
import { createPoll } from "@/api/meetings";
import { fetchPollPresetsPublic, type PollPreset } from "@/api/admin";
import type { User } from "@/types";
import { useUI } from "@/store/ui";
import { haptic, showAlert } from "@/tg/webapp";
import { humanizeApiError } from "@/api/client";
import BottomSheet from "./BottomSheet";

interface Props {
  users: User[];
}

function defaultOption(daysAhead: number, preset?: PollPreset): string {
  const base = startOfDay(addDays(new Date(), daysAhead));
  if (preset) {
    const [h, m] = preset.start.split(":").map(Number);
    return addMinutes(addHours(base, h), m).toISOString().slice(0, 16);
  }
  return addHours(base, 19).toISOString().slice(0, 16); // "YYYY-MM-DDTHH:mm" for input
}

function applyPresetToOption(option: string, preset: PollPreset): string {
  // Сохраняем дату из option, заменяем часы/минуты на preset.start.
  try {
    const d = option ? parseISO(option) : new Date();
    const [h, m] = preset.start.split(":").map(Number);
    const next = addMinutes(addHours(startOfDay(d), h), m);
    return next.toISOString().slice(0, 16);
  } catch {
    return option;
  }
}

export default function PollSheet(_props: Props) {
  const close = () => useUI.getState().setShowPollSheet(false);
  const [question, setQuestion] = useState("Когда собираемся?");
  const presetsQ = useQuery({
    queryKey: ["poll-presets"],
    queryFn: fetchPollPresetsPublic,
    staleTime: 60_000,
  });
  const firstPreset = presetsQ.data?.[0];
  const [options, setOptions] = useState<string[]>([
    defaultOption(1, firstPreset),
    defaultOption(2, firstPreset),
    defaultOption(3, firstPreset),
  ]);
  const [closesIn, setClosesIn] = useState(24);
  const [error, setError] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: () =>
      createPoll({
        question: question.trim(),
        options: options
          .filter(Boolean)
          .map((v) => new Date(v).toISOString()),
        closes_in_hours: closesIn,
      }),
    onSuccess: () => {
      haptic("success");
      close();
    },
    onError: (e) => {
      haptic("error");
      const human = humanizeApiError(e);
      setError(human);
      void showAlert(human);
    },
  });

  const setOption = (i: number, v: string) => {
    setOptions((o) => o.map((x, idx) => (idx === i ? v : x)));
  };

  const addOption = () => {
    if (options.length >= 5) return;
    setOptions((o) => [...o, defaultOption(o.length + 1)]);
  };

  const removeOption = (i: number) => {
    if (options.length <= 2) return;
    setOptions((o) => o.filter((_, idx) => idx !== i));
  };

  const valid =
    question.trim().length > 0 &&
    options.length >= 2 &&
    options.every((v) => !!v && !Number.isNaN(new Date(v).getTime()));

  return (
    <BottomSheet title="📊 Опрос в чат" onClose={close}>
      <label className="text-sm">
        <div className="mb-1 text-xs text-tg-hint">Вопрос</div>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={255}
          className="w-full rounded-lg bg-tg-secondary-bg px-3 py-2"
        />
      </label>

      <div className="mt-3 space-y-2">
        <div className="text-xs text-tg-hint">Варианты дат (2–5)</div>
        {options.map((v, i) => (
          <div key={i} className="space-y-1">
            <div className="flex items-center gap-2">
              <input
                type="datetime-local"
                value={v}
                onChange={(e) => setOption(i, e.target.value)}
                className="flex-1 rounded-lg bg-tg-secondary-bg px-3 py-2 text-sm"
              />
              <span className="text-xs text-tg-hint">
                {v ? format(new Date(v), "EEE") : ""}
              </span>
              {options.length > 2 && (
                <button
                  type="button"
                  onClick={() => removeOption(i)}
                  className="rounded-lg bg-status-busy/15 px-2 py-2 text-xs text-status-busy"
                >
                  ✕
                </button>
              )}
            </div>
            {presetsQ.data && presetsQ.data.length > 0 && (
              <div className="flex flex-wrap gap-1 pl-1">
                {presetsQ.data.map((p, pi) => (
                  <button
                    key={pi}
                    type="button"
                    onClick={() => {
                      haptic("selection");
                      setOption(i, applyPresetToOption(v, p));
                    }}
                    className="rounded-md border border-tg-secondary-bg/80 bg-tg-bg/40 px-2 py-0.5 text-[11px] text-tg-text hover:bg-tg-link/15"
                  >
                    {p.start}–{p.end}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {options.length < 5 && (
          <button
            type="button"
            onClick={addOption}
            className="w-full rounded-lg bg-tg-secondary-bg/60 py-2 text-sm"
          >
            + ещё вариант
          </button>
        )}
      </div>

      <label className="mt-3 block text-sm">
        <div className="mb-1 text-xs text-tg-hint">Закрыть через</div>
        <select
          value={closesIn}
          onChange={(e) => setClosesIn(Number(e.target.value))}
          className="w-full rounded-lg bg-tg-secondary-bg px-2 py-2"
        >
          <option value={6}>6 часов</option>
          <option value={12}>12 часов</option>
          <option value={24}>24 часа</option>
          <option value={48}>2 дня</option>
          <option value={72}>3 дня</option>
        </select>
      </label>

      {error && (
        <div className="mt-2 rounded-lg bg-status-busy/15 p-2 text-center text-sm text-status-busy">
          {error}
        </div>
      )}

      <button
        type="button"
        onClick={() => {
          haptic("medium");
          mut.mutate();
        }}
        disabled={!valid || mut.isPending}
        className="mt-4 w-full rounded-xl bg-tg-button py-3 font-medium text-tg-button-text disabled:opacity-50"
      >
        {mut.isPending ? "Отправляем…" : "Отправить в чат"}
      </button>

      <button
        type="button"
        onClick={close}
        className="mt-2 w-full rounded-xl bg-tg-secondary-bg py-3 font-medium"
      >
        Отмена
      </button>
    </BottomSheet>
  );
}
