import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchAdminEmployees,
  fetchDepartments,
  fetchEmployee,
  fetchOrgSetup,
  fetchTraining,
  setProfilePrivacy,
  setProfileVisibility,
  submitOnboarding,
  switchMyRole,
  type HrEmployee,
} from "@/api/hr";
import { startSimulation } from "@/api/simulation";
import { useAppText } from "@/api/texts";
import { useSimulation } from "@/store/simulation";
import { getApiBase, humanizeApiError, setApiBase } from "@/api/client";
import ErrorState from "@/components/ErrorState";
import Icon, { type IconName } from "@/components/Icon";
import { CardSkeleton, Skeleton } from "@/components/Skeleton";
import AchievementsCard from "@/features/hr/AchievementsCard";
import Badge from "@/features/hr/Badge";
import FeedbackScreen from "@/features/hr/FeedbackScreen";
import HrDemoPanel from "@/features/hr/HrDemoPanel";
import OrgSetupScreen from "@/features/hr/OrgSetupScreen";
import EmailVerifyCard from "@/features/hr/EmailVerifyCard";
import KpiCard from "@/features/hr/KpiCard";
import PushCard from "@/features/hr/PushCard";
import TrainingScreen from "@/features/hr/TrainingScreen";
import WebVersionCard from "@/features/hr/WebVersionCard";
import { useUI } from "@/store/ui";
import { haptic, showAlert, WebApp } from "@/tg/webapp";
import { useTx } from "@/i18n";
/**
 * SemiTaskBot: «Профиль».
 *
 * VISUAL_AUDIT P1.7: раньше экран был свалкой из 15 блоков — «кто я», KPI,
 * обучение, «примерить роль», «режим проверки», достижения, «мои данные»,
 * 14 «быстрых переходов» (из них семь дублировали нижнюю полосу), чат с ботом
 * и серверный переключатель. Человек листал профиль дольше, чем работал.
 *
 * Теперь четыре блока по смыслу:
 *  1. «Кто я» — имя, роль, подразделение, опыт; правка данных открывается
 *     кнопкой, а во время знакомства показана сразу;
 *  2. «Опыт и обучение» — KPI, курс и достижения вместе (это одна тема);
 *  3. «Разделы» — один свёрнутый список; то, что уже есть в нижней полосе,
 *     из него убрано, чтобы не было двух входов в одно место;
 *  4. «Для администратора» — примерка роли, режим проверки, тестовый пул и
 *     серверный переключатель, свёрнуто по умолчанию.
 *
 * Ничего не удалено: календарь, встречи, материалы, стандарты, приёмка и
 * отчёты по-прежнему открываются из списка разделов.
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

interface RowItem {
  icon: IconName;
  label: string;
  onSelect: () => void;
}

export default function HrProfileScreen() {
  const { tx } = useTx();
  const qc = useQueryClient();
  const setTab = useUI((s) => s.setTab);
  const photoHint = useAppText(
    "profile.photo.hint",
    "Фотоотчёт можно приложить прямо в пункте чек-листа (камера или галерея), а «не успеваю» — в карточке задачи. Чат с ботом тоже работает.",
  );
  const meQ = useQuery({ queryKey: ["hr-employee"], queryFn: fetchEmployee });
  const depsQ = useQuery({
    queryKey: ["hr-departments"],
    queryFn: fetchDepartments,
  });

  const [departmentId, setDepartmentId] = useState<number | null>(null);
  const [experience, setExperience] = useState<"new" | "experienced" | null>(
    null,
  );
  // Правка «моих данных» по умолчанию открыта только пока знакомство не
  // закончено: это обязательный шаг, его нельзя прятать за кнопку.
  const [editingOverride, setEditingOverride] = useState<boolean | null>(null);
  // Опрос живёт оверлеем поверх вкладок: он нужен раз в смену и не стоит
  // отдельной кнопки в нижней полосе.
  const [showFeedback, setShowFeedback] = useState(false);
  // Тестовый пул `[BOT]` — админский экран: показываем только администратору.
  const [showDemo, setShowDemo] = useState(false);
  // Обучение — этап онбординга и всегда доступный справочник.
  const [showTraining, setShowTraining] = useState(false);
  // Разделы и админ-инструменты свёрнуты: это редкие переходы, а не работа.
  const [showSections, setShowSections] = useState(false);
  const [showAdmin, setShowAdmin] = useState(false);
  const trainingQ = useQuery({ queryKey: ["hr-training"], queryFn: fetchTraining });
  const staff = !!(meQ.data?.is_admin || meQ.data?.is_staff);
  const employeesQ = useQuery({
    queryKey: ["admin-employees"],
    queryFn: fetchAdminEmployees,
    enabled: staff,
  });
  const [simulationTarget, setSimulationTarget] = useState<number | null>(null);
  const [simulationMode, setSimulationMode] = useState<"new" | "as_is">("new");
  const simulationStart = useMutation({
    mutationFn: () =>
      startSimulation(simulationTarget ?? 0, simulationMode),
    onSuccess: (data) => {
      haptic("success");
      useSimulation.getState().start({
        sessionId: data.id,
        subjectName: data.subject_name,
        departmentName: data.department_name,
        mode: data.mode,
      });
      void qc.invalidateQueries();
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });
  // «Профиль открыт»: человек сам решает, видят ли коллеги его активность.
  // Руководитель и админ видят её в любом случае — это написано рядом.
  const visibility = useMutation({
    mutationFn: (isPublic: boolean) => setProfileVisibility(isPublic),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["hr-employee"], data);
      void qc.invalidateQueries({ queryKey: ["hr-feed"] });
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });
  // Две личные галочки: последний заход и последнее медиа. Сервер может
  // отказать в выключении — тогда он вернёт фактическое состояние, и тумблер
  // останется включённым (это не ошибка клиента, а политика руководства).
  const privacy = useMutation({
    mutationFn: (body: { show_last_seen?: boolean; show_last_media?: boolean }) =>
      setProfilePrivacy(body),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["hr-employee"], data);
      void qc.invalidateQueries({ queryKey: ["hr-profile-card"] });
    },
    onError: (error) => void showAlert(humanizeApiError(error)),
  });
  // Мастер организации: вход для руководителя, повторный проход не запрещён.
  const [orgSetupOpen, setOrgSetupOpen] = useState(false);
  const orgSetupQ = useQuery({
    queryKey: ["org-setup"],
    queryFn: fetchOrgSetup,
    enabled: orgSetupOpen,
    staleTime: 60_000,
  });

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

  // Переключатель режима после первого курса: «учимся вместе» или обычный
  // рабочий режим. Включить обучение обратно можно в любой момент — оно
  // сопровождение, а не замена обязанностей.
  const learningMode = useMutation({
    mutationFn: (enabled: boolean) => submitOnboarding({ learning_mode: enabled }),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["hr-employee"], data);
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
      setEditingOverride(false);
      void showAlert(
        data.onboarding_state === "done"
          ? tx("Профиль готов. Смена начнётся с чек-листа.")
          : tx("Сохранили — остался один шаг."),
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
  const editing = editingOverride ?? onboarding;
  const pickedDept = departmentId ?? me.department_id;
  const deps = depsQ.data ?? [];
  // VISUAL_AUDIT P2.15: у управляющего/админа подразделение и опыт могут быть
  // не заданы — «не выбрано» и «не указан» читались как брошенная анкета.
  // Для staff-ролей показываем доступ, а пустые поля опыта не рисуем.
  const staffView = !onboarding && !!(me.is_admin || me.is_staff || me.is_aup);

  // Семь разделов уже есть в нижней полосе (задачи, смена, табель, события,
  // команда, админ). Второй вход в то же место только путал.
  const sections: RowItem[] = [
    // Поиск стоит первым: у нового сотрудника вопрос «где это написано»
    // возникает раньше, чем желание открыть раздел и листать его.
    { icon: "search", label: "Спросить", onSelect: () => setTab("ask") },
    { icon: "book", label: "Материалы смены", onSelect: () => setTab("materials") },
    { icon: "globe", label: "Ссылки", onSelect: () => setTab("links") },
    { icon: "checklist", label: "Стандарты", onSelect: () => setTab("standards") },
    { icon: "alert", label: "Журнал проблем", onSelect: () => setTab("issues") },
    { icon: "send", label: "Передача смены", onSelect: () => setTab("handovers") },
    // «График» — расписание смен; старая сетка участников убрана (план, 13.1).
    { icon: "calendar", label: "График", onSelect: () => setTab("shifts") },
    { icon: "clock", label: "Встречи", onSelect: () => setTab("meetings") },
    { icon: "edit", label: "Обратная связь", onSelect: () => setShowFeedback(true) },
  ];
  if (me.is_aup || me.is_staff) {
    sections.splice(4, 0, {
      icon: "check",
      label: "Приёмка",
      onSelect: () => setTab("review"),
    });
    sections.splice(5, 0, {
      icon: "layout",
      label: "Отчёт смены",
      onSelect: () => setTab("reports"),
    });
  }

  return (
    <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3 lg:grid lg:grid-cols-2 lg:items-start lg:gap-4 lg:space-y-0 lg:px-6 lg:py-5">
      {/* 1. Кто я. */}
      <section
        data-testid="profile-identity"
        className="rounded-card bg-tg-secondary-bg/60 p-3"
      >
        {/* Раунд 5: имя стояло в одной строке с плашкой и кнопкой «Изменить»
            и обрезалось до «Серж-…». Теперь имя — своя строка, ниже плашки
            отдельным рядом, а правка — иконкой справа. */}
        <div className="flex items-start gap-3">
          <div className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-tg-bg/60 text-tg-hint">
            <Icon name="profile" size={26} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="break-words text-base font-semibold leading-tight text-tg-text">
              {me.display_name}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <Badge text={me.badge} emoji={me.badge_emoji} demo={me.is_demo} />
              <span className="rounded-full bg-tg-bg/60 px-2 py-0.5 text-2xs text-tg-hint">
                {tx(ROLE_LABEL[me.role])}
              </span>
            </div>
            {me.position && (
              <div className="mt-1 text-xs text-tg-hint">
                {tx(me.position)}
              </div>
            )}
          </div>
          {!editing && (
            <button
              type="button"
              onClick={() => {
                haptic("light");
                setEditingOverride(true);
              }}
              className="grid min-h-11 min-w-11 shrink-0 place-items-center rounded-tile bg-tg-bg/60 text-tg-link"
              aria-label={tx("Изменить мои данные")}
              title={tx("Изменить")}
            >
              <Icon name="edit" size={18} />
            </button>
          )}
        </div>

        {staffView ? (
          <div className="mt-2 text-xs">
            <Info
              label={tx("Доступ")}
              value={tx(me.department_name ?? "все подразделения")}
            />
          </div>
        ) : (
          <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
            <Info
              label={tx("Подразделение")}
              value={
                me.department_name ??
                tx(onboarding ? "выбери ниже" : "не выбрано")
              }
            />
            <Info
              label={tx("Опыт")}
              value={
                me.experience === "new"
                  ? tx("новичок")
                  : me.experience === "experienced"
                    ? tx("с опытом")
                    : onboarding
                      ? tx("выбери ниже")
                      : tx("не указан")
              }
            />
          </div>
        )}

        <p className="mt-2 text-xs text-tg-hint">{tx(ROLE_HINT[me.role])}</p>

        {/* Видимость профиля — рядом с «кто я», а не в глубине настроек: именно
            здесь человек отвечает на вопрос «что обо мне видят коллеги». */}
        <div className="mt-2 flex items-center gap-2 rounded-tile bg-tg-bg/50 p-2">
          <div className="min-w-0 flex-1">
            <div className="text-xs text-tg-text">
              {me.profile_public ? tx("Профиль открыт") : tx("Профиль закрыт")}
            </div>
            <div className="text-2xs text-tg-hint">
              {me.profile_public
                ? tx("Коллеги видят твою активность и цифры. Руководитель видит их всегда.")
                : tx("Коллеги видят только имя и отдел. Руководитель и админ — всё.")}
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={me.profile_public}
            disabled={visibility.isPending || me.profile_locked}
            onClick={() => visibility.mutate(!me.profile_public)}
            className={[
              "min-h-9 shrink-0 rounded-full px-3 text-xs transition-colors disabled:opacity-60",
              me.profile_public
                ? "bg-tg-button text-tg-button-text"
                : "bg-tg-secondary-bg text-tg-text",
            ].join(" ")}
          >
            {me.profile_locked
              ? tx("Так решили")
              : me.profile_public
                ? tx("Открыт")
                : tx("Закрыт")}
          </button>
        </div>

        {/* Что именно видят коллеги — двумя отдельными пунктами. Раньше это
            было спрятано за одним «профиль открыт», и человек не мог оставить
            историю смены, но убрать отметку «когда заходил». */}
        <div className="mt-2 space-y-1">
          <PrivacyRow
            title={tx("Последний заход")}
            hint={
              me.can_toggle_last_seen
                ? tx("Коллеги видят, когда ты последний раз открывал приложение.")
                : tx("Включено руководителем — выключить нельзя.")
            }
            value={me.show_last_seen}
            locked={!me.can_toggle_last_seen}
            busy={privacy.isPending}
            onToggle={() => privacy.mutate({ show_last_seen: !me.show_last_seen })}
          />
          <PrivacyRow
            title={tx("Последнее медиа")}
            hint={
              me.can_toggle_last_media
                ? tx("Коллеги видят твоё последнее фото из отчёта.")
                : tx("Включено руководителем — выключить нельзя.")
            }
            value={me.show_last_media}
            locked={!me.can_toggle_last_media}
            busy={privacy.isPending}
            onToggle={() => privacy.mutate({ show_last_media: !me.show_last_media })}
          />
        </div>

        {(me.is_aup || me.is_staff) && (
          <button
            type="button"
            onClick={() => {
              haptic("light");
              setOrgSetupOpen(true);
            }}
            className="mt-2 flex min-h-11 w-full items-center gap-2 rounded-tile bg-tg-secondary-bg/60 px-2 text-left text-xs text-tg-text active:bg-tg-bg/60"
          >
            <Icon name="admin" size={16} className="text-tg-hint" />
            <span className="min-w-0 flex-1">
              {tx("Настройка организации")}
              <span className="block text-2xs text-tg-hint">
                {tx("Разделы, подразделения и кто что видит")}
              </span>
            </span>
            <Icon name="chevron" size={14} className="shrink-0 text-tg-hint" />
          </button>
        )}

        {editing && (
          <div className="mt-3 border-t border-tg-hint/10 pt-3">
            <h2 className="text-xs font-medium text-tg-text">
              {onboarding ? tx("Закончим знакомство") : tx("Мои данные")}
            </h2>
            <p className="mt-1 text-xs text-tg-hint">{tx(
              "Подразделение определяет чек-листы, поручения и ссылки, которые тебе приходят.",
            )}</p>

            <div className="mt-2 flex flex-wrap gap-1.5">
              {depsQ.isLoading && (
                <>
                  <Skeleton className="h-8 w-20 rounded-full" />
                  <Skeleton className="h-8 w-20 rounded-full" />
                </>
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
                    {tx(o.label)}
                  </button>
                );
              })}
            </div>

            <div className="mt-3 flex gap-2">
              {!onboarding && (
                <button
                  type="button"
                  onClick={() => {
                    haptic("light");
                    setDepartmentId(null);
                    setExperience(null);
                    setEditingOverride(false);
                  }}
                  className="min-h-11 rounded-tile bg-tg-bg/60 px-3 text-sm text-tg-text"
                >{tx("Отмена")}</button>
              )}
              <button
                type="button"
                disabled={save.isPending || (!pickedDept && !experience)}
                onClick={() =>
                  save.mutate({
                    department_id: pickedDept,
                    experience: experience ?? me.experience,
                  })
                }
                className="min-h-11 flex-1 rounded-tile bg-tg-button px-3 text-sm font-medium text-tg-button-text disabled:opacity-50"
              >
                {onboarding ? tx("Продолжить") : tx("Сохранить")}
              </button>
            </div>
          </div>
        )}
      </section>

      {/* 2. Опыт и обучение: мотивация и курс — одна тема, а не три блока.
          KpiCard и AchievementsCard — самостоятельные карточки, поэтому здесь
          общий заголовок, а не карточка в карточке. */}
      <div data-testid="profile-progress" className="space-y-2">
        <h2 className="px-1 text-2xs font-medium uppercase tracking-wide text-tg-hint">{tx("Опыт и обучение")}</h2>
        <KpiCard />

        <section className="rounded-card bg-tg-secondary-bg/60 p-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-tg-text">{tx("Курс")}</h3>
            <span className="text-xs tabular-nums text-tg-hint">
              {trainingQ.data
                ? `${trainingQ.data.done}/${trainingQ.data.total}`
                : "…"}
            </span>
          </div>
          <p className="mt-1 text-xs text-tg-hint">{tx(
            "Три уровня от знакомства до самостоятельной работы — по одному действию на урок.",
          )}</p>

          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={learningMode.isPending}
              aria-pressed={me.learning_mode}
              onClick={() => learningMode.mutate(!me.learning_mode)}
              className={[
                "min-h-10 flex-1 rounded-tile px-2 text-xs transition-colors disabled:opacity-50",
                me.learning_mode
                  ? "bg-tg-button text-tg-button-text"
                  : "bg-tg-bg/60 text-tg-text",
              ].join(" ")}
            >
              {me.learning_mode
                ? tx("Учимся вместе · вкл")
                : tx("Учимся вместе · выкл")}
            </button>
            <button
              type="button"
              onClick={() => {
                haptic("light");
                setShowTraining(true);
              }}
              className="min-h-10 flex-1 rounded-tile bg-tg-button px-2 text-xs font-medium text-tg-button-text"
            >
              {trainingQ.data?.complete ? tx("Открыть курс") : tx("Продолжить курс")}
            </button>
          </div>
        </section>

        {/* Скрытый личный прогресс: сервер сам решает, показывать ли блок
            (сейчас — руководителю и админу), см. `AchievementsCard`. */}
        <AchievementsCard />
      </div>

      {/* 3. Разделы: один вход вместо сетки из 14 кнопок. */}
      <section className="rounded-card bg-tg-secondary-bg/60">
        <button
          type="button"
          aria-expanded={showSections}
          aria-controls="profile-sections"
          onClick={() => {
            haptic("light");
            setShowSections((v) => !v);
          }}
          className="flex min-h-12 w-full items-center gap-2 rounded-card px-3 text-left"
        >
          <Icon name="layout" size={18} className="text-tg-hint" />
          <span className="flex-1 text-sm font-semibold text-tg-text">{tx("Все разделы")}</span>
          <span className="text-xs tabular-nums text-tg-hint">
            {sections.length}
          </span>
          <Icon
            name="chevron"
            size={16}
            className={[
              "text-tg-hint transition-transform",
              showSections ? "rotate-90" : "",
            ].join(" ")}
          />
        </button>
        {showSections && (
          <div id="profile-sections" className="border-t border-tg-hint/10 p-2">
            {sections.map((item) => (
              <Row key={item.label} {...item} />
            ))}
          </div>
        )}
      </section>

      {/* Веб-версия: широкая ссылка для компьютера. Живёт рядом с разделами —
          это личный доступ, а не админская настройка. */}
      <WebVersionCard />

      {/* Подтверждение почты: карточка исчезает, как только адрес подтверждён. */}
      <EmailVerifyCard />

      {/* Push вне Telegram: своё устройство, свой тумблер. */}
      <PushCard />

      {/* 4. Админ-инструменты: нужны редко, поэтому свёрнуты. */}
      {(me.is_admin || me.is_staff) && (
        <section className="rounded-card bg-tg-secondary-bg/60">
          <button
            type="button"
            aria-expanded={showAdmin}
            aria-controls="profile-admin"
            onClick={() => {
              haptic("light");
              setShowAdmin((v) => !v);
            }}
            className="flex min-h-12 w-full items-center gap-2 rounded-card px-3 text-left"
          >
            <Icon name="admin" size={18} className="text-tg-hint" />
            <span className="flex-1 text-sm font-semibold text-tg-text">{tx("Для администратора")}</span>
            <Icon
              name="chevron"
              size={16}
              className={[
                "text-tg-hint transition-transform",
                showAdmin ? "rotate-90" : "",
              ].join(" ")}
            />
          </button>

          {showAdmin && (
            <div id="profile-admin" className="space-y-4 border-t border-tg-hint/10 p-3">
              {/* Кабинет предприятия — единственный вход в него после
                  31.10.2026: в нижней полосе вкладки «Админ» больше нет, а
                  иначе на телефоне это была седьмая подпись, которую видел
                  и сотрудник. Видна только тем, кому сервер разрешил (`me.is_admin`). */}
              {me.is_admin && (
                <button
                  type="button"
                  onClick={() => {
                    haptic("light");
                    setTab("admin");
                  }}
                  className="flex min-h-11 w-full items-center gap-2 rounded-tile bg-tg-bg/60 px-3 text-left text-sm font-medium text-tg-text"
                >
                  <Icon name="admin" size={17} className="text-tg-link" />
                  <span className="min-w-0 flex-1">{tx("Управление предприятием")}</span>
                  <Icon name="chevron" size={15} className="text-tg-hint" />
                </button>
              )}

              <div>
                <h3 className="text-xs font-medium text-tg-text">{tx("Примерить роль")}</h3>
                <p className="mt-1 text-xs text-tg-hint">{tx(
                  "Роль меняет только твой обзор: задачи, ленту и кабинет. Доступ в админку остаётся — вернуть себя можно этой же кнопкой.",
                )}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(
                    [
                      { v: "employee", label: "Сотрудник" },
                      { v: "aup", label: "Руководитель" },
                      { v: "admin", label: "Администратор" },
                    ] as const
                  ).map((option) => {
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
                        {tx(option.label)}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="border-t border-tg-hint/10 pt-3">
                <h3 className="text-xs font-medium text-tg-text">{tx("Режим проверки")}</h3>
                <p className="mt-1 text-xs text-tg-hint">{tx(
                  "Открой приложение глазами сотрудника. Тестовые задачи и смены удалятся при выходе — настоящие данные не изменятся.",
                )}</p>
                <select
                  aria-label={tx("Кого проверяем")}
                  value={simulationTarget ?? ""}
                  onChange={(event) =>
                    setSimulationTarget(
                      event.target.value ? Number(event.target.value) : null,
                    )
                  }
                  className="mt-2 min-h-10 w-full rounded-tile bg-tg-bg px-2 text-xs text-tg-text"
                >
                  <option value="">{tx("Выбери сотрудника")}</option>
                  {(employeesQ.data ?? []).map((person) => (
                    <option key={person.id} value={person.id}>
                      {person.display_name}
                      {person.department_name ? ` · ${person.department_name}` : ""}
                    </option>
                  ))}
                </select>
                <div className="mt-2 flex gap-1.5">
                  {[
                    { v: "new" as const, label: "Как новичок" },
                    { v: "as_is" as const, label: "Как сейчас" },
                  ].map((option) => (
                    <button
                      key={option.v}
                      type="button"
                      aria-pressed={simulationMode === option.v}
                      onClick={() => setSimulationMode(option.v)}
                      className={[
                        "min-h-9 flex-1 rounded-full px-3 text-xs transition-colors",
                        simulationMode === option.v
                          ? "bg-tg-button text-tg-button-text"
                          : "bg-tg-bg/60 text-tg-text",
                      ].join(" ")}
                    >
                      {tx(option.label)}
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  disabled={simulationTarget === null || simulationStart.isPending}
                  onClick={() => simulationStart.mutate()}
                  className="mt-2 min-h-10 w-full rounded-tile bg-tg-button text-xs font-medium text-tg-button-text disabled:opacity-50"
                >
                  {simulationStart.isPending
                    ? tx("Открываем…")
                    : tx("Открыть как сотрудник")}
                </button>
              </div>

              {me.is_admin && (
                <div className="border-t border-tg-hint/10 pt-3">
                  <h3 className="text-xs font-medium text-tg-text">{tx("Тестовый пул")}</h3>
                  <p className="mt-1 text-xs text-tg-hint">{tx(
                    "Сотрудники `[BOT]` для проверки сценариев. Настоящие данные не затрагиваются.",
                  )}</p>
                  <button
                    type="button"
                    onClick={() => {
                      haptic("light");
                      setShowDemo(true);
                    }}
                    className="mt-2 min-h-10 w-full rounded-tile bg-tg-bg/60 text-xs text-tg-text"
                  >{tx("Открыть тестовый пул")}</button>
                </div>
              )}

              {me.is_admin && (
                <div className="border-t border-tg-hint/10 pt-3">
                  <ServerSwitch />
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {/* Чат с ботом — тихая ссылка внизу, а не отдельная карточка. */}
      <div className="pb-2 text-center">
        {/* Текст можно переопределить в админке; если он совпадает с
            заводским — переводим, если написан свой — показываем как есть. */}
        <p className="text-xs text-tg-hint">{tx(photoHint)}</p>
        <button
          type="button"
          onClick={() => {
            haptic("light");
            const app = WebApp as unknown as { close?: () => void };
            app.close?.();
          }}
          className="mt-2 min-h-11 rounded-tile px-3 text-xs font-medium text-tg-link"
        >{tx("Вернуться в чат с ботом")}</button>
      </div>

      {showDemo && <HrDemoPanel onClose={() => setShowDemo(false)} />}

      {showFeedback && (
        <FeedbackScreen onClose={() => setShowFeedback(false)} />
      )}

      {showTraining && (
        <div className="fixed inset-0 z-40 mx-auto flex w-full max-w-[560px] bg-tg-bg">
          <TrainingScreen onClose={() => setShowTraining(false)} />
        </div>
      )}

      {orgSetupOpen && !orgSetupQ.data && (
        <div className="fixed inset-0 z-50 mx-auto flex w-full max-w-[560px] flex-col items-center justify-center gap-2 bg-tg-bg">
          <CardSkeleton />
          <button
            type="button"
            onClick={() => setOrgSetupOpen(false)}
            className="min-h-9 rounded-tile bg-tg-secondary-bg px-3 text-xs text-tg-text"
          >
            {tx("Отмена")}
          </button>
        </div>
      )}

      {orgSetupOpen && orgSetupQ.data && (
        <div className="fixed inset-0 z-50 mx-auto flex w-full max-w-[560px] bg-tg-bg">
          <OrgSetupScreen
            setup={{ ...orgSetupQ.data, done: false }}
            onClose={() => {
              haptic("success");
              setOrgSetupOpen(false);
              void qc.invalidateQueries({ queryKey: ["org-setup"] });
            }}
          />
        </div>
      )}
    </div>
  );
}

function ServerSwitch() {
  const { tx } = useTx();
  const [value, setValue] = useState(getApiBase());
  return (
    <div>
      <h3 className="text-xs font-medium text-tg-text">{tx("Сервер")}</h3>
      <p className="mt-1 text-xs text-tg-hint">{tx(
        "Если основной адрес недоступен, укажи резервный — приложение продолжит работать без переустановки. Пусто — адрес из сборки.",
      )}</p>
      <input
        value={value}
        onChange={(e) => setValue(e.target.value.trim())}
        placeholder="https://backup.example.ru"
        inputMode="url"
        autoCapitalize="none"
        autoCorrect="off"
        className="mt-2 min-h-10 w-full rounded-tile bg-tg-bg/60 px-2 text-xs text-tg-text"
      />
      <button
        type="button"
        onClick={() => {
          haptic("medium");
          setApiBase(value || null);
          window.location.reload();
        }}
        className="mt-2 min-h-10 w-full rounded-tile bg-tg-button text-xs font-medium text-tg-button-text"
      >{tx("Сохранить и перезагрузить")}</button>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-tile bg-tg-bg/50 p-2">
      <div className="text-tg-hint">{label}</div>
      <div className="text-tg-text">{value}</div>
    </div>
  );
}

/** Личная галочка приватности: включена/выключена и, если политика
 * организации, — «заперто руководителем», без лживого «выключено». */
function PrivacyRow({
  title,
  hint,
  value,
  locked,
  busy,
  onToggle,
}: {
  title: string;
  hint: string;
  value: boolean;
  locked: boolean;
  busy: boolean;
  onToggle: () => void;
}) {
  const { tx } = useTx();
  return (
    <div className="flex items-center gap-2 rounded-tile bg-tg-bg/50 p-2">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 text-xs text-tg-text">
          {title}
          {locked && <Icon name="lock" size={11} className="text-tg-hint" />}
        </div>
        <div className="text-2xs text-tg-hint">{hint}</div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        aria-label={title}
        disabled={locked || busy}
        onClick={() => {
          haptic("light");
          onToggle();
        }}
        className={[
          "min-h-9 shrink-0 rounded-full px-3 text-xs transition-colors disabled:opacity-60",
          value
            ? "bg-tg-button text-tg-button-text"
            : "bg-tg-secondary-bg text-tg-text",
        ].join(" ")}
      >
        {value ? tx("Видно") : tx("Скрыто")}
      </button>
    </div>
  );
}

/** Строка списка разделов: иконка, подпись, шеврон. */
function Row({ icon, label, onSelect }: RowItem) {
  const { tx } = useTx();
  return (
    <button
      type="button"
      onClick={() => {
        haptic("light");
        onSelect();
      }}
      className="flex min-h-11 w-full items-center gap-2 rounded-tile px-2 text-left text-sm text-tg-text active:bg-tg-bg/60"
    >
      <Icon name={icon} size={18} className="text-tg-hint" />
      <span className="flex-1 truncate">{tx(label)}</span>
      <Icon name="chevron" size={14} className="text-tg-hint" />
    </button>
  );
}
