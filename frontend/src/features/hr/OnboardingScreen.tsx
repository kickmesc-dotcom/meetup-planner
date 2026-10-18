import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchDepartments,
  fetchTraining,
  submitOnboarding,
  type HrEmployee,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import ErrorState from "@/components/ErrorState";
import ThemeSwitcher from "@/components/ThemeSwitcher";
import TrainingScreen from "@/features/hr/TrainingScreen";
import { useUI } from "@/store/ui";
import { haptic, showAlert } from "@/tg/webapp";

/**
 * Первый экран нового сотрудника: «Привет! Давай освоимся».
 *
 * Намеренно короткий сценарий из трёх шагов и без стен текста:
 *  1. подтвердить, кто ты (имя уже известно из Telegram);
 *  2. выбрать подразделение;
 *  3. ответить, есть ли опыт.
 *
 * После этого — короткое знакомство с приложением (уроки) и сразу рабочая
 * смена. «Я уже запомнил» закрывает обучение, но не отменяет рабочие
 * чек-листы, поручения и требования безопасности.
 */
export default function OnboardingScreen({ employee }: { employee: HrEmployee }) {
  const qc = useQueryClient();
  const setTab = useUI((s) => s.setTab);
  const departmentsQ = useQuery({ queryKey: ["departments"], queryFn: fetchDepartments });
  const trainingQ = useQuery({ queryKey: ["hr-training"], queryFn: fetchTraining });

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

  const finish = useMutation({
    mutationFn: () => submitOnboarding({ finish: true }),
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
  const trainingDone = trainingQ.data?.complete === true;

  if (departmentsQ.isError) {
    return (
      <ErrorState
        error={departmentsQ.error}
        onRetry={() => void departmentsQ.refetch()}
        title="Не загрузилось"
      />
    );
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-[560px] flex-col bg-tg-bg">
      <header className="flex items-center justify-between px-5 pb-2 pt-4">
        <span className="text-[11px] text-tg-hint">
          {step < 3 ? `Шаг ${step + 1} из 3` : "Знакомство"}
        </span>
        <ThemeSwitcher />
      </header>

      <div className="flex-1 overflow-y-auto px-5 pb-6">
        {step === 0 && (
          <section className="pt-10">
            <div className="text-4xl" aria-hidden>
              👋
            </div>
            <h1 className="mt-4 text-2xl font-semibold text-tg-text">
              Привет, {employee.display_name.split(" ")[0]}!
            </h1>
            <p className="mt-2 text-sm text-tg-hint">
              Пара шагов — и можно начинать смену.
            </p>
            <button
              type="button"
              onClick={() => {
                haptic("light");
                setStep(1);
              }}
              className="mt-8 min-h-12 w-full rounded-xl bg-tg-button text-sm font-medium text-tg-button-text"
            >
              Начать
            </button>
          </section>
        )}

        {step === 1 && (
          <section className="pt-6">
            <h1 className="text-xl font-semibold text-tg-text">Где ты работаешь?</h1>
            <p className="mt-1 text-sm text-tg-hint">
              От этого зависят чек-лист смены и задачи.
            </p>
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
                      "min-h-14 rounded-xl px-3 text-left text-sm transition-colors",
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
              className="mt-6 min-h-12 w-full rounded-xl bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
            >
              {save.isPending ? "Сохраняем…" : "Продолжить"}
            </button>
          </section>
        )}

        {step === 2 && (
          <section className="pt-6">
            <h1 className="text-xl font-semibold text-tg-text">Как давно ты в деле?</h1>
            <div className="mt-4 space-y-2">
              {(
                [
                  { value: "new" as const, title: "Я только начинаю", hint: "Покажем всё по шагам" },
                  {
                    value: "experienced" as const,
                    title: "Уже освоился",
                    hint: "Сразу к работе",
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
                      "w-full rounded-xl p-3 text-left transition-colors",
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
              className="mt-6 min-h-12 w-full rounded-xl bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
            >
              {save.isPending ? "Сохраняем…" : "Продолжить"}
            </button>
          </section>
        )}

        {step === 3 && (
          <section className="-mx-5 flex min-h-0 flex-col">
            <div className="px-5 pb-2">
              <h1 className="text-xl font-semibold text-tg-text">Освоимся за пару минут</h1>
              <p className="mt-1 text-sm text-tg-hint">
                {department ? `${department.emoji ?? ""} ${department.name} · ` : ""}
                короткое знакомство с приложением.
              </p>
            </div>
            <div className="min-h-[320px] flex-1">
              <TrainingScreen />
            </div>
            <div className="space-y-2 px-5 pt-3">
              <button
                type="button"
                disabled={finish.isPending}
                onClick={() => finish.mutate()}
                className="min-h-12 w-full rounded-xl bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
              >
                {trainingDone ? "Начать смену" : "Я уже запомнил"}
              </button>
              {!trainingDone && (
                <p className="pb-2 text-center text-[11px] text-tg-hint">
                  Обязательные чек-листы и задачи это не отменяет.
                </p>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
