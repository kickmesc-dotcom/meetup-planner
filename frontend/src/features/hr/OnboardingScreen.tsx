import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchDepartments, submitOnboarding, type HrEmployee } from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import ErrorState from "@/components/ErrorState";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import Icon, { type IconName } from "@/components/Icon";
import TrainingScreen from "@/features/hr/TrainingScreen";
import { useUI } from "@/store/ui";
import { haptic, showAlert } from "@/tg/webapp";
import { useTx } from "@/i18n";

/**
 * Три вещи, которые ждут новичка в первую смену.
 *
 * Тексты держим таблицей, а оборачиваем в `tx(...)` на месте показа — как
 * `MyTasksScreen` со своими статусами: словарь перевода видит литералы
 * `tx("…")`, а не константы. Иконки вместо эмодзи — правило `emoji.guard`.
 */
const FIRST_DAY_STEPS: readonly {
  icon: IconName;
  title: string;
  hint: string;
}[] = [
  {
    icon: "checklist",
    title: "Чек-лист смены",
    hint: "Отмечаешь пункты по одному — по мере того, как сделал.",
  },
  {
    icon: "tasks",
    title: "Поручения",
    hint: "Если руководитель что-то поручит, оно придёт сюда и напомнит о сроке.",
  },
  {
    icon: "clock",
    title: "Закрытие смены",
    hint: "В конце дня приложение попросит закрыть смену.",
  },
];

/**
 * Первый экран нового сотрудника: «Привет! Давай освоимся».
 *
 * Намеренно короткий сценарий из трёх шагов и без стен текста:
 *  1. подтвердить, кто ты (имя уже известно из Telegram);
 *  2. выбрать подразделение;
 *  3. ответить, есть ли опыт.
 *
 * Дальше — не курс, а один экран «Первая смена»: три вещи, которые сегодня
 * спросит приложение, и кнопка «Открыть смену». Репетиция первого запуска
 * показала, почему так: на этапе обучения новичок видел список из семи уроков,
 * счётчик «0/7» и кнопку «Сбросить прогресс обучения» — и справедливо решал,
 * что от него требуют что-то уже знать. Курс никуда не делся: он открывается
 * по кнопке «Хочу посмотреть, как всё устроено» и из профиля, то есть по
 * желанию, а не стеной на входе. Обязательные чек-листы и поручения обучение не
 * отменяет — оно лишь показывает, как их закрывать.
 */
