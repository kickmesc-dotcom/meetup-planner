import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  TASK_MODE_LABEL,
  fetchAdminTasks,
  reviewTask,
  type HrAdminTask,
  type HrAdminTaskAssignment,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import { PhotoThumbs } from "@/components/PhotoAttach";
import ErrorState from "@/components/ErrorState";
import { CardSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";
import { useUI } from "@/store/ui";

/**
 * Приёмка работы.
 *
 * Сюда попадает только то, что сотрудники сдали в поручениях с проверкой
 * (`requires_review`). Принять можно одного исполнителя или всех, кто сдал:
 * в групповом поручении работы разные, и «принять всё» — не всегда верно.
 * Возврат требует комментария: «переделай» без причины сотруднику бесполезно.
 */
export default function ReviewScreen() {
  const setTab = useUI((s) => s.setTab);
  const tasksQ = useQuery({
    queryKey: ["hr-admin-tasks"],
    queryFn: () => fetchAdminTasks(),
  });
  const [openFor, setOpenFor] = useState<number | null>(null);

  if (tasksQ.isError) {
    return (
      <ErrorState error={tasksQ.error} onRetry={() => void tasksQ.refetch()} />
    );
  }

  const waiting = (tasksQ.data ?? []).filter((task) =>
    task.assignments.some((a) => a.status === "on_review"),
  );

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        <button
          type="button"
          onClick={() => {
            haptic("light");
            setTab("tasks");
          }}
          className="min-h-11 min-w-11 rounded-tile text-lg text-tg-link"
          aria-label="Назад к задачам"
        >
          ‹
        </button>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-tg-text">🔍 Приёмка</div>
          <div className="text-xs text-tg-hint">
            {waiting.length === 0
              ? "Работ на проверке нет"
              : `Ждут приёмки: ${waiting.length}`}
          </div>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        {tasksQ.isLoading && (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}

        {!tasksQ.isLoading && waiting.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="text-4xl" aria-hidden>
              ☑️
            </div>
            <div className="mt-2 text-sm font-medium text-tg-text">
              Всё принято
            </div>
            <div className="mt-1 max-w-[280px] text-xs text-tg-hint">
              Когда сотрудник сдаст поручение с проверкой, оно появится здесь.
            </div>
          </div>
        )}

        {waiting.map((task) => (
          <ReviewCard
            key={task.id}
            task={task}
            expanded={openFor === task.id}
            onToggle={() => {
              haptic("light");
              setOpenFor(openFor === task.id ? null : task.id);
            }}
            onDone={() => setOpenFor(null)}
          />
        ))}
      </div>
    </div>
  );
}

function fmtDue(iso: string | null): string {
  if (!iso) return "без срока";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "без срока";
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    ...(d.getSeconds() ? { second: "2-digit" as const } : {}),
  });
}

function ReviewCard({
  task,
  expanded,
  onToggle,
  onDone,
}: {
  task: HrAdminTask;
  expanded: boolean;
  onToggle: () => void;
  onDone: () => void;
}) {
  const waiting = task.assignments.filter((a) => a.status === "on_review");

  return (
    <article className="rounded-card bg-tg-secondary-bg/60 p-3">
      <button type="button" onClick={onToggle} className="w-full text-left">
        <div className="flex items-start justify-between gap-2">
          <h2 className="text-sm font-semibold text-tg-text break-words">
            {task.title}
          </h2>
          <span className="shrink-0 rounded-full bg-status-maybe/20 px-2 py-0.5 text-xs text-status-maybe">
            сдано {waiting.length}
          </span>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-tg-hint">
          <span>⏰ {fmtDue(task.due_at)}</span>
          {task.progress_total > 1 && (
            <span>
              👥 {TASK_MODE_LABEL[task.mode]} · {task.progress_done} из{" "}
              {task.progress_total}
            </span>
          )}
          {task.requires_photo && <span>📷 фотоотчёт</span>}
        </div>
      </button>

      {expanded && (
        <div className="mt-3 space-y-2">
          <PhotoThumbs photos={task.photos ?? []} size={96} />
          {waiting.map((assignment) => (
            <ReviewRow
              key={assignment.employee_id}
              taskId={task.id}
              assignment={assignment}
              onDone={onDone}
            />
          ))}
          {waiting.length > 1 && (
            <ReviewRow
              taskId={task.id}
              assignment={null}
              onDone={onDone}
            />
          )}
        </div>
      )}
    </article>
  );
}

function ReviewRow({
  taskId,
  assignment,
  onDone,
}: {
  taskId: number;
  assignment: HrAdminTaskAssignment | null;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const [comment, setComment] = useState("");
  const [reworkOpen, setReworkOpen] = useState(false);

  const review = useMutation({
    mutationFn: (approve: boolean) =>
      reviewTask(taskId, {
        approve,
        employee_id: assignment?.employee_id ?? null,
        comment: comment.trim() || null,
      }),
    onSuccess: (_data, approve) => {
      haptic(approve ? "success" : "warning");
      void qc.invalidateQueries({ queryKey: ["hr-admin-tasks"] });
      void qc.invalidateQueries({ queryKey: ["hr-tasks"] });
      void qc.invalidateQueries({ queryKey: ["review-queue"] });
      setComment("");
      setReworkOpen(false);
      onDone();
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  return (
    <div className="rounded-tile bg-tg-bg/60 p-2.5">
      <div className="text-xs font-medium text-tg-text">
        {assignment ? assignment.display_name : "Все, кто сдал"}
      </div>
      {assignment?.part && (
        <div className="mt-0.5 text-xs text-tg-hint">
          Часть: {assignment.part}
        </div>
      )}
      {assignment?.done_at && (
        <div className="mt-0.5 text-xs text-tg-hint">
          Сдано: {new Date(assignment.done_at).toLocaleString("ru-RU")}
        </div>
      )}

      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={review.isPending}
          onClick={() => review.mutate(true)}
          className="min-h-9 rounded-tile bg-tg-button px-3 text-xs font-medium text-tg-button-text disabled:opacity-50"
        >
          Принять
        </button>
        <button
          type="button"
          disabled={review.isPending}
          onClick={() => {
            haptic("light");
            setReworkOpen((v) => !v);
          }}
          className="min-h-9 rounded-tile bg-tg-secondary-bg px-3 text-xs text-tg-text"
        >
          {reworkOpen ? "Отмена" : "На доработку"}
        </button>
      </div>

      {reworkOpen && (
        <div className="mt-2">
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            maxLength={500}
            placeholder="Что переделать — коротко и по делу"
            className="w-full rounded-tile bg-tg-secondary-bg p-2 text-xs text-tg-text"
          />
          <button
            type="button"
            disabled={review.isPending || !comment.trim()}
            onClick={() => review.mutate(false)}
            className="mt-1.5 min-h-9 w-full rounded-tile bg-status-busy/20 text-xs font-medium text-status-busy disabled:opacity-50"
          >
            Вернуть с комментарием
          </button>
        </div>
      )}
    </div>
  );
}
