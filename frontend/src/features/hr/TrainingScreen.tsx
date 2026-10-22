import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  completeTrainingLesson,
  fetchTraining,
  resetTraining,
  type HrTraining,
  type HrTrainingLesson,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import { CardSkeleton } from "@/components/Skeleton";
import ErrorState from "@/components/ErrorState";
import Icon from "@/components/Icon";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";

/**
 * Обучение пользованию приложением — отдельный этап онбординга.
 *
 * Один экран = одно действие: раскрыл урок, прочитал три шага, нажал «Понятно».
 * Прогресс хранит сервер, поэтому курс можно прервать и вернуться.
 *
 * Уроки сгруппированы по уровням погружения (знакомство → основные задачи →
 * самостоятельная работа): новичок видит, что освоил и что впереди, вместо
 * плоского списка из семи пунктов.
 */
export default function TrainingScreen({
  onClose,
  onFinish,
  finishing = false,
}: {
  onClose?: () => void;
  /** Выбор режима после первого этапа: «Повторим вместе» / «Я уже запомнил». */
  onFinish?: (learningMode: boolean) => void;
  finishing?: boolean;
}) {
  const qc = useQueryClient();
  const [openCode, setOpenCode] = useState<string | null>(null);
  const training = useQuery({ queryKey: ["hr-training"], queryFn: fetchTraining });

  const reset = useMutation({
    mutationFn: () => resetTraining(),
    onSuccess: (data: HrTraining) => {
      haptic("success");
      qc.setQueryData(["hr-training"], data);
      void qc.invalidateQueries({ queryKey: ["hr-employee"] });
      setOpenCode(null);
      void showAlert("Курс сброшен — можно пройти заново с первого урока.");
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const complete = useMutation({
    mutationFn: (code: string) => completeTrainingLesson(code),
    onSuccess: (data: HrTraining) => {
      haptic("success");
      qc.setQueryData(["hr-training"], data);
      // Последний урок НЕ закрывает онбординг: сотрудник сам выбирает, учимся
      // дальше вместе или переходим в обычный режим (см. блок ниже).
      void qc.invalidateQueries({ queryKey: ["hr-employee"] });
      if (data.complete) {
        void showAlert("Курс пройден. Осталось выбрать, как продолжим.");
      }
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const lessons = training.data?.lessons ?? [];
  const levels = training.data?.levels ?? [];

  // Внутри уровня незакрытые уроки идут первыми: следующий шаг всегда сверху.
  const byLevel = useMemo(() => {
    const groups = new Map<number, HrTrainingLesson[]>();
    for (const lesson of lessons) {
      const list = groups.get(lesson.level) ?? [];
      list.push(lesson);
      groups.set(lesson.level, list);
    }
    for (const list of groups.values()) {
      list.sort((a, b) => Number(a.done) - Number(b.done));
    }
    return groups;
  }, [lessons]);

  if (training.isError) {
    return <ErrorState error={training.error} onRetry={() => void training.refetch()} />;
  }

  const done = training.data?.complete === true;

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        {onClose && (
          <button
            type="button"
            onClick={() => {
              haptic("light");
              onClose();
            }}
            className="min-h-11 min-w-11 rounded-tile text-lg text-tg-link"
            aria-label="Назад"
          >
            ‹
          </button>
        )}
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-tg-text">Обучение</div>
          <div className="text-xs text-tg-hint">
            Три уровня, по одному действию на экран.
          </div>
        </div>
        {training.data && (
          <span className="rounded-full bg-tg-bg/60 px-2 py-1 text-xs tabular-nums text-tg-hint">
            {training.data.done}/{training.data.total}
          </span>
        )}
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {training.isLoading && (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}

        {training.data && (
          <>
            {training.data.today_training && (
              <section className="rounded-card bg-tg-link/10 p-3">
                <div className="text-sm font-semibold text-tg-text">
                  Сегодня учебная смена
                </div>
                <p className="mt-1 text-xs text-tg-hint">
                  Идём по программе вместе. Обязательные чек-листы и поручения
                  работают как обычно.{" "}
                  {training.data.rate_type === "partial"
                    ? "Ставка частичная."
                    : "Ставка полная."}
                </p>
              </section>
            )}
            {done && onFinish && (
              <section className="rounded-card bg-status-free/10 p-3">
                <div className="text-sm font-semibold text-tg-text">
                  Отлично, первый этап пройден.
                </div>
                <p className="mt-1 text-xs text-tg-hint">
                  Теперь решим, как продолжим в следующую смену.
                </p>
                <div className="mt-3 space-y-2">
                  <button
                    type="button"
                    disabled={finishing}
                    onClick={() => {
                      haptic("medium");
                      onFinish(true);
                    }}
                    className="min-h-11 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
                  >
                    Повторим вместе
                  </button>
                  <button
                    type="button"
                    disabled={finishing}
                    onClick={() => {
                      haptic("light");
                      onFinish(false);
                    }}
                    className="min-h-11 w-full rounded-card bg-tg-secondary-bg text-sm font-medium text-tg-text disabled:opacity-50"
                  >
                    Я уже запомнил
                  </button>
                </div>
                <p className="mt-2 text-xs text-tg-hint">
                  Обязательные чек-листы и поручения остаются в любом режиме.
                </p>
              </section>
            )}

            <div className="rounded-card bg-tg-secondary-bg/60 p-3">
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-tg-bg/60">
                <div
                  className="h-full rounded-full bg-tg-link transition-[width]"
                  style={{ width: `${training.data.percent}%` }}
                  role="progressbar"
                  aria-valuenow={training.data.percent}
                  aria-valuemin={0}
                  aria-valuemax={100}
                />
              </div>
              <div className="mt-2 text-xs text-tg-hint">
                {done
                  ? "Готово. Можно возвращаться к смене."
                  : `Осталось ${training.data.total - training.data.done}. Уроки можно проходить в любом порядке.`}
              </div>
            </div>

            {levels.map((level) => (
              <section key={level.level} className="space-y-2">
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-sm font-semibold text-tg-text">
                    Уровень {level.level} · {level.title}
                  </div>
                  <span className="shrink-0 text-xs tabular-nums text-tg-hint">
                    {level.done}/{level.total}
                  </span>
                </div>
                <p className="text-xs text-tg-hint">{level.hint}</p>
                {(byLevel.get(level.level) ?? []).map((lesson) => (
                  <LessonCard
                    key={lesson.code}
                    lesson={lesson}
                    open={openCode === lesson.code}
                    onToggle={() => {
                      haptic("selection");
                      setOpenCode((cur) => (cur === lesson.code ? null : lesson.code));
                    }}
                    busy={complete.isPending}
                    onComplete={() => complete.mutate(lesson.code)}
                  />
                ))}
              </section>
            ))}

            {/* Сброс доступен всегда: и сотруднику (повторить материал), и
                разработчику (проверить сценарий «как у новичка»). */}
            <section className="rounded-card border border-tg-hint/20 p-3">
              <div className="text-sm font-medium text-tg-text">
                Пройти курс заново
              </div>
              <p className="mt-1 text-xs text-tg-hint">
                Снимет отметки уроков, но оставит подразделение и опыт. Смена,
                задачи и отметки чек-листа не затрагиваются.
              </p>
              <button
                type="button"
                disabled={reset.isPending}
                onClick={async () => {
                  haptic("light");
                  const ok = await showConfirm(
                    "Сбросить прогресс обучения и начать курс заново?",
                  );
                  if (!ok) return;
                  const sure = await showConfirm(
                    "Точно? Отметки уроков будут удалены.",
                  );
                  if (sure) reset.mutate();
                }}
                className="mt-2 min-h-10 w-full rounded-tile bg-tg-secondary-bg text-sm text-tg-text disabled:opacity-50"
              >
                {reset.isPending ? "Сбрасываю…" : "Сбросить прогресс обучения"}
              </button>
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function LessonCard({
  lesson,
  open,
  onToggle,
  onComplete,
  busy,
}: {
  lesson: HrTrainingLesson;
  open: boolean;
  onToggle: () => void;
  onComplete: () => void;
  busy: boolean;
}) {
  return (
    <section
      className={[
        "rounded-card p-3 transition-colors",
        lesson.done ? "bg-status-free/10" : "bg-tg-secondary-bg/60",
      ].join(" ")}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 text-left"
      >
        <span className="text-lg" aria-hidden>
          {lesson.done ? (
            <Icon name="check" size={18} className="text-status-free" />
          ) : (
            lesson.emoji
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-tg-text">
            {lesson.title}
          </span>
          <span className="block text-xs text-tg-hint">
            {lesson.minutes} мин · {lesson.summary}
          </span>
        </span>
        <span className="text-tg-hint" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
      </button>

      {open && (
        <div className="mt-2 space-y-2">
          <ol className="space-y-1.5">
            {lesson.steps.map((step, index) => (
              <li key={step} className="flex gap-2 text-xs text-tg-text">
                <span className="text-tg-hint tabular-nums">{index + 1}.</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
          {!lesson.done ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                haptic("medium");
                onComplete();
              }}
              className="min-h-10 w-full rounded-tile bg-tg-button text-xs font-medium text-tg-button-text disabled:opacity-50"
            >
              Понятно, отметил
            </button>
          ) : (
            <div className="text-xs text-status-free">Пройдено</div>
          )}
        </div>
      )}
    </section>
  );
}
