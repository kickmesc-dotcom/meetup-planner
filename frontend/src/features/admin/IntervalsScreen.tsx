import { ReactNode, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchScheduledSettings,
  updateScheduledSettings,
  type ScheduledSettingsIO,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import { Spinner } from "@/components/Spinner";
import SubScreen from "./SubScreen";

/**
 * GHG6 H3 (п.16): единый блок «Интервалы и окна».
 *
 * Числовые/временные параметры расписания (тик напоминаний, частота и окно
 * автолоха, окно автопостинга фраз, день+окно публикации чухана) собраны в
 * одном экране. Master-toggles остаются в «Запланированных публикациях» —
 * один-два клика, чтобы что-то включить/выключить; сюда же залезаешь раз в
 * месяц поправить «когда» и «как часто».
 *
 * Один draft, одна sticky-кнопка «Сохранить» — backend дёргает
 * `scheduler.reload_dynamic_jobs(bot)` после PUT'а.
 */
const WEEKDAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

interface Props {
  onBack: () => void;
}

const errAlert = (e: unknown) => {
  haptic("error");
  void showAlert(humanizeApiError(e));
};

export default function IntervalsScreen({ onBack }: Props) {
  const qc = useQueryClient();

  const sched = useQuery({
    queryKey: ["admin", "scheduled"],
    queryFn: fetchScheduledSettings,
  });

  const [draft, setDraft] = useState<ScheduledSettingsIO | null>(null);
  useEffect(() => {
    if (sched.data) setDraft(structuredClone(sched.data));
  }, [sched.data]);

  const dirty = useMemo(
    () => !!draft && !!sched.data && JSON.stringify(draft) !== JSON.stringify(sched.data),
    [draft, sched.data],
  );

  const save = useMutation({
    mutationFn: updateScheduledSettings,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "scheduled"], data);
      qc.invalidateQueries({ queryKey: ["admin", "jobs"] });
    },
    onError: errAlert,
  });

  const patch = (updater: (d: ScheduledSettingsIO) => ScheduledSettingsIO) => {
    setDraft((cur) => (cur ? updater(structuredClone(cur)) : cur));
  };

  if (sched.isPending || !draft) {
    return (
      <SubScreen title="🎛 Интервалы и окна" subtitle="Расписание задач" onBack={onBack}>
        <ListSkeleton rows={6} />
      </SubScreen>
    );
  }

  return (
    <SubScreen
      title="🎛 Интервалы и окна"
      subtitle="Раз в месяц заглянуть и поправить — рубильники живут в «Запланированных публикациях»"
      onBack={onBack}
    >
      <Block icon="⏰" title="Тик напоминаний" hint="Раз в N минут бот проверяет очередь напоминаний к встречам.">
        <Field label="Интервал, мин (1–120)">
          <NumberInput
            value={draft.reminders.tick_minutes}
            min={1}
            max={120}
            onChange={(v) =>
              patch((d) => {
                d.reminders.tick_minutes = v;
                return d;
              })
            }
          />
        </Field>
      </Block>

      <Block
        icon="🤡"
        title="Автолох"
        hint="Кулдаун ручной рулетки и автолоха теперь независимы — авто крутится по этому расписанию, ручная — по своим 12ч."
      >
        <Field label="Раз в сутки (1–12)">
          <NumberInput
            value={draft.loser.per_day}
            min={1}
            max={12}
            onChange={(v) =>
              patch((d) => {
                d.loser.per_day = v;
                return d;
              })
            }
          />
        </Field>
        <Field label="Окно активности (часы)">
          <HourRange
            start={draft.loser.window_start_hour}
            end={draft.loser.window_end_hour}
            onChange={(s, e) =>
              patch((d) => {
                d.loser.window_start_hour = s;
                d.loser.window_end_hour = e;
                return d;
              })
            }
          />
        </Field>
      </Block>

      <Block icon="💬" title="Автопост фраз" hint="Окно — когда бот может постить рандомные фразы. Сами времена — в «Автопост рандомных фраз».">
        <Field label="Окно активности">
          <HhmmRange
            start={draft.phrases.window_start}
            end={draft.phrases.window_end}
            onChange={(s, e) =>
              patch((d) => {
                d.phrases.window_start = s;
                d.phrases.window_end = e;
                return d;
              })
            }
          />
        </Field>
      </Block>

      <Block icon="💩" title="Чухан недели" hint="День недели и окно — в этот промежуток бот публикует чухана.">
        <Field label="День недели">
          <div className="flex flex-wrap gap-1">
            {WEEKDAYS_RU.map((label, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => {
                  haptic("selection");
                  patch((d) => {
                    d.chukhan.weekday = idx;
                    return d;
                  });
                }}
                className={[
                  "min-h-9 min-w-9 rounded-md px-2 text-xs",
                  draft.chukhan.weekday === idx
                    ? "bg-tg-button text-tg-button-text"
                    : "bg-tg-bg/70 text-tg-text",
                ].join(" ")}
              >
                {label}
              </button>
            ))}
          </div>
        </Field>
        <Field label="Окно активности">
          <HhmmRange
            start={draft.chukhan.window_start}
            end={draft.chukhan.window_end}
            onChange={(s, e) =>
              patch((d) => {
                d.chukhan.window_start = s;
                d.chukhan.window_end = e;
                return d;
              })
            }
          />
        </Field>
      </Block>

      <div className="sticky bottom-0 -mx-3 px-3 pb-3 pt-2 bg-tg-bg/95 backdrop-blur">
        <button
          type="button"
          disabled={!dirty || save.isPending}
          onClick={() => {
            if (!draft) return;
            haptic("medium");
            save.mutate(draft);
          }}
          className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
        >
          {save.isPending && <Spinner />}
          {save.isPending
            ? "Сохраняем…"
            : dirty
            ? "💾 Сохранить интервалы"
            : "✓ Сохранено"}
        </button>
      </div>
    </SubScreen>
  );
}

