import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { trackFeature } from "@/lib/product";
import { humanizeApiError } from "@/api/client";
import {
  fetchTrainees,
  setTraineeMentor,
  type HrTrainee,
} from "@/api/hrMentorship";
import { fetchEmployeesPool } from "@/api/hrOps";
import ErrorState from "@/components/ErrorState";
import Icon from "@/components/Icon";
import { ListSkeleton } from "@/components/Skeleton";
import { showAlert } from "@/tg/webapp";
import { useTx } from "@/i18n";
import SubScreen from "./SubScreen";

/**
 * Первая неделя новичка.
 *
 * Список отвечает на один вопрос: кого спросить сегодня. Поэтому сверху те, у
 * кого есть признаки риска (не заходил, просрочка, нет смен), а не все подряд
 * по алфавиту. Наставник назначается прямо здесь — пара должна заводиться в
 * тот же момент, когда руководитель заметил новичка, иначе он уйдёт в другой
 * экран и не вернётся.
 *
 * Почему в списке нет фильтра по отделу: руководитель отдела и так видит
 * только своих (сужает сервер), а администратору две недели новичков — это
 * короткий список, в котором отдел написан в строке.
 */
export default function MentorshipScreen({ onBack }: { onBack: () => void }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "trainees"], queryFn: () => fetchTrainees() });
  useEffect(() => {
    trackFeature("mentorship", "open");
  }, []);

  const poolQ = useQuery({
    queryKey: ["admin", "employees-pool"],
    queryFn: fetchEmployeesPool,
    staleTime: 60_000,
  });

  const assign = useMutation({
    mutationFn: ({ id, mentor }: { id: number; mentor: number | null }) =>
      setTraineeMentor(id, mentor),
    onSuccess: (_data, variables) => {
      trackFeature("mentorship", variables.mentor === null ? "unassign" : "assign");
      void qc.invalidateQueries({ queryKey: ["admin", "trainees"] });
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const mentors = (poolQ.data?.items ?? []).filter((item) => !item.is_demo);
  const items = q.data?.items ?? [];
  const risky = items.filter((item) => item.at_risk);

  return (
    <SubScreen
      title={tx("Первая неделя")}
      subtitle={
        q.data
          ? tx("Новички за {days} дн: {count}", {
              days: q.data.window_days,
              count: items.length,
            })
          : tx("Новички и наставники")
      }
      onBack={onBack}
    >
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.isLoading && <ListSkeleton rows={4} />}

      {q.data && items.length === 0 && (
        <p className="rounded-card bg-tg-secondary-bg/40 p-4 text-center text-xs text-tg-hint">
          {tx("За две недели новых сотрудников не было.")}
        </p>
      )}

      {q.data && items.length > 0 && (
        <>
          <p className="text-xs text-tg-hint">
            {risky.length > 0
              ? tx("Требуют внимания: {count}. Спросите, всё ли в порядке.", {
                  count: risky.length,
                })
              : tx("Все новички заходят и закрывают поручения вовремя.")}
          </p>
          <ul className="space-y-2">
            {items.map((item) => (
              <TraineeCard
                key={item.employee_id}
                item={item}
                mentors={mentors.map((mentor) => ({
                  id: mentor.employee_id,
                  name: mentor.display_name,
                }))}
                busy={assign.isPending && assign.variables?.id === item.employee_id}
                onAssign={(mentor) => assign.mutate({ id: item.employee_id, mentor })}
              />
            ))}
          </ul>
        </>
      )}
    </SubScreen>
  );
}

function TraineeCard({
  item,
  mentors,
  busy,
  onAssign,
}: {
  item: HrTrainee;
  mentors: { id: number; name: string }[];
  busy: boolean;
  onAssign: (mentor: number | null) => void;
}) {
  const { tx } = useTx();
  return (
    <li className="space-y-2 rounded-card bg-tg-secondary-bg/60 p-3">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-medium text-tg-text">{item.name}</span>
            {item.at_risk && (
              <span className="rounded-full bg-status-busy/15 px-1.5 py-0.5 text-2xs font-medium text-status-busy">
                {tx("внимание")}
              </span>
            )}
          </div>
          <div className="mt-0.5 text-2xs text-tg-hint">
            {[
              item.position,
              item.department,
              tx("{days} дн в команде", { days: item.days_in_team }),
            ]
              .filter(Boolean)
              .join(" · ")}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-x-3 gap-y-1 text-2xs text-tg-hint">
        <span>{tx("Смен за неделю: {count}", { count: item.shifts_week })}</span>
        <span className={item.overdue_tasks > 0 ? "text-status-busy" : undefined}>
          {tx("Просрочено: {count}", { count: item.overdue_tasks })}
        </span>
      </div>

      <label className="flex items-center gap-2 text-xs text-tg-hint">
        <Icon name="team" size={14} />
        <span className="shrink-0">{tx("Наставник")}</span>
        <select
          value={item.mentor_employee_id ?? ""}
          disabled={busy}
          onChange={(event) =>
            onAssign(event.target.value ? Number(event.target.value) : null)
          }
          className="min-h-9 min-w-0 flex-1 rounded-tile border border-tg-secondary-bg bg-tg-bg px-2 text-xs text-tg-text"
        >
          <option value="">{tx("Не назначен")}</option>
          {mentors
            .filter((mentor) => mentor.id !== item.employee_id)
            .map((mentor) => (
              <option key={mentor.id} value={mentor.id}>
                {mentor.name}
              </option>
            ))}
        </select>
      </label>
    </li>
  );
}
