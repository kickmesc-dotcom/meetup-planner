import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { humanizeApiError } from "@/api/client";
import {
  fetchJournal,
  forceTaskDone,
  type HrJournalItem,
} from "@/api/hrOps";
import { ListSkeleton } from "@/components/Skeleton";
import ErrorState from "@/components/ErrorState";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import SubScreen from "./SubScreen";

/**
 * Журнал событий (админ): человекочитаемая история поручений.
 *
 * Здесь живут и системные строки планировщика (`auto_overdue`, `reminder_sent`):
 * в кабинете руководителя их нет — там разбор смены, а не лог. Проваленное
 * поручение можно зачесть руками: в рабочем потоке это делает приёмка, но
 * бывает, что человек реально доделал работу вне приложения.
 */
export default function JournalScreen({ onBack }: { onBack: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "journal"],
    queryFn: () => fetchJournal(150),
    staleTime: 30_000,
  });

  const force = useMutation({
    mutationFn: ({ taskId, employeeId }: { taskId: number; employeeId: number }) =>
      forceTaskDone(taskId, employeeId, "админка: зачтено вручную"),
    onSuccess: () => {
      haptic("success");
      void qc.invalidateQueries({ queryKey: ["admin", "journal"] });
      void qc.invalidateQueries({ queryKey: ["hr-dashboard"] });
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const groups = useMemo(() => groupByDay(q.data?.items ?? []), [q.data]);

  return (
    <SubScreen
      title="🗂 Журнал событий"
      subtitle="Поручения: кто что сделал и что отправил планировщик"
      onBack={onBack}
    >
      {q.isLoading && <ListSkeleton rows={8} />}
      {q.isError && (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      )}

      {q.data && q.data.items.length === 0 && (
        <p className="py-8 text-center text-xs text-tg-hint">
          Пока пусто: поручений ещё не было.
        </p>
      )}

      {groups.map((group) => (
        <section key={group.label} className="space-y-2">
          <h2 className="text-xs font-medium uppercase tracking-wide text-tg-hint">
            {group.label}
          </h2>
          <div className="divide-y divide-tg-secondary-bg/70 overflow-hidden rounded-card bg-tg-secondary-bg/40">
            {group.items.map((item, index) => (
              <JournalRow
                key={`${item.at}-${item.task_id ?? "x"}-${index}`}
                item={item}
                onForce={() => {
                  if (item.task_id === null || item.employee_id === null) return;
                  void (async () => {
                    const ok = await showConfirm(
                      `Зачесть поручение «${item.task_title ?? ""}» выполненным за ${
                        item.display_name ?? "сотрудника"
                      }?`,
                    );
                    if (ok) {
                      force.mutate({
                        taskId: item.task_id as number,
                        employeeId: item.employee_id as number,
                      });
                    }
                  })();
                }}
                forceBusy={force.isPending}
              />
            ))}
          </div>
        </section>
      ))}
    </SubScreen>
  );
}

function JournalRow({
  item,
  onForce,
  forceBusy,
}: {
  item: HrJournalItem;
  onForce: () => void;
  forceBusy: boolean;
}) {
  const canForce =
    item.kind === "failed" && item.task_id !== null && item.employee_id !== null;
  return (
    <div className="px-3 py-2.5">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 text-base" aria-hidden>
          {item.is_system ? "🤖" : "🧑"}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm text-tg-text break-words">
            <span className="font-medium">{item.display_name ?? "Система"}</span>{" "}
            {item.text}
            {item.task_title ? ` «${item.task_title}»` : ""}
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-tg-hint">
            <span>{formatMoment(item.at)}</span>
            {item.is_system && <span>· автоматически</span>}
          </div>
        </div>
        {canForce && (
          <button
            type="button"
            disabled={forceBusy}
            onClick={() => {
              haptic("selection");
              onForce();
            }}
            className="shrink-0 min-h-8 rounded-full bg-tg-bg/60 px-2.5 text-xs text-tg-link disabled:opacity-50"
          >
            Зачесть
          </button>
        )}
      </div>
    </div>
  );
}

function dayLabel(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Без даты";
  const startOf = (value: Date) =>
    new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
  const diff = Math.round((startOf(new Date()) - startOf(date)) / 86_400_000);
  if (diff === 0) return "Сегодня";
  if (diff === 1) return "Вчера";
  return date.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}

function groupByDay(
  items: HrJournalItem[],
): { label: string; items: HrJournalItem[] }[] {
  const groups: { label: string; items: HrJournalItem[] }[] = [];
  for (const item of items) {
    const label = dayLabel(item.at);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.items.push(item);
    else groups.push({ label, items: [item] });
  }
  return groups;
}

function formatMoment(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });
}
