import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  STANDARD_CATEGORY_LABEL,
  createStandard,
  fetchEmployee,
  fetchStandard,
  fetchStandards,
  submitStandardCheck,
  type HrCheckResult,
  type HrStandard,
  type StandardCategory,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import ErrorState from "@/components/ErrorState";
import { CardSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";
import { useUI } from "@/store/ui";

/**
 * База стандартов: как мы моем руки, подаём блюдо, тушим сковороду.
 *
 * Экран сознательно двухшаговый: сначала список (что вообще есть и что я уже
 * сдал), потом один стандарт с инструкцией и тестом. Тест сдаётся целиком —
 * сервер сверяет ответы и возвращает разбор, поэтому «подсмотреть» ключ в
 * запросе нельзя.
 */
export default function StandardsScreen() {
  const setTab = useUI((s) => s.setTab);
  const [openId, setOpenId] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const meQ = useQuery({ queryKey: ["hr-employee"], queryFn: fetchEmployee });

  if (openId !== null) {
    return (
      <StandardDetail
        id={openId}
        onBack={() => {
          haptic("light");
          setOpenId(null);
        }}
      />
    );
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        <button
          type="button"
          onClick={() => {
            haptic("light");
            setTab("tasks");
          }}
          className="min-h-9 min-w-9 rounded-lg text-lg text-tg-link"
          aria-label="Назад к задачам"
        >
          ‹
        </button>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-tg-text">📚 Стандарты</div>
          <div className="text-[11px] text-tg-hint">
            Инструкции и короткие тесты по ним
          </div>
        </div>
        {meQ.data?.is_aup && (
          <button
            type="button"
            onClick={() => {
              haptic("selection");
              setAdding((v) => !v);
            }}
            className="min-h-9 rounded-lg bg-tg-secondary-bg px-3 text-xs text-tg-text"
          >
            {adding ? "Отмена" : "+ Стандарт"}
          </button>
        )}
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {adding && <AddStandardForm onDone={() => setAdding(false)} />}
        <StandardsList onOpen={(id) => setOpenId(id)} />
      </div>
    </div>
  );
}

function StandardsList({ onOpen }: { onOpen: (id: number) => void }) {
  const listQ = useQuery({ queryKey: ["hr-standards"], queryFn: fetchStandards });

  if (listQ.isError) {
    return (
      <ErrorState error={listQ.error} onRetry={() => void listQ.refetch()} />
    );
  }
  if (listQ.isLoading) {
    return (
      <div className="space-y-3">
        <CardSkeleton />
        <CardSkeleton />
      </div>
    );
  }

  const data = listQ.data;
  if (!data || data.items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <div className="text-4xl" aria-hidden>
          📚
        </div>
        <div className="mt-2 text-sm font-medium text-tg-text">
          Стандартов пока нет
        </div>
        <div className="mt-1 max-w-[280px] text-xs text-tg-hint">
          Руководитель добавит инструкции — здесь появятся они и тесты к ним.
        </div>
      </div>
    );
  }

  // Группируем по категориям: так список читается как оглавление, а не как
  // свалка карточек.
  const groups = new Map<StandardCategory, HrStandard[]>();
  for (const item of data.items) {
    const bucket = groups.get(item.category) ?? [];
    bucket.push(item);
    groups.set(item.category, bucket);
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-tg-hint">Сдано стандартов</span>
          <span className="font-medium text-tg-text">
            {data.passed} из {data.total}
          </span>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-tg-bg/70">
          <div
            className="h-full rounded-full bg-tg-link"
            style={{
              width: `${data.total ? Math.round((data.passed / data.total) * 100) : 0}%`,
            }}
          />
        </div>
        {data.attempts > 0 && (
          <div className="mt-1.5 text-[11px] text-tg-hint">
            Попыток: {data.attempts}
          </div>
        )}
      </div>

      {[...groups.entries()].map(([category, items]) => (
        <section key={category}>
          <h2 className="px-1 text-[11px] uppercase tracking-wide text-tg-hint">
            {STANDARD_CATEGORY_LABEL[category]}
          </h2>
          <div className="mt-1.5 space-y-2">
            {items.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  haptic("light");
                  onOpen(item.id);
                }}
                className="flex w-full items-start gap-3 rounded-xl bg-tg-secondary-bg/60 p-3 text-left"
              >
                <span className="text-xl leading-none" aria-hidden>
                  {item.emoji ?? "📄"}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-start justify-between gap-2">
                    <span className="text-sm font-medium text-tg-text break-words">
                      {item.title}
                    </span>
                    <span
                      className={[
                        "shrink-0 rounded-full px-2 py-0.5 text-[11px]",
                        item.passed
                          ? "bg-status-free/20 text-status-free"
                          : "bg-tg-bg/70 text-tg-hint",
                      ].join(" ")}
                    >
                      {item.passed ? "сдано" : "не сдано"}
                    </span>
                  </span>
                  {item.summary && (
                    <span className="mt-0.5 block text-[11px] text-tg-hint break-words">
                      {item.summary}
                    </span>
                  )}
                  <span className="mt-1 flex flex-wrap gap-x-2 text-[11px] text-tg-hint">
                    {item.questions_count > 0 && (
                      <span>вопросов: {item.questions_count}</span>
                    )}
                    {item.last_percent !== null && (
                      <span>последняя попытка: {item.last_percent}%</span>
                    )}
                    {item.department_name && (
                      <span>· {item.department_name}</span>
                    )}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function StandardDetail({ id, onBack }: { id: number; onBack: () => void }) {
  const qc = useQueryClient();
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [result, setResult] = useState<HrCheckResult | null>(null);
  const detailQ = useQuery({
    queryKey: ["hr-standard", id],
    queryFn: () => fetchStandard(id),
  });

  const check = useMutation({
    mutationFn: (values: number[]) => submitStandardCheck(id, values),
    onSuccess: (res) => {
      setResult(res);
      haptic(res.passed ? "success" : "error");
      void qc.invalidateQueries({ queryKey: ["hr-standards"] });
      void qc.invalidateQueries({ queryKey: ["hr-standard", id] });
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  if (detailQ.isError) {
    return (
      <ErrorState error={detailQ.error} onRetry={() => void detailQ.refetch()} />
    );
  }

  const standard = detailQ.data;
  const questions = standard?.questions ?? [];
  const allAnswered =
    questions.length > 0 && questions.every((q) => answers[q.id] !== undefined);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-tg-secondary-bg px-3 py-2">
        <button
          type="button"
          onClick={onBack}
          className="min-h-9 min-w-9 rounded-lg text-lg text-tg-link"
          aria-label="Назад к списку"
        >
          ‹
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-tg-text">
            {standard?.emoji ?? "📄"} {standard?.title ?? "Стандарт"}
          </div>
          <div className="text-[11px] text-tg-hint">
            {standard
              ? `${STANDARD_CATEGORY_LABEL[standard.category]} · порог ${standard.pass_percent}%`
              : "…"}
          </div>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        {detailQ.isLoading && <CardSkeleton />}

        {standard && (
          <article className="rounded-xl bg-tg-secondary-bg/60 p-3">
            <p className="whitespace-pre-wrap break-words text-sm text-tg-text/90">
              {standard.body}
            </p>
          </article>
        )}

        {standard && questions.length === 0 && (
          <div className="rounded-xl bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">
            Теста к этому стандарту нет — достаточно прочитать инструкцию.
          </div>
        )}

        {questions.map((q, index) => (
          <section key={q.id} className="rounded-xl bg-tg-secondary-bg/60 p-3">
            <div className="text-sm font-medium text-tg-text">
              {index + 1}. {q.text}
            </div>
            <div className="mt-2 space-y-1.5">
              {q.options.map((option, optionIndex) => {
                const picked = answers[q.id] === optionIndex;
                const wrong =
                  result?.wrong_indexes.includes(index) && picked;
                return (
                  <button
                    key={`${q.id}-${optionIndex}`}
                    type="button"
                    onClick={() => {
                      if (result) return;
                      haptic("selection");
                      setAnswers((prev) => ({ ...prev, [q.id]: optionIndex }));
                    }}
                    className={[
                      "flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left text-xs",
                      picked
                        ? wrong
                          ? "bg-status-busy/20 text-tg-text"
                          : "bg-tg-link/20 text-tg-text"
                        : "bg-tg-bg/60 text-tg-text/90",
                    ].join(" ")}
                  >
                    <span className="text-[11px] text-tg-hint">
                      {String.fromCharCode(1040 + optionIndex)})
                    </span>
                    <span className="min-w-0 flex-1 break-words">{option}</span>
                  </button>
                );
              })}
            </div>
            {result?.wrong_indexes.includes(index) && (
              <div className="mt-1.5 text-[11px] text-status-busy">
                Ответ неверный — вернись к инструкции выше.
              </div>
            )}
          </section>
        ))}

        {result && (
          <div
            className={[
              "rounded-xl p-3 text-sm",
              result.passed
                ? "bg-status-free/15 text-status-free"
                : "bg-status-busy/15 text-status-busy",
            ].join(" ")}
          >
            {result.passed ? "✅ Сдано" : "❌ Пока не сдано"}: {result.correct} из{" "}
            {result.total} верно ({result.percent}%, нужно {result.pass_percent}%).
            {!result.passed && " Перечитай инструкцию и попробуй снова."}
          </div>
        )}

        {questions.length > 0 && (
          <button
            type="button"
            disabled={!allAnswered || check.isPending}
            onClick={() => {
              const values = questions.map((q) => answers[q.id] ?? -1);
              check.mutate(values);
            }}
            className="min-h-11 w-full rounded-lg bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
          >
            {result ? "Попробовать снова" : "Проверить ответы"}
          </button>
        )}
      </div>
    </div>
  );
}

interface DraftQuestion {
  text: string;
  options: [string, string, string, string];
  correct: number;
}

const EMPTY_QUESTION = (): DraftQuestion => ({
  text: "",
  options: ["", "", "", ""],
  correct: 0,
});

function AddStandardForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [category, setCategory] = useState<StandardCategory>("other");
  const [emoji, setEmoji] = useState("");
  const [summary, setSummary] = useState("");
  const [passPercent, setPassPercent] = useState(80);
  const [questions, setQuestions] = useState<DraftQuestion[]>([EMPTY_QUESTION()]);

  const save = useMutation({
    mutationFn: () =>
      createStandard({
        title: title.trim(),
        body: body.trim(),
        category,
        emoji: emoji.trim() || null,
        summary: summary.trim() || null,
        pass_percent: passPercent,
        questions: questions
          .map((q) => ({
            text: q.text.trim(),
            // Пустые варианты не отправляем: сервер требует минимум два, и
            // «третий вариант — пустая строка» это не вариант ответа.
            options: q.options.map((o) => o.trim()).filter(Boolean),
            correct_index: q.correct,
          }))
          .filter((q) => q.text && q.options.length >= 2),
      }),
    onSuccess: () => {
      haptic("success");
      void qc.invalidateQueries({ queryKey: ["hr-standards"] });
      onDone();
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const canSave =
    title.trim().length > 0 &&
    body.trim().length > 0 &&
    !save.isPending &&
    questions.every(
      (q) => !q.text.trim() || q.options.filter((o) => o.trim()).length >= 2,
    );

  return (
    <section className="mb-4 rounded-xl bg-tg-secondary-bg/60 p-3">
      <h2 className="text-sm font-semibold text-tg-text">Новый стандарт</h2>
      <p className="mt-0.5 text-[11px] text-tg-hint">
        Пиши как для нового сотрудника: что сделать, в каком порядке и почему.
      </p>

      <label className="mt-3 block text-[11px] text-tg-hint">
        Название
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={200}
          placeholder="Гигиена рук перед сменой"
          className="mt-1 min-h-10 w-full rounded-lg bg-tg-bg/70 px-2 text-sm text-tg-text"
        />
      </label>

      <div className="mt-2 flex gap-2">
        <label className="w-16 shrink-0 text-[11px] text-tg-hint">
          Значок
          <input
            value={emoji}
            onChange={(e) => setEmoji(e.target.value)}
            maxLength={4}
            placeholder="🧼"
            className="mt-1 min-h-10 w-full rounded-lg bg-tg-bg/70 px-2 text-center text-sm text-tg-text"
          />
        </label>
        <label className="min-w-0 flex-1 text-[11px] text-tg-hint">
          Категория
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value as StandardCategory)}
            className="mt-1 min-h-10 w-full rounded-lg bg-tg-bg/70 px-2 text-sm text-tg-text"
          >
            {(
              Object.keys(STANDARD_CATEGORY_LABEL) as StandardCategory[]
            ).map((key) => (
              <option key={key} value={key}>
                {STANDARD_CATEGORY_LABEL[key]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="mt-2 block text-[11px] text-tg-hint">
        Короткое описание (для списка)
        <input
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          maxLength={200}
          className="mt-1 min-h-10 w-full rounded-lg bg-tg-bg/70 px-2 text-sm text-tg-text"
        />
      </label>

      <label className="mt-2 block text-[11px] text-tg-hint">
        Инструкция
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={5}
          placeholder="1. Помой руки…"
          className="mt-1 w-full rounded-lg bg-tg-bg/70 p-2 text-sm text-tg-text"
        />
      </label>

      <label className="mt-2 block text-[11px] text-tg-hint">
        Порог сдачи: {passPercent}%
        <input
          type="range"
          min={50}
          max={100}
          step={5}
          value={passPercent}
          onChange={(e) => setPassPercent(Number(e.target.value))}
          className="mt-1 w-full"
        />
      </label>

      <div className="mt-3 space-y-2">
        <div className="text-[11px] uppercase tracking-wide text-tg-hint">
          Тест
        </div>
        {questions.map((q, index) => (
          <div key={index} className="rounded-lg bg-tg-bg/60 p-2">
            <div className="flex items-center gap-2">
              <input
                value={q.text}
                onChange={(e) =>
                  setQuestions((prev) =>
                    prev.map((item, i) =>
                      i === index ? { ...item, text: e.target.value } : item,
                    ),
                  )
                }
                placeholder={`Вопрос ${index + 1}`}
                className="min-h-9 min-w-0 flex-1 rounded-lg bg-tg-secondary-bg px-2 text-sm text-tg-text"
              />
              {questions.length > 1 && (
                <button
                  type="button"
                  onClick={() =>
                    setQuestions((prev) => prev.filter((_, i) => i !== index))
                  }
                  className="min-h-9 min-w-9 rounded-lg text-xs text-tg-hint"
                  aria-label="Удалить вопрос"
                >
                  ✕
                </button>
              )}
            </div>
            {q.options.map((option, optionIndex) => (
              <label
                key={optionIndex}
                className="mt-1.5 flex items-center gap-2 text-[11px] text-tg-hint"
              >
                <input
                  type="radio"
                  name={`correct-${index}`}
                  checked={q.correct === optionIndex}
                  onChange={() =>
                    setQuestions((prev) =>
                      prev.map((item, i) =>
                        i === index ? { ...item, correct: optionIndex } : item,
                      ),
                    )
                  }
                  aria-label="Верный вариант"
                />
                <input
                  value={option}
                  onChange={(e) =>
                    setQuestions((prev) =>
                      prev.map((item, i) =>
                        i === index
                          ? {
                              ...item,
                              options: item.options.map((o, oi) =>
                                oi === optionIndex ? e.target.value : o,
                              ) as [string, string, string, string],
                            }
                          : item,
                      ),
                    )
                  }
                  placeholder={
                    optionIndex === 0 ? "Верный вариант" : "Вариант"
                  }
                  className="min-h-8 min-w-0 flex-1 rounded-lg bg-tg-secondary-bg px-2 text-xs text-tg-text"
                />
              </label>
            ))}
          </div>
        ))}
        <button
          type="button"
          onClick={() => setQuestions((prev) => [...prev, EMPTY_QUESTION()])}
          className="min-h-9 w-full rounded-lg bg-tg-secondary-bg text-xs text-tg-text"
        >
          + Вопрос
        </button>
      </div>

      <button
        type="button"
        disabled={!canSave}
        onClick={() => save.mutate()}
        className="mt-3 min-h-11 w-full rounded-lg bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
      >
        Сохранить стандарт
      </button>
    </section>
  );
}
