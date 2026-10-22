/**
 * «Интервалы» — один рабочий параметр: как часто планировщик проверяет очередь
 * напоминаний к встречам. Раньше здесь же жили окна автолоха, автопоста
 * рандомных фраз и публикации чухана; этих модулей больше нет.
 */
import { ReactNode, useEffect, useState } from "react";
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
import Icon, { type IconName } from "@/components/Icon";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

export default function IntervalsScreen({ onBack }: Props) {
  const qc = useQueryClient();

  const sched = useQuery({
    queryKey: ["admin", "scheduled"],
    queryFn: fetchScheduledSettings,
  });

  const [tick, setTick] = useState<number | null>(null);
  useEffect(() => {
    if (sched.data) setTick(sched.data.reminders.tick_minutes);
  }, [sched.data]);

  const dirty =
    !!sched.data && tick !== null && tick !== sched.data.reminders.tick_minutes;

  const save = useMutation({
    mutationFn: () => {
      const base = sched.data as ScheduledSettingsIO;
      return updateScheduledSettings({
        ...base,
        reminders: { ...base.reminders, tick_minutes: tick ?? base.reminders.tick_minutes },
      });
    },
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["admin", "scheduled"], data);
      qc.invalidateQueries({ queryKey: ["admin", "jobs"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  if (sched.isPending || tick === null) {
    return (
      <SubScreen title="Интервалы" subtitle="Расписание напоминаний" onBack={onBack}>
        <ListSkeleton rows={3} />
      </SubScreen>
    );
  }

  return (
    <SubScreen
      title="Интервалы"
      subtitle="Как часто проверять очередь напоминаний"
      onBack={onBack}
    >
      <Block
        icon="clock"
        title="Тик напоминаний"
        hint="Раз в N минут бот проверяет, кому пора напомнить о встрече."
      >
        <div className="flex items-center gap-2">
          <input
            type="text"
            inputMode="numeric"
            value={String(tick)}
            onChange={(e) => setTick(Number(e.target.value.replace(/[^0-9]/g, "")))}
            className="w-24 rounded-tile bg-tg-bg/70 px-2 py-2 text-center text-sm tabular-nums text-tg-text outline-none border border-transparent focus:border-tg-link"
            aria-label="Интервал напоминаний, минут"
          />
          <span className="text-xs text-tg-hint">мин (1–360)</span>
        </div>
      </Block>

      <div className="rounded-card bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
        Напоминания о сроках поручений настраиваются в «Уведомлениях сотрудников»:
        там же можно выключить конкретное, перенести его вперёд или замьютить все
        алерты.
      </div>

      <div className="sticky bottom-0 -mx-3 px-3 pb-3 pt-2 bg-tg-bg/95 backdrop-blur">
        <button
          type="button"
          disabled={!dirty || save.isPending || (tick !== null && (tick < 1 || tick > 360))}
          onClick={() => {
            haptic("medium");
            save.mutate();
          }}
          className="w-full min-h-11 rounded-tile bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-40 active:scale-[0.98] transition-transform inline-flex items-center justify-center gap-2"
        >
          {save.isPending && <Spinner />}            {save.isPending ? (
              "Сохраняем…"
            ) : dirty ? (
              <>
                <Icon name="save" size={16} />
                Сохранить
              </>
            ) : (
              <>
                <Icon name="check" size={16} />
                Сохранено
              </>
            )}
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
  icon: IconName;
  title: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-card bg-tg-secondary-bg/60 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <Icon name={icon} size={18} className="shrink-0 text-tg-hint" />
        <div className="min-w-0">
          <div className="text-base font-semibold text-tg-text">{title}</div>
          <div className="text-xs text-tg-hint">{hint}</div>
        </div>
      </div>
      {children}
    </section>
  );
}