function Block({
  icon,
  title,
  hint,
  children,
}: {
  icon: string;
  title: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-base">{icon}</span>
        <div className="min-w-0">
          <div className="text-base font-semibold text-tg-text">{title}</div>
          <div className="text-[11px] text-tg-hint">{hint}</div>
        </div>
      </div>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-[11px] text-tg-hint mb-1">{label}</div>
      {children}
    </div>
  );
}

function NumberInput({
  value,
  min,
  max,
  step = 1,
  onChange,
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => {
    setDraft(String(value));
  }, [value]);
  const isInt = step >= 1 && Number.isInteger(step);
  return (
    <input
      type="text"
      inputMode={isInt ? "numeric" : "decimal"}
      value={draft}
      onChange={(e) => {
        const cleaned = e.target.value.replace(isInt ? /[^0-9]/g : /[^0-9.]/g, "");
        setDraft(cleaned);
      }}
      onBlur={() => {
        const n = parseFloat(draft);
        if (Number.isNaN(n)) {
          setDraft(String(value));
          return;
        }
        const clamped = Math.max(min, Math.min(max, n));
        const rounded = isInt ? Math.round(clamped) : Math.round(clamped * 100) / 100;
        setDraft(String(rounded));
        if (rounded !== value) onChange(rounded);
      }}
      className="w-24 rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text text-center tabular-nums outline-none border border-transparent focus:border-tg-link"
    />
  );
}

function HourRange({
  start,
  end,
  onChange,
}: {
  start: number;
  end: number;
  onChange: (s: number, e: number) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <NumberInput value={start} min={0} max={23} onChange={(v) => onChange(v, end)} />
      <span className="text-tg-hint text-xs">…</span>
      <NumberInput value={end} min={0} max={23} onChange={(v) => onChange(start, v)} />
      <span className="text-tg-hint text-xs">ч</span>
    </div>
  );
}

function HhmmRange({
  start,
  end,
  onChange,
}: {
  start: string;
  end: string;
  onChange: (s: string, e: string) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <input
        type="time"
        value={start}
        onChange={(e) => onChange(e.target.value, end)}
        className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
      />
      <span className="text-tg-hint text-xs">…</span>
      <input
        type="time"
        value={end}
        onChange={(e) => onChange(start, e.target.value)}
        className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
      />
    </div>
  );
}
