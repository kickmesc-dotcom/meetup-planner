/**
 * GHG6 E11: настройки /zaebal — порог, длительности, авто-зэбал.
 *
 * Все поля живут в `admin_config` с дефолтами (см. services/bot_pause.py:118).
 * Save-кнопка активна только при `dirty` — иначе серая.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchZaebalSettings,
  updateZaebalSettings,
  type ZaebalSettings,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { Spinner } from "@/components/Spinner";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

export default function ZaebalSettingsScreen({ onBack }: Props) {
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ["admin", "zaebal-settings"],
    queryFn: fetchZaebalSettings,
  });

  const [draft, setDraft] = useState<ZaebalSettings | null>(null);
  useEffect(() => {
    if (q.data && draft === null) setDraft(q.data);
  }, [q.data, draft]);

  const dirty = useMemo(() => {
    if (!q.data || !draft) return false;
    return (
      draft.threshold !== q.data.threshold ||
      draft.duration_days !== q.data.duration_days ||
      draft.poll_hours !== q.data.poll_hours ||
      draft.vote_duration_days !== q.data.vote_duration_days ||
      draft.auto_enabled !== q.data.auto_enabled ||
      draft.auto_max_per_month !== q.data.auto_max_per_month
    );
  }, [q.data, draft]);

  const save = useMutation({
    mutationFn: updateZaebalSettings,
    onSuccess: (out) => {
      haptic("success");
      setDraft(out);
      qc.setQueryData(["admin", "zaebal-settings"], out);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  return (
    <SubScreen
      title="⏸ Пауза и /zaebal"
      subtitle="Порог голосов, длительности, авто-зэбал"
      onBack={onBack}
    >
      {q.isPending && (
        <div className="text-xs text-tg-hint">Загрузка…</div>
      )}
      {q.isError && (
        <div className="rounded-lg bg-status-busy/10 p-2 text-xs text-status-busy">
          ⚠ {humanizeApiError(q.error)}
        </div>
      )}
      {draft && (
        <>
          <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-3">
            <SectionHeader
              icon="🎯"
              title="/zaebal (порог в чате)"
              hint="Команда /zaebal в группе. Когда уникальных голосов в окне ≥ порога — пауза стартует."
            />
            <Field label={`Порог голосов: ${draft.threshold}`}>
              <RangeInput
                value={draft.threshold}
                min={1}
                max={5}
                step={1}
                onChange={(v) => setDraft({ ...draft, threshold: v })}
              />
              <Hint>1 — мгновенно после первого /zaebal; 5 — все шестеро.</Hint>
            </Field>
            <Field label={`Длительность паузы: ${draft.duration_days} дн.`}>
              <RangeInput
                value={draft.duration_days}
                min={1}
                max={30}
                step={1}
                onChange={(v) =>
                  setDraft({ ...draft, duration_days: v })
                }
              />
            </Field>
          </section>

          <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-3">
            <SectionHeader
              icon="🗳"
              title="/zaebal-vote (опрос)"
              hint="Telegram-опрос «GHG Bot — zaebal?». Если большинство «за» — пауза."
            />
            <Field label={`Открыт ${draft.poll_hours} ч.`}>
              <RangeInput
                value={draft.poll_hours}
                min={1}
                max={72}
                step={1}
                onChange={(v) => setDraft({ ...draft, poll_hours: v })}
              />
            </Field>
            <Field
              label={`Длительность паузы при «за»: ${draft.vote_duration_days} дн.`}
            >
              <RangeInput
                value={draft.vote_duration_days}
                min={1}
                max={30}
                step={1}
                onChange={(v) =>
                  setDraft({ ...draft, vote_duration_days: v })
                }
              />
            </Field>
          </section>

          <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-3">
            <SectionHeader
              icon="🤖"
              title="Авто-зэбал"
              hint="Бот сам запускает /zaebal-vote 15–18 числа месяца — самоирония."
            />
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm text-tg-text">Включён</div>
              <Switch
                checked={draft.auto_enabled}
                onChange={(v) => setDraft({ ...draft, auto_enabled: v })}
              />
            </div>
            <Field label={`Максимум раз в месяц: ${draft.auto_max_per_month}`}>
              <RangeInput
                value={draft.auto_max_per_month}
                min={1}
                max={4}
                step={1}
                onChange={(v) =>
                  setDraft({ ...draft, auto_max_per_month: v })
                }
              />
            </Field>
          </section>

          <button
            type="button"
            disabled={!dirty || save.isPending}
            onClick={() => {
              haptic("medium");
              save.mutate(draft);
            }}
            className="sticky bottom-0 w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform flex items-center justify-center gap-2"
          >
            {save.isPending && <Spinner />}
            💾 Сохранить настройки
          </button>
        </>
      )}
    </SubScreen>
  );
}

function SectionHeader({
  icon,
  title,
  hint,
}: {
  icon: string;
  title: string;
  hint?: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <span className="text-base">{icon}</span>
        <span className="text-sm font-semibold text-tg-text">{title}</span>
      </div>
      {hint && <div className="mt-0.5 text-[11px] text-tg-hint">{hint}</div>}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-[11px] text-tg-hint mb-1">{label}</div>
      {children}
    </div>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return <div className="mt-1 text-[10px] text-tg-hint">{children}</div>;
}

function RangeInput({
  value,
  min,
  max,
  step,
  onChange,
}: {
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-full accent-tg-button"
    />
  );
}

function Switch({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => {
        haptic("selection");
        onChange(!checked);
      }}
      className={[
        "shrink-0 inline-flex h-6 w-11 items-center rounded-full transition-colors",
        checked ? "bg-tg-button" : "bg-tg-hint/30",
      ].join(" ")}
      role="switch"
      aria-checked={checked}
    >
      <span
        className={[
          "inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-5" : "translate-x-0.5",
        ].join(" ")}
      />
    </button>
  );
}
