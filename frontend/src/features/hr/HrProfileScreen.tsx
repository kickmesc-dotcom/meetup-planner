import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchDepartments,
  fetchEmployee,
  fetchTraining,
  submitOnboarding,
  switchMyRole,
  type HrEmployee,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import ErrorState from "@/components/ErrorState";
import { CardSkeleton } from "@/components/Skeleton";
import AchievementsCard from "@/features/hr/AchievementsCard";
import Badge from "@/features/hr/Badge";
import FeedbackScreen from "@/features/hr/FeedbackScreen";
import HrDemoPanel from "@/features/hr/HrDemoPanel";
import KpiCard from "@/features/hr/KpiCard";
import TrainingScreen from "@/features/hr/TrainingScreen";
import { useUI } from "@/store/ui";
import { haptic, showAlert, WebApp } from "@/tg/webapp";

/**
 * SemiTaskBot: «Профиль».
 *
 * Две задачи экрана:
 *  1. закончить знакомство, если оно оборвалось в чате (бот спрашивает
 *     подразделение и опыт — здесь те же два шага, чтобы человек не застревал);
 *  2. показать, кем он числится в системе: роль видна честно, потому что от неё
 *     зависит, что он видит в ленте и какие кнопки у него есть.
 */
const ROLE_LABEL: Record<HrEmployee["role"], string> = {
  employee: "Сотрудник",
  aup: "Руководитель",
  admin: "Администратор",
};

const ROLE_HINT: Record<HrEmployee["role"], string> = {
  employee: "В событиях смены видны только твои действия.",
  aup: "В событиях смены видны действия твоего подразделения.",
  admin: "В событиях смены видно всё, с фильтрами по людям и подразделениям.",
};

