import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchAutoLoser, updateAutoLoser, type AutoLoserSettings } from "@/api/admin";
import { haptic } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

export default function AutoLoserScreen({ onBack }: Props) {
  const qc = useQueryClient();

  const cfg = useQuery({ queryKey: ["admin", "autoloser"], queryFn: fetchAutoLoser });

  const save = useMutation({
    mutationFn: updateAutoLoser,
    onSuccess: () => {
      haptic("light");
      qc.invalidateQueries({ queryKey: ["admin", "autoloser"] });
      qc.invalidateQueries({ queryKey: ["admin", "jobs"] });
    },
    onError: () => haptic("error"),
  });

  return (
    <SubScreen
      title="🤡 Автолох"
      subtitle="Бот сам выбирает лоха в окне дня"
      onBack={onBack}
    >
      {cfg.isPending || !cfg.data ? (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
          <ListSkeleton rows={4} />
        </section>
      ) : (
        <AutoLoserForm
          initial={cfg.data}
          isPending={save.isPending}
          onSave={(body) => save.mutate(body)}
        />
      )}
      {save.isError && (
        <div className="rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
          ⚠ {String((save.error as Error)?.message ?? save.error)}
        </div>
      )}
    </SubScreen>
  );
}

function AutoLoserForm({
  initial,
  isPending,
  onSave,
}: {
  initial: AutoLoserSettings;
  isPending: boolean;
  onSave: (body: AutoLoserSettings) => void;
}) {
  const [enabled, setEnabled] = useState(initial.enabled);
  const [startH, setStartH] = useState(String(initial.window_start_hour));
  const [endH, setEndH] = useState(String(initial.window_end_hour));
  const [interval, setInterval_] = useState(String(initial.interval_hours));

  useEffect(() => {
    setEnabled(initial.enabled);
    setStartH(String(initial.window_start_hour));
    setEndH(String(initial.window_end_hour));
    setInterval_(String(initial.interval_hours));
  }, [initial]);

  const startN = clamp(parseInt(startH, 10) || 0, 0, 23);
  const endN = clamp(parseInt(endH, 10) || 22, 0, 23);
  const intervalN = clamp(parseInt(interval, 10) || 0, 0, 72);

  const body: AutoLoserSettings = {
    enabled,
    window_start_hour: startN,
    window_end_hour: endN,
    interval_hours: intervalN,
  };

  const dirty =
    body.enabled !== initial.enabled ||
    body.window_start_hour !== initial.window_start_hour ||
    body.window_end_hour !== initial.window_end_hour ||
    body.interval_hours !== initial.interval_hours;

  return (
    <>
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-3">
        <label
          className={`flex items-center justify-between gap-2 rounded-lg px-2 py-2.5 transition-colors ${
            enabled ? "bg-status-free/10" : "bg-tg-bg/40"
          }`}
        >
          <span className="text-sm font-medium text-tg-text">
            {enabled ? "🤖 Автолох включён" : "💤 Автолох выключен"}
          </span>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => {
              haptic("selection");
              setEnabled(e.target.checked);
            }}
            className="h-6 w-6 accent-status-free"
          />
        </label>

        <div>
          <div className="text-base font-semibold mb-1">🕐 Окно времени</div>
          <div className="text-xs text-tg-hint mb-2">
            Запуск разрешён только внутри окна (в часах локального TZ scheduler'а).
          </div>
          <div className="grid grid-cols-2 gap-2">
            <NumField label="с (0..23)" value={startH} onChange={setStartH} hint={`= ${startN}:00`} />
            <NumField label="до (0..23)" value={endH} onChange={setEndH} hint={`= ${endN}:00`} />
          </div>
        </div>

        <div>
          <div className="text-base font-semibold mb-1">⏳ Интервал</div>
          <div className="text-xs text-tg-hint mb-2">
            0 = random раз в сутки в окне. ≥1 = фикс. интервал в часах (jitter 5 мин).
          </div>
          <NumField
            label="часов (0..72)"
            value={interval}
            onChange={setInterval_}
            hint={intervalN === 0 ? "= random раз в сутки" : `= каждые ${intervalN} ч`}
          />
        </div>
      </section>

      <button
        type="button"
        disabled={!dirty || isPending}
        onClick={() => onSave(body)}
        className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform"
      >
        {isPending ? "Сохраняем…" : dirty ? "💾 Сохранить" : "✓ Сохранено"}
      </button>
    </>
  );
}

function NumField({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] text-tg-hint">{label}</span>
      <input
        type="text"
        inputMode="numeric"
        value={value}
        onChange={(e) => onChange(e.target.value.replace(/[^0-9]/g, ""))}
        className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text text-center tabular-nums outline-none border border-transparent focus:border-tg-link"
      />
      {hint && <span className="text-[10px] text-tg-hint">{hint}</span>}
    </label>
  );
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}
