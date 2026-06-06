import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchBirthdays,
  fetchScheduledSettings,
  updateBirthdays,
  updateScheduledSettings,
  type BirthdayRow,
  type ScheduledSettingsIO,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";
import { ListSkeleton } from "@/components/Skeleton";
import { Checkbox, Toggle as TgToggle } from "@/components/Checkbox";
import { Spinner } from "@/components/Spinner";
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
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "birthdays"] });
      // BD-CAL1: подсветить 🎂 в календаре сразу после сохранения.
      qc.invalidateQueries({ queryKey: ["birthdays"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  return (
    <SubScreen
      title="🎂 Дни рождения"
      subtitle="Дата + что напоминать"
      onBack={onBack}
    >
      <BirthdaysMasterSwitch />
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

// P2.3.e: глобальный мастер-рубильник всех ДР-напоминаний. Дублирует
// birthdays.alerts_enabled из «Запланированных публикаций» (тот же queryKey
// ["admin","scheduled"] → синхронизируется автоматически). Per-user тогглы
// ниже не теряются — это отдельный слой; при выключенном рубильнике бот молчит
// независимо от них.
function BirthdaysMasterSwitch() {
  const qc = useQueryClient();
  const sched = useQuery({
    queryKey: ["admin", "scheduled"],
    queryFn: fetchScheduledSettings,
  });

  const save = useMutation({
    mutationFn: updateScheduledSettings,
    onMutate: async (next) => {
      await qc.cancelQueries({ queryKey: ["admin", "scheduled"] });
      const prev = qc.getQueryData<ScheduledSettingsIO>(["admin", "scheduled"]);
      qc.setQueryData(["admin", "scheduled"], next);
      return { prev };
    },
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "scheduled"], data);
    },
    onError: (e, _vars, ctx) => {
      haptic("error");
      if (ctx?.prev) qc.setQueryData(["admin", "scheduled"], ctx.prev);
      void showAlert(humanizeApiError(e));
    },
  });

  const enabled = sched.data?.birthdays.alerts_enabled ?? true;
  // GHG8 P3: старые серверы поля не отдают → дефолт "announce" (как на бэке).
  const immunityMode = sched.data?.birthdays.immunity_mode ?? "announce";

  const setImmunityMode = (mode: "announce" | "silent") => {
    if (mode === immunityMode || !sched.data) return;
    haptic("selection");
    const next = structuredClone(sched.data);
    next.birthdays.immunity_mode = mode;
    save.mutate(next);
  };

  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
      {sched.isPending || !sched.data ? (
        <ListSkeleton rows={1} />
      ) : (
        <>
          <TgToggle
            checked={enabled}
            disabled={save.isPending}
            label={enabled ? "🔔 Все ДР-напоминания" : "🔕 Напоминания отключены"}
            onChange={(v) => {
              const next = structuredClone(sched.data!);
              next.birthdays.alerts_enabled = v;
              save.mutate(next);
            }}
          />
          <div className="mt-1 text-[11px] text-tg-hint">
            Глобальный рубильник — гасит все ДР-уведомления у всех участников.
            Персональные галочки ниже при этом сохраняются.
          </div>

          {/* GHG8 P3.1.a: режим иммунитета именинника к лоху/чухану. Выключить
              иммунитет нельзя by design — настраивается только подача. */}
          <div className="mt-3">
            <div className="text-sm font-semibold text-tg-text mb-1">
              🛡 Иммунитет именинника
            </div>
            <div className="text-[11px] text-tg-hint mb-2">
              {immunityMode === "announce"
                ? "Именинник участвует в рулетке, но при выпадении бот объявит «мог бы стать…, но у него ДР» и перекрутит."
                : "Именинник молча исключается из рулетки — никаких объявлений."}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <ModeChip
                active={immunityMode === "announce"}
                disabled={save.isPending}
                onClick={() => setImmunityMode("announce")}
              >
                📣 С оглашением
              </ModeChip>
              <ModeChip
                active={immunityMode === "silent"}
                disabled={save.isPending}
                onClick={() => setImmunityMode("silent")}
              >
                🤫 Без оглашения
              </ModeChip>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

// GHG8 P3: chip-кнопка выбора режима (паттерн ModeChip из
// RandomPhrasesGeneratorScreen + disabled на время мутации).
function ModeChip({
  active,
  disabled,
  onClick,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={
        active
          ? "min-h-11 rounded-md bg-tg-button px-2 py-2 text-xs font-medium text-tg-button-text active:scale-[0.98] transition-transform disabled:opacity-60"
          : "min-h-11 rounded-md bg-tg-bg/70 px-2 py-2 text-xs text-tg-text border border-tg-hint/30 active:scale-[0.98] transition-transform disabled:opacity-60"
      }
    >
      {children}
    </button>
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
              <div className="pb-2">
                <Checkbox
                  size="sm"
                  checked={d.year_known}
                  onChange={(v) => patch(r.user_id, { year_known: v })}
                  label="год известен"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 gap-1">
              <TgToggle
                label="📅 За месяц"
                checked={d.remind_month}
                onChange={(v) => patch(r.user_id, { remind_month: v })}
              />
              <TgToggle
                label="🗓️ За неделю"
                checked={d.remind_week}
                onChange={(v) => patch(r.user_id, { remind_week: v })}
              />
              <TgToggle
                label="📌 За день"
                checked={d.remind_day}
                onChange={(v) => patch(r.user_id, { remind_day: v })}
              />
              <TgToggle
                label="🎉 В сам день (поздравление)"
                checked={d.remind_on_day}
                onChange={(v) => patch(r.user_id, { remind_on_day: v })}
              />
              <TgToggle
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
        onClick={() => {
          haptic("medium");
          onSave(Array.from(draft.values()));
        }}
        className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
      >
        {isPending && <Spinner />}
        {isPending ? "Сохраняем…" : dirty ? "💾 Сохранить" : "✓ Сохранено"}
      </button>
    </>
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
