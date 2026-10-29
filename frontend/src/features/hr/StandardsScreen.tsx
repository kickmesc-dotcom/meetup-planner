import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  STANDARD_CATEGORY_LABEL,
  createStandard,
  fetchEmployee,
  fetchStandard,
  fetchStandards,
  submitStandardCheck,
  updateStandard,
  type HrCheckResult,
  type HrStandard,
  type StandardCategory,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import ErrorState from "@/components/ErrorState";
import Icon, { InlineIcon } from "@/components/Icon";
import { CardSkeleton } from "@/components/Skeleton";
import {
  TranslateBlockButton,
  TranslateFailedNotice,
  useBatchTranslate,
} from "@/components/TranslatableBlock";
import { haptic, showAlert } from "@/tg/webapp";
import { useUI } from "@/store/ui";
import { useTx } from "@/i18n";
/**
 * База стандартов: как мы моем руки, подаём блюдо, тушим сковороду.
 *
 * Экран сознательно двухшаговый: сначала список (что вообще есть и что я уже
 * сдал), потом один стандарт с инструкцией и тестом. Тест сдаётся целиком —
 * сервер сверяет ответы и возвращает разбор, поэтому «подсмотреть» ключ в
 * запросе нельзя.
 */
export default function StandardsScreen() {
  const { tx } = useTx();
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
          className="min-h-11 min-w-11 rounded-tile text-lg text-tg-link"
          aria-label={tx("Назад к задачам")}
        >
          ‹
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-sm font-semibold text-tg-text">
            <Icon name="book" size={15} className="shrink-0" />{tx("Стандарты")}</div>
          <div className="text-xs text-tg-hint">{tx("Инструкции и короткие тесты по ним")}</div>
        </div>
        {meQ.data?.is_aup && (
          <button
            type="button"
            onClick={() => {
              haptic("selection");
              setAdding((v) => !v);
            }}
            className="min-h-9 rounded-tile bg-tg-secondary-bg px-3 text-xs text-tg-text"
          >
            {adding ? tx("Отмена") : tx("+ Стандарт")}
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
  const { tx } = useTx();
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
        <Icon name="book" size={34} className="text-tg-hint" />
        <div className="mt-2 text-sm font-medium text-tg-text">{tx("Стандартов пока нет")}</div>
        <div className="mt-1 max-w-[280px] text-xs text-tg-hint">{tx(
          "Руководитель добавит инструкции — здесь появятся они и тесты к ним.",
        )}</div>
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
      <div className="rounded-card bg-tg-secondary-bg/60 p-3">
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-tg-hint">{tx("Сдано стандартов")}</span>
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
          <div className="mt-1.5 text-xs text-tg-hint">
            Попыток: {data.attempts}
          </div>
        )}
      </div>

      {[...groups.entries()].map(([category, items]) => (
        <section key={category}>
          <h2 className="px-1 text-xs uppercase tracking-wide text-tg-hint">
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
                className="flex w-full items-start gap-3 rounded-card bg-tg-secondary-bg/60 p-3 text-left"
              >
                <span className="text-xl leading-none" aria-hidden>
                  {item.emoji ?? <Icon name="book" size={18} />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-start justify-between gap-2">
                    <span className="text-sm font-medium text-tg-text break-words">
                      {item.title}
                    </span>
                    <span
                      className={[
                        "shrink-0 rounded-full px-2 py-0.5 text-xs",
                        item.passed
                          ? "bg-status-free/20 text-status-free"
                          : "bg-tg-bg/70 text-tg-hint",
                      ].join(" ")}
                    >
                      {item.passed ? tx("сдано") : tx("не сдано")}
                    </span>
                  </span>
                  {item.summary && (
                    <span className="mt-0.5 block text-xs text-tg-hint break-words">
                      {item.summary}
                    </span>
                  )}
                  <span className="mt-1 flex flex-wrap gap-x-2 text-xs text-tg-hint">
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
  const { tx } = useTx();
  const qc = useQueryClient();
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [result, setResult] = useState<HrCheckResult | null>(null);
  const meQ = useQuery({ queryKey: ["hr-employee"], queryFn: fetchEmployee });
  const detailQ = useQuery({
    queryKey: ["hr-standard", id],
    queryFn: () => fetchStandard(id),
  });

  // Инструкция и тест — чужие данные: их пишет руководитель по-русски, кодом
  // такое не переводится. Одна кнопка на весь стандарт: заголовок, тело и
  // тест целиком, — а не стрелка у каждого варианта ответа. Хук стоит до
  // раннего возврата, иначе порядок хуков менялся бы между состояниями.
  const standardTexts = [
    detailQ.data?.title ?? "",
    detailQ.data?.body ?? "",
    ...(detailQ.data?.questions ?? []).flatMap((q) => [q.text, ...q.options]),
  ];
  const translate = useBatchTranslate(standardTexts);

  // Обязательность — то, что попадает в отчёт смены; меняется одним тапом.
  const toggleRequired = useMutation({
    mutationFn: (next: boolean) => updateStandard(id, { is_required: next }),
    onSuccess: () => {
      haptic("success");
      void qc.invalidateQueries({ queryKey: ["hr-standard", id] });
      void qc.invalidateQueries({ queryKey: ["hr-standards"] });
      void qc.invalidateQueries({ queryKey: ["hr-shift-report"] });
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
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
          className="min-h-11 min-w-11 rounded-tile text-lg text-tg-link"
          aria-label={tx("Назад к списку")}
        >
          ‹
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-tg-text">
            {standard?.emoji ? `${standard.emoji} ` : ""}
            {standard ? translate.t(standard.title) : tx("Стандарт")}
          </div>
          <div className="text-xs text-tg-hint">
            {standard
              ? tx("{category} · порог {percent}%", {
                  category: tx(STANDARD_CATEGORY_LABEL[standard.category]),
                  percent: standard.pass_percent,
                })
              : "…"}
          </div>
        </div>
        {translate.canTranslate && (
          <TranslateBlockButton
            on={translate.on}
            busy={translate.busy}
            onClick={() => void translate.toggle()}
          />
        )}
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        <TranslateFailedNotice show={translate.failed} />
        {detailQ.isLoading && <CardSkeleton />}

        {standard && (
          <article className="rounded-card bg-tg-secondary-bg/60 p-3">
            <p
              className={[
                "whitespace-pre-wrap break-words text-sm text-tg-text/90",
                translate.t(standard.body) !== standard.body
                  ? "rounded-tile bg-tg-secondary-bg/80 px-1 ring-1 ring-tg-hint/10"
                  : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              {translate.t(standard.body)}
            </p>
          </article>
        )}

        {standard && meQ.data?.is_aup && (
          <button
            type="button"
            disabled={toggleRequired.isPending}
            onClick={() => {
              haptic("light");
              toggleRequired.mutate(!standard.is_required);
            }}
            className={[
              "flex w-full items-center justify-between rounded-card px-3 py-2 text-left text-xs disabled:opacity-50",
              standard.is_required
                ? "bg-status-busy/15 text-status-busy"
                : "bg-tg-secondary-bg/60 text-tg-hint",
            ].join(" ")}
          >
            <span>
              {standard.is_required
                ? tx("Обязательный: не сдавшие попадают в отчёт смены")
                : tx("Сделать обязательным для отчёта смены")}
            </span>
            {standard.is_required && (
              <Icon
                name="check"
                size={16}
                className="ml-2 shrink-0 text-tg-link"
              />
            )}
          </button>
        )}

        {standard && questions.length === 0 && (
          <div className="rounded-card bg-tg-secondary-bg/60 p-3 text-xs text-tg-hint">{tx("Теста к этому стандарту нет — достаточно прочитать инструкцию.")}</div>
        )}

        {questions.map((q, index) => (
          <section key={q.id} className="rounded-card bg-tg-secondary-bg/60 p-3">
            <div className="text-sm font-medium text-tg-text">
              {index + 1}. {translate.t(q.text)}
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
                      "flex w-full items-start gap-2 rounded-tile px-2.5 py-2 text-left text-xs",
                      picked
                        ? wrong
                          ? "bg-status-busy/20 text-tg-text"
                          : "bg-tg-link/20 text-tg-text"
                        : "bg-tg-bg/60 text-tg-text/90",
                    ].join(" ")}
                  >
                    <span className="text-xs text-tg-hint">
                      {String.fromCharCode(1040 + optionIndex)})
                    </span>
                    <span className="min-w-0 flex-1 break-words">
                      {translate.t(option)}
                    </span>
                  </button>
                );
              })}
            </div>
            {result?.wrong_indexes.includes(index) && (
              <div className="mt-1.5 text-xs text-status-busy">{tx("Ответ неверный — вернись к инструкции выше.")}</div>
            )}
          </section>
        ))}

        {result && (
          <div
            className={[
              "rounded-card p-3 text-sm",
              result.passed
                ? "bg-status-free/15 text-status-free"
                : "bg-status-busy/15 text-status-busy",
            ].join(" ")}
          >
            {result.passed ? (
              <>
                <InlineIcon name="check" />{tx("Сдано")}</>
            ) : (
              <>
                <InlineIcon name="close" />{tx("Пока не сдано")}</>
            )}
            : {result.correct} из{" "}
            {result.total} верно ({result.percent}%, нужно {result.pass_percent}%).
            {!result.passed && tx(" Перечитай инструкцию и попробуй снова.")}
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
            className="min-h-11 w-full rounded-tile bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
          >
            {result ? tx("Попробовать снова") : tx("Проверить ответы")}
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
  const { tx } = useTx();
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [category, setCategory] = useState<StandardCategory>("other");
  const [emoji, setEmoji] = useState("");
  const [summary, setSummary] = useState("");
  const [passPercent, setPassPercent] = useState(80);
  // Обязательный стандарт попадает в пробелы отчёта смены — по умолчанию нет.
  const [isRequired, setIsRequired] = useState(false);
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
        is_required: isRequired,
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
    <section className="mb-4 rounded-card bg-tg-secondary-bg/60 p-3">
      <h2 className="text-sm font-semibold text-tg-text">{tx("Новый стандарт")}</h2>
      <p className="mt-0.5 text-xs text-tg-hint">{tx(
        "Пиши как для нового сотрудника: что сделать, в каком порядке и почему.",
      )}</p>

      <label className="mt-3 block text-xs text-tg-hint">{tx("Название")}<input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={200}
          placeholder={tx("Гигиена рук перед сменой")}
          className="mt-1 min-h-10 w-full rounded-tile bg-tg-bg/70 px-2 text-sm text-tg-text"
        />
      </label>

      <div className="mt-2 flex gap-2">
        <label className="w-16 shrink-0 text-xs text-tg-hint">{tx("Значок")}<input
            value={emoji}
            onChange={(e) => setEmoji(e.target.value)}
            maxLength={4}
            placeholder={tx("Значок")}
            className="mt-1 min-h-10 w-full rounded-tile bg-tg-bg/70 px-2 text-center text-sm text-tg-text"
          />
        </label>
        <label className="min-w-0 flex-1 text-xs text-tg-hint">{tx("Категория")}<select
            value={category}
            onChange={(e) => setCategory(e.target.value as StandardCategory)}
            className="mt-1 min-h-10 w-full rounded-tile bg-tg-bg/70 px-2 text-sm text-tg-text"
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

      <label className="mt-2 block text-xs text-tg-hint">{tx("Короткое описание (для списка)")}<input
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          maxLength={200}
          className="mt-1 min-h-10 w-full rounded-tile bg-tg-bg/70 px-2 text-sm text-tg-text"
        />
      </label>

      <label className="mt-2 block text-xs text-tg-hint">{tx("Инструкция")}<textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={5}
          placeholder={tx("1. Помой руки…")}
          className="mt-1 w-full rounded-tile bg-tg-bg/70 p-2 text-sm text-tg-text"
        />
      </label>

      <label className="mt-2 block text-xs text-tg-hint">
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

      <label className="mt-2 flex items-start gap-2 text-xs text-tg-hint">
        <input
          type="checkbox"
          checked={isRequired}
          onChange={(e) => setIsRequired(e.target.checked)}
          className="mt-0.5"
        />
        <span>{tx("Обязательный: не сдавшие попадут в пробелы отчёта смены.")}</span>
      </label>

      <div className="mt-3 space-y-2">
        <div className="text-xs uppercase tracking-wide text-tg-hint">{tx("Тест")}</div>
        {questions.map((q, index) => (
          <div key={index} className="rounded-tile bg-tg-bg/60 p-2">
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
                placeholder={tx("Вопрос {number}", { number: index + 1 })}
                className="min-h-9 min-w-0 flex-1 rounded-tile bg-tg-secondary-bg px-2 text-sm text-tg-text"
              />
              {questions.length > 1 && (
                <button
                  type="button"
                  onClick={() =>
                    setQuestions((prev) => prev.filter((_, i) => i !== index))
                  }
                  className="min-h-11 min-w-11 rounded-tile text-xs text-tg-hint"
                  aria-label={tx("Удалить вопрос")}
                >
                  <Icon name="close" size={14} />
                </button>
              )}
            </div>
            {q.options.map((option, optionIndex) => (
              <label
                key={optionIndex}
                className="mt-1.5 flex items-center gap-2 text-xs text-tg-hint"
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
                  aria-label={tx("Верный вариант")}
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
                    optionIndex === 0 ? tx("Верный вариант") : tx("Вариант")
                  }
                  className="min-h-8 min-w-0 flex-1 rounded-tile bg-tg-secondary-bg px-2 text-xs text-tg-text"
                />
              </label>
            ))}
          </div>
        ))}
        <button
          type="button"
          onClick={() => setQuestions((prev) => [...prev, EMPTY_QUESTION()])}
          className="min-h-9 w-full rounded-tile bg-tg-secondary-bg text-xs text-tg-text"
        >{tx("+ Вопрос")}</button>
      </div>

      <button
        type="button"
        disabled={!canSave}
        onClick={() => save.mutate()}
        className="mt-3 min-h-11 w-full rounded-tile bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
      >{tx("Сохранить стандарт")}</button>
    </section>
  );
}
