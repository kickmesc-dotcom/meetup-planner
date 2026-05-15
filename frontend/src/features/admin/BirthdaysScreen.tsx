import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchBirthdays, updateBirthdays, type BirthdayRow } from "@/api/admin";
import { haptic } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

type Draft = Omit<BirthdayRow, "display_name">;

export default function BirthdaysScreen({ onBack }: Props) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["admin", "birthdays"], queryFn: fetchBirthdays });

  const save = useMutation({
    mutationFn: updateBirthdays,
    onSuccess: () => {
      haptic("light");
      qc.invalidateQueries({ queryKey: ["admin", "birthdays"] });
    },
    onError: () => haptic("error"),
  });

  return (
    <SubScreen
      title="🎂 Дни рождения"
      subtitle="Дата + что напоминать"
      onBack={onBack}
    >
      {list.isPending || !list.data ? (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
          <ListSkeleton rows={6} />
        </section>
      ) : (
        <BirthdaysForm
          rows={list.data}
          isPending={save.isPending}
          onSave={(items) => save.mutate(items)}
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

function BirthdaysForm({
  rows,
  isPending,
  onSave,
}: {
  rows: BirthdayRow[];
  isPending: boolean;
  onSave: (items: Draft[]) => void;
}) {
  const [draft, setDraft] = useState<Map<number, Draft>>(() => toMap(rows));

  useEffect(() => {
    setDraft(toMap(rows));
  }, [rows]);

  const dirty = useMemo(() => {
    for (const r of rows) {
      const d = draft.get(r.user_id);
      if (!d) continue;
      if (
        d.bday !== r.bday ||
        d.year_known !== r.year_known ||
        d.remind_month !== r.remind_month ||
        d.remind_week !== r.remind_week ||
        d.remind_day !== r.remind_day ||
        d.remind_on_day !== r.remind_on_day ||
        d.remind_hint_week !== r.remind_hint_week
      ) {
        return true;
      }
    }
    return false;
  }, [rows, draft]);

  const patch = (userId: number, p: Partial<Draft>) => {
    setDraft((m) => {
      const next = new Map(m);
      const cur = next.get(userId);
      if (cur) next.set(userId, { ...cur, ...p });
      return next;
    });
  };

  return (
    <>
      {rows.map((r) => {
        const d = draft.get(r.user_id) ?? rowToDraft(r);
        return (
          <section key={r.user_id} className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
            <div className="text-sm font-semibold text-tg-text">{r.display_name}</div>

            <div className="grid grid-cols-[1fr_auto] gap-2 items-end">
              <label className="flex flex-col gap-1">
                <span className="text-[11px] text-tg-hint">Дата рождения</span>
                <input
                  type="date"
                  value={d.bday ?? ""}
                  onChange={(e) => {
                    haptic("selection");
                    patch(r.user_id, { bday: e.target.value || null });
                  }}
                  className="rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link"
                />
              </label>
              <label className="flex items-center gap-1.5 pb-2 text-[11px] text-tg-hint">
                <input
                  type="checkbox"
                  checked={d.year_known}
                  onChange={(e) => {
                    haptic("selection");
                    patch(r.user_id, { year_known: e.target.checked });
                  }}
                  className="h-4 w-4 accent-tg-link"
                />
                год известен
              </label>
            </div>

            <div className="grid grid-cols-1 gap-1">
              <Toggle
                label="📅 За месяц"
                checked={d.remind_month}
                onChange={(v) => patch(r.user_id, { remind_month: v })}
              />
              <Toggle
                label="🗓️ За неделю"
                checked={d.remind_week}
                onChange={(v) => patch(r.user_id, { remind_week: v })}
              />
              <Toggle
                label="📌 За день"
                checked={d.remind_day}
                onChange={(v) => patch(r.user_id, { remind_day: v })}
              />
              <Toggle
                label="🎉 В сам день (поздравление)"
                checked={d.remind_on_day}
                onChange={(v) => patch(r.user_id, { remind_on_day: v })}
              />
              <Toggle
                label="💡 За неделю — намёк задать встречу"
                checked={d.remind_hint_week}
                onChange={(v) => patch(r.user_id, { remind_hint_week: v })}
              />
            </div>
          </section>
        );
      })}

      <button
        type="button"
        disabled={!dirty || isPending}
        onClick={() => onSave(Array.from(draft.values()))}
        className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform"
      >
        {isPending ? "Сохраняем…" : dirty ? "💾 Сохранить" : "✓ Сохранено"}
      </button>
    </>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label
      className={`flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 transition-colors ${
        checked ? "bg-status-free/10" : "bg-tg-bg/30"
      }`}
    >
      <span className="text-xs text-tg-text">{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => {
          haptic("selection");
          onChange(e.target.checked);
        }}
        className="h-5 w-5 accent-status-free"
      />
    </label>
  );
}

function rowToDraft(r: BirthdayRow): Draft {
  return {
    user_id: r.user_id,
    bday: r.bday,
    year_known: r.year_known,
    remind_month: r.remind_month,
    remind_week: r.remind_week,
    remind_day: r.remind_day,
    remind_on_day: r.remind_on_day,
    remind_hint_week: r.remind_hint_week,
  };
}

function toMap(rows: BirthdayRow[]): Map<number, Draft> {
  const m = new Map<number, Draft>();
  for (const r of rows) m.set(r.user_id, rowToDraft(r));
  return m;
}
