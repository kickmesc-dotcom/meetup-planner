import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  fetchFeedbackQuestions,
  submitFeedback,
  type HrFeedbackAnswer,
  type HrFeedbackQuestion,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import ErrorState from "@/components/ErrorState";
import { CardSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";

/**
 * SemiTaskBot: «Обратная связь» после смены.
 *
 * Вопросы приходят от администратора (шкала 1–5, выбор варианта, свободный
 * текст), поэтому экран ничего не знает про их содержимое. Отправка одной
 * пачкой; частично заполненный опрос не ломается — незаполненные ответы просто
 * не уходят, а сервер сам проверяет обязательные.
 */
export default function FeedbackScreen({ onClose }: { onClose: () => void }) {
  const q = useQuery({
    queryKey: ["hr-feedback-questions"],
    queryFn: fetchFeedbackQuestions,
  });
  const [answers, setAnswers] = useState<Record<number, HrFeedbackAnswer>>({});
  const [sent, setSent] = useState(false);

  const send = useMutation({
    mutationFn: () => submitFeedback({ answers: Object.values(answers) }),
    onSuccess: () => {
      haptic("success");
      setSent(true);
      void showAlert("Спасибо! Ответы ушли руководителю.");
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const set = (q2: HrFeedbackQuestion, patch: Partial<HrFeedbackAnswer>) =>
    setAnswers((prev) => ({
      ...prev,
      [q2.id]: {
        ...prev[q2.id],
        ...patch,
        question_id: q2.id,
      },
    }));

  return (
    <div className="absolute inset-0 z-30 flex flex-col bg-tg-bg">
      <header className="flex items-center gap-3 border-b border-tg-secondary-bg py-3 pl-4 pr-3">
        <div className="min-w-0 flex-1">
          <div className="text-base font-medium text-tg-text">
            📝 Обратная связь
          </div>
          <div className="text-xs text-tg-hint">Как прошла смена</div>
        </div>
        <button
          type="button"
          onClick={() => {
            haptic("light");
            onClose();
          }}
          className="min-h-9 rounded-tile bg-tg-secondary-bg px-3 text-xs text-tg-text"
        >
          Закрыть
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {q.isLoading && (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}

        {q.isError && (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        )}

        {sent && (
          <div className="rounded-card bg-status-free/10 p-3 text-center text-sm text-status-free">
            ✓ Ответы отправлены
          </div>
        )}

        {q.data?.length === 0 && (
          <div className="rounded-card bg-tg-secondary-bg/60 p-3 text-center text-xs text-tg-hint">
            Вопросов пока нет — администратор их ещё не завёл.
          </div>
        )}

        {q.data?.map((question) => (
          <section
            key={question.id}
            className="rounded-card bg-tg-secondary-bg/60 p-3"
          >
            <h2 className="text-sm text-tg-text">{question.text}</h2>

            {question.kind === "scale" && (
              <div className="mt-2 flex gap-1.5">
                {[1, 2, 3, 4, 5].map((v) => {
                  const active = answers[question.id]?.value_scale === v;
                  return (
                    <button
                      key={v}
                      type="button"
                      aria-pressed={active}
                      onClick={() => {
                        haptic("selection");
                        set(question, { value_scale: v });
                      }}
                      className={[
                        "min-h-10 flex-1 rounded-tile text-sm font-medium transition-colors",
                        active
                          ? "bg-tg-button text-tg-button-text"
                          : "bg-tg-bg/60 text-tg-text",
                      ].join(" ")}
                    >
                      {v}
                    </button>
                  );
                })}
              </div>
            )}

            {question.kind === "choice" && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {question.options.map((opt) => {
                  const active = answers[question.id]?.value_choice === opt;
                  return (
                    <button
                      key={opt}
                      type="button"
                      aria-pressed={active}
                      onClick={() => {
                        haptic("selection");
                        set(question, { value_choice: opt });
                      }}
                      className={[
                        "min-h-9 rounded-full px-3 text-xs transition-colors",
                        active
                          ? "bg-tg-button text-tg-button-text"
                          : "bg-tg-bg/60 text-tg-text",
                      ].join(" ")}
                    >
                      {opt}
                    </button>
                  );
                })}
              </div>
            )}

            {question.kind === "text" && (
              <textarea
                rows={3}
                maxLength={2000}
                value={answers[question.id]?.value_text ?? ""}
                onChange={(e) => set(question, { value_text: e.target.value })}
                placeholder="Пара слов своими словами"
                className="mt-2 w-full rounded-tile bg-tg-bg/60 p-2 text-sm text-tg-text"
              />
            )}
          </section>
        ))}

        {q.data && q.data.length > 0 && (
          <button
            type="button"
            disabled={send.isPending || Object.keys(answers).length === 0}
            onClick={() => send.mutate()}
            className="min-h-11 w-full rounded-tile bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
          >
            {send.isPending ? "Отправляем…" : "Отправить"}
          </button>
        )}
      </div>
    </div>
  );
}