export default function OnboardingScreen({ employee }: { employee: HrEmployee }) {
  const { tx } = useTx();
  const qc = useQueryClient();
  const setTab = useUI((s) => s.setTab);
  const departmentsQ = useQuery({ queryKey: ["departments"], queryFn: fetchDepartments });
  // Курс открывается по кнопке: держим выбор в состоянии экрана, а не в
  // URL — знакомство прерывать некуда, это один проход.
  const [showCourse, setShowCourse] = useState(false);

  const initialStep = useMemo(() => {
    if (employee.onboarding_state === "training") return 3;
    if (employee.onboarding_state === "department") return 1;
    if (employee.onboarding_state === "experience") return 2;
    return 0;
  }, [employee.onboarding_state]);

  const [step, setStep] = useState(initialStep);
  const [departmentId, setDepartmentId] = useState<number | null>(
    employee.department_id,
  );
  const [experience, setExperience] = useState<"new" | "experienced" | null>(
    employee.experience,
  );

  const save = useMutation({
    mutationFn: submitOnboarding,
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["hr-employee"], data);
      void qc.invalidateQueries({ queryKey: ["hr-training"] });
    },
    onError: (error) => {
      haptic("error");
      void showAlert(humanizeApiError(error));
    },
  });

  // Закрыть знакомство и уйти на смену. Режим обучения не трогаем: его
  // выбирают в профиле («Обучение в сменах»), а на первом экране этот выбор
  // был бы вопросом без контекста. Курс, если его открыли, передаёт `true`
  // («повторим вместе») или `false` («я уже запомнил») сам.
  const finish = useMutation({
    mutationFn: (learningMode?: boolean) =>
      submitOnboarding(
        learningMode === undefined
          ? { finish: true }
          : { finish: true, learning_mode: learningMode },
      ),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["hr-employee"], data);
      void qc.invalidateQueries();
      setTab("checklist");
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const departments = departmentsQ.data ?? [];
  const department = departments.find((d) => d.id === departmentId);

  if (departmentsQ.isError) {
    return (
      <ErrorState
        error={departmentsQ.error}
        onRetry={() => void departmentsQ.refetch()}
        title={tx("Не загрузилось")}
      />
    );
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-[560px] flex-col bg-tg-bg">
      <header className="flex items-center justify-between px-5 pb-2 pt-4">
        <span className="text-xs text-tg-hint">
          {step < 3
            ? tx("Шаг {step} из {total}", { step: step + 1, total: 3 })
            : tx("Первый день")}
        </span>
        <ThemeSwitcher />
      </header>

      <div className="flex-1 overflow-y-auto px-5 pb-6">
        {step === 0 && (
          <section className="pt-10">
            <h1 className="mt-4 text-2xl font-semibold text-tg-text">
              Привет, {employee.display_name.split(" ")[0]}!
            </h1>
            <p className="mt-2 text-sm text-tg-hint">{tx("Пара шагов — и можно начинать смену.")}</p>
            <button
              type="button"
              onClick={() => {
                haptic("light");
                setStep(1);
              }}
              className="mt-8 min-h-12 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text"
            >{tx("Начать")}</button>
          </section>
        )}

        {step === 1 && (
          <section className="pt-6">
            <h1 className="text-xl font-semibold text-tg-text">{tx("Где ты работаешь?")}</h1>
            <p className="mt-1 text-sm text-tg-hint">{tx("От этого зависят чек-лист смены и задачи.")}</p>
            <div className="mt-4 grid grid-cols-2 gap-2">
              {departments.map((item) => {
                const active = departmentId === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => {
                      haptic("selection");
                      setDepartmentId(item.id);
                    }}
                    className={[
                      "min-h-14 rounded-card px-3 text-left text-sm transition-colors",
                      active
                        ? "bg-tg-button text-tg-button-text"
                        : "bg-tg-secondary-bg text-tg-text",
                    ].join(" ")}
                  >
                    <span className="mr-1" aria-hidden>
                      {item.emoji ?? "•"}
                    </span>
                    {item.name}
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              disabled={departmentId === null || save.isPending}
              onClick={() =>
                save.mutate(
                  { department_id: departmentId },
                  { onSuccess: () => setStep(2) },
                )
              }
              className="mt-6 min-h-12 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
            >
              {save.isPending ? tx("Сохраняем…") : tx("Продолжить")}
            </button>
          </section>
        )}

        {step === 2 && (
          <section className="pt-6">
            <h1 className="text-xl font-semibold text-tg-text">{tx("Как давно ты в деле?")}</h1>
            <div className="mt-4 space-y-2">
              {(
                [
                  {
                    value: "new" as const,
                    title: tx("Я только начинаю"),
                    hint: tx("Покажем всё по шагам"),
                  },
                  {
                    value: "experienced" as const,
                    title: tx("Уже освоился"),
                    hint: tx("Сразу к работе"),
                  },
                ]
              ).map((option) => {
                const active = experience === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={active}
                    onClick={() => {
                      haptic("selection");
                      setExperience(option.value);
                    }}
                    className={[
                      "w-full rounded-card p-3 text-left transition-colors",
                      active ? "bg-tg-button text-tg-button-text" : "bg-tg-secondary-bg",
                    ].join(" ")}
                  >
                    <div className="text-sm font-medium">{option.title}</div>
                    <div className={active ? "text-xs opacity-80" : "text-xs text-tg-hint"}>
                      {option.hint}
                    </div>
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              disabled={experience === null || save.isPending}
              onClick={() =>
                save.mutate(
                  { department_id: departmentId, experience },
                  { onSuccess: () => setStep(3) },
                )
              }
              className="mt-6 min-h-12 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
            >
              {save.isPending ? tx("Сохраняем…") : tx("Продолжить")}
            </button>
          </section>
        )}

        {step === 3 &&
          (showCourse ? (
            <section className="-mx-5 flex min-h-0 flex-col">
              <div className="px-5 pb-2">
                <h1 className="text-xl font-semibold text-tg-text">{tx("Как устроено приложение")}</h1>
                <p className="mt-1 text-sm text-tg-hint">
                  {tx("Короткие уроки — по одному действию на экран. Можно прервать.")}
                </p>
              </div>
              <div className="min-h-[320px] flex-1">
                <TrainingScreen
                  onFinish={(learningMode) => finish.mutate(learningMode)}
                  finishing={finish.isPending}
                />
              </div>
            </section>
          ) : (
            <section className="pt-4">
              <h1 className="text-2xl font-semibold text-tg-text">
                {tx("Первая смена")}
              </h1>
              <p className="mt-2 text-sm text-tg-hint">
                {department ? `${department.emoji ?? ""} ${department.name} · ` : ""}
                {tx("Вот что будет сегодня.")}
              </p>
              <ul className="mt-6 space-y-3">
                {FIRST_DAY_STEPS.map((item) => (
                  <li
                    key={item.title}
                    className="flex gap-3 rounded-card bg-tg-secondary-bg p-4"
                  >
                    <Icon name={item.icon} size={20} className="shrink-0 text-tg-link" />
                    <div>
                      <div className="text-sm font-medium text-tg-text">
                        {tx(item.title)}
                      </div>
                      <div className="mt-1 text-xs text-tg-hint">{tx(item.hint)}</div>
                    </div>
                  </li>
                ))}
              </ul>
              <div className="mt-6 space-y-2 pb-2">
                <button
                  type="button"
                  disabled={finish.isPending}
                  onClick={() => finish.mutate(undefined)}
                  className="min-h-12 w-full rounded-card bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
                >
                  {finish.isPending ? tx("Открываем…") : tx("Открыть смену")}
                </button>
                <button
                  type="button"
                  disabled={finish.isPending}
                  onClick={() => {
                    haptic("light");
                    setShowCourse(true);
                  }}
                  className="min-h-11 w-full rounded-card bg-tg-secondary-bg text-sm text-tg-text disabled:opacity-50"
                >
                  {tx("Хочу посмотреть, как всё устроено")}
                </button>
              </div>
            </section>
          ))}
      </div>
    </div>
  );
}