export default function HrProfileScreen() {
  const qc = useQueryClient();
  const setTab = useUI((s) => s.setTab);
  const meQ = useQuery({ queryKey: ["hr-employee"], queryFn: fetchEmployee });
  const depsQ = useQuery({
    queryKey: ["hr-departments"],
    queryFn: fetchDepartments,
  });

  const [departmentId, setDepartmentId] = useState<number | null>(null);
  const [experience, setExperience] = useState<"new" | "experienced" | null>(
    null,
  );
  // Опрос живёт оверлеем поверх вкладок: он нужен раз в смену и не стоит
  // отдельной кнопки в нижней полосе.
  const [showFeedback, setShowFeedback] = useState(false);
  // Тестовый пул `[BOT]` — админский экран: показываем только администратору.
  const [showDemo, setShowDemo] = useState(false);
  // Обучение — этап онбординга и всегда доступный справочник.
  const [showTraining, setShowTraining] = useState(false);
  const trainingQ = useQuery({ queryKey: ["hr-training"], queryFn: fetchTraining });
  // Админ может примерить любую роль, не теряя кабинет (`is_staff`).
  const roleSwitch = useMutation({
    mutationFn: (role: HrEmployee["role"]) => switchMyRole(role),
    onSuccess: () => {
      haptic("success");
      void qc.invalidateQueries({ queryKey: ["hr-employee"] });
      void qc.invalidateQueries({ queryKey: ["me"] });
      void qc.invalidateQueries({ queryKey: ["hr-dashboard"] });
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });

  const save = useMutation({
    mutationFn: (body: {
      department_id?: number | null;
      experience?: "new" | "experienced" | null;
    }) => submitOnboarding(body),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["hr-employee"], data);
      void showAlert(
        data.onboarding_state === "done"
          ? "Профиль готов. Смена начнётся с чек-листа."
          : "Сохранили — остался один шаг.",
      );
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  if (meQ.isError)
    return <ErrorState error={meQ.error} onRetry={() => void meQ.refetch()} />;

  if (meQ.isLoading || !meQ.data) {
    return (
      <div className="flex-1 space-y-3 p-4">
        <CardSkeleton />
        <CardSkeleton />
      </div>
    );
  }

  const me = meQ.data;
  const onboarding = me.onboarding_state !== "done";
  const pickedDept = departmentId ?? me.department_id;
  const deps = depsQ.data ?? [];

  return (
    <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="flex items-center gap-3">
          <div
            className="flex h-12 w-12 items-center justify-center rounded-full bg-tg-bg/60 text-xl"
            aria-hidden
          >
            👷
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate text-base font-semibold text-tg-text">
                {me.display_name}
              </span>
              <Badge text={me.badge} emoji={me.badge_emoji} demo={me.is_demo} />
            </div>
            <div className="text-xs text-tg-hint">
              {ROLE_LABEL[me.role]}
              {me.position ? ` · ${me.position}` : ""}
            </div>
          </div>
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
          <Info
            label="Подразделение"
            value={me.department_name ?? "не выбрано"}
          />
          <Info
            label="Опыт"
            value={
              me.experience === "new"
                ? "новичок"
                : me.experience === "experienced"
                  ? "с опытом"
                  : "не указан"
            }
          />
        </div>
        <p className="mt-2 rounded-lg bg-tg-bg/50 p-2 text-[11px] text-tg-hint">
          {ROLE_HINT[me.role]}
        </p>
      </section>

      {/* Опыт за работу: открыт всем — это мотивация, а не надзор. */}
      <KpiCard />

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-tg-text">🎓 Обучение</h2>
          <span className="text-[11px] tabular-nums text-tg-hint">
            {trainingQ.data
              ? `${trainingQ.data.done}/${trainingQ.data.total}`
              : "…"}
          </span>
        </div>
        <p className="mt-1 text-[11px] text-tg-hint">
          Семь коротких уроков: чек-лист, фотоотчёт, проблемы, уведомления.
          Проходить можно в любом порядке.
        </p>
        <button
          type="button"
          onClick={() => {
            haptic("light");
            setShowTraining(true);
          }}
          className="mt-2 min-h-10 w-full rounded-lg bg-tg-button text-xs font-medium text-tg-button-text"
        >
          {trainingQ.data?.complete
            ? "Открыть курс"
            : trainingQ.data
              ? `Продолжить (${
                  trainingQ.data.lessons.find((l) => !l.done)?.title ?? "курс"
                })`
              : "Открыть курс"}
        </button>
      </section>

      {(me.is_admin || me.is_staff) && (
        <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
          <h2 className="text-sm font-semibold text-tg-text">Примерить роль</h2>
          <p className="mt-1 text-[11px] text-tg-hint">
            Роль меняет только твой обзор: задачи, ленту и кабинет. Доступ в
            админку остаётся — вернуть себя можно этой же кнопкой.
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {([
              { v: "employee", label: "Сотрудник" },
              { v: "aup", label: "Руководитель" },
              { v: "admin", label: "Администратор" },
            ] as const).map((option) => {
              const active = me.role === option.v;
              return (
                <button
                  key={option.v}
                  type="button"
                  aria-pressed={active}
                  disabled={roleSwitch.isPending || active}
                  onClick={() => roleSwitch.mutate(option.v)}
                  className={[
                    "min-h-9 rounded-full px-3 text-xs transition-colors disabled:opacity-60",
                    active
                      ? "bg-tg-button text-tg-button-text"
                      : "bg-tg-bg/60 text-tg-text",
                  ].join(" ")}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
        </section>
      )}

      {/* Скрытый личный прогресс: сервер сам решает, показывать ли блок
          (сейчас — руководителю и админу), см. `AchievementsCard`. */}
      <AchievementsCard />

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <h2 className="text-sm font-semibold text-tg-text">
          {onboarding ? "Закончим знакомство" : "Мои данные"}
        </h2>
        <p className="mt-1 text-[11px] text-tg-hint">
          Подразделение определяет чек-листы, поручения и ссылки, которые тебе
          приходят.
        </p>

        <div className="mt-2 flex flex-wrap gap-1.5">
          {depsQ.isLoading && (
            <div className="text-xs text-tg-hint">Загружаем…</div>
          )}
          {deps.map((d) => {
            const active = pickedDept === d.id;
            return (
              <button
                key={d.id}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  haptic("selection");
                  setDepartmentId(d.id);
                }}
                className={[
                  "min-h-9 rounded-full px-3 text-xs transition-colors",
                  active
                    ? "bg-tg-button text-tg-button-text"
                    : "bg-tg-bg/60 text-tg-text",
                ].join(" ")}
              >
                {d.emoji ? `${d.emoji} ` : ""}
                {d.name}
              </button>
            );
          })}
        </div>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {[
            { v: "new" as const, label: "Я новичок" },
            { v: "experienced" as const, label: "У меня есть опыт" },
          ].map((o) => {
            const active = (experience ?? me.experience) === o.v;
            return (
              <button
                key={o.v}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  haptic("selection");
                  setExperience(o.v);
                }}
                className={[
                  "min-h-9 rounded-full px-3 text-xs transition-colors",
                  active
                    ? "bg-tg-button text-tg-button-text"
                    : "bg-tg-bg/60 text-tg-text",
                ].join(" ")}
              >
                {o.label}
              </button>
            );
          })}
        </div>

        <button
          type="button"
          disabled={save.isPending || (!pickedDept && !experience)}
          onClick={() =>
            save.mutate({
              department_id: pickedDept,
              experience: experience ?? me.experience,
            })
          }
          className="mt-3 min-h-11 w-full rounded-lg bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
        >
          {onboarding ? "Продолжить" : "Сохранить"}
        </button>
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <h2 className="text-sm font-semibold text-tg-text">Быстрые переходы</h2>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <Jump icon="✅" label="Мои задачи" onClick={() => setTab("tasks")} />
          <Jump
            icon="🕒"
            label="Чек-лист смены"
            onClick={() => setTab("checklist")}
          />
          <Jump
            icon="📋"
            label="События смены"
            onClick={() => setTab("feed")}
          />
          <Jump icon="🔗" label="Ссылки" onClick={() => setTab("links")} />
          <Jump
            icon="🛠"
            label="Журнал проблем"
            onClick={() => setTab("issues")}
          />
          <Jump
            icon="🌙"
            label="Передача смены"
            onClick={() => setTab("handovers")}
          />
          <Jump
            icon="📚"
            label="Стандарты"
            onClick={() => setTab("standards")}
          />
          {(me.is_aup || me.is_staff) && (
            <>
              <Jump
                icon="🔍"
                label="Приёмка"
                onClick={() => setTab("review")}
              />
              <Jump
                icon="📊"
                label="Отчёт смены"
                onClick={() => setTab("reports")}
              />
            </>
          )}
          <Jump
            icon="📝"
            label="Обратная связь"
            onClick={() => setShowFeedback(true)}
          />
          {/* Календарь-график и встречи не удалены: из нижней полосы они убраны,
              чтобы подписи оставались читаемыми, но вход сохранён. */}
          <Jump icon="📅" label="График" onClick={() => setTab("calendar")} />
          <Jump icon="🤝" label="Встречи" onClick={() => setTab("meetings")} />
          {(me.is_aup || me.is_staff) && (
            <Jump icon="👀" label="Команда" onClick={() => setTab("team")} />
          )}
          {me.is_admin && (
            <Jump
              icon="🧪"
              label="Тестовый пул"
              onClick={() => setShowDemo(true)}
            />
          )}
        </div>
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <h2 className="text-sm font-semibold text-tg-text">Пиши боту в чат</h2>
        <p className="mt-1 text-[11px] text-tg-hint">
          Фотоотчёты и «не успеваю» принимает бот в чате: там же кнопки «📷
          Фотоотчёт», «📝 Обратная связь» и «ℹ️ Помощь».
        </p>
        <button
          type="button"
          onClick={() => {
            haptic("light");
            const app = WebApp as unknown as { close?: () => void };
            app.close?.();
          }}
          className="mt-2 min-h-10 w-full rounded-lg bg-tg-bg/60 text-xs font-medium text-tg-text"
        >
          Вернуться в чат с ботом
        </button>
      </section>

      {showDemo && <HrDemoPanel onClose={() => setShowDemo(false)} />}

      {showFeedback && (
        <FeedbackScreen onClose={() => setShowFeedback(false)} />
      )}

      {showTraining && (
        <div className="fixed inset-0 z-40 mx-auto flex w-full max-w-[560px] bg-tg-bg">
          <TrainingScreen onClose={() => setShowTraining(false)} />
        </div>
      )}
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-tg-bg/50 p-2">
      <div className="text-tg-hint">{label}</div>
      <div className="text-tg-text">{value}</div>
    </div>
  );
}

function Jump({
  icon,
  label,
  onClick,
}: {
  icon: string;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={() => {
        haptic("light");
        onClick();
      }}
      className="flex min-h-11 items-center gap-2 rounded-lg bg-tg-bg/60 px-3 text-xs text-tg-text active:scale-[0.98] transition-transform"
    >
      <span aria-hidden>{icon}</span>
      <span className="truncate">{label}</span>
    </button>
  );
}
