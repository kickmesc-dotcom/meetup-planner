import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchMe,
  fetchUiPrefs,
  fetchUsers,
  updateUiPrefs,
  type UiPrefs,
} from "./api/availability";
import CalendarView from "./features/calendar/CalendarView";
import MeetingsPollsScreen from "./features/meetings/MeetingsPollsScreen";
// SemiTaskBot: рабочие экраны сотрудника.
import MyTasksScreen from "./features/hr/MyTasksScreen";
import ChecklistScreen from "./features/hr/ChecklistScreen";
import ShiftsScreen from "./features/shifts/ShiftsScreen";
import TeamScreen from "./features/hr/TeamScreen";
import { fetchEmployee } from "./api/hr";
import HrFeedScreen from "./features/hr/HrFeedScreen";
import IssuesScreen from "./features/issues/IssuesScreen";
import HandoversScreen from "./features/handovers/HandoversScreen";
import StandardsScreen from "./features/hr/StandardsScreen";
import ReviewScreen from "./features/hr/ReviewScreen";
import ReportsScreen from "./features/hr/ReportsScreen";
import LinksScreen from "./features/hr/LinksScreen";
import MaterialsScreen from "./features/hr/MaterialsScreen";
import HrProfileScreen from "./features/hr/HrProfileScreen";
import OnboardingScreen from "./features/hr/OnboardingScreen";
import WelcomeBanner from "./features/welcome/WelcomeBanner";
import AdminScreen from "./features/admin/AdminScreen";
import TabBar from "./features/nav/TabBar";
import ErrorState from "./components/ErrorState";
import ThemeSwitcher from "./components/ThemeSwitcher";
import SimulationBanner from "./components/SimulationBanner";
import { useSimulation } from "./store/simulation";
import { useUI } from "./store/ui";
import { getStartParam, haptic } from "./tg/webapp";

export default function App() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: fetchMe });
  const users = useQuery({ queryKey: ["users"], queryFn: fetchUsers });
  // HR-профиль нужен не только экрану профиля: от его роли зависит, есть ли
  // вкладка «Команда» (руководитель) и кабинет (прописанный админ).
  const hrMe = useQuery({
    queryKey: ["hr-employee"],
    queryFn: fetchEmployee,
    retry: false,
    staleTime: 60_000,
  });
  const uiPrefs = useQuery({ queryKey: ["ui-prefs"], queryFn: fetchUiPrefs });
  const hideGreeting = useMutation({
    mutationFn: () => updateUiPrefs({ hide_greeting: true }),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ["ui-prefs"] });
      const prev = qc.getQueryData<UiPrefs>(["ui-prefs"]);
      qc.setQueryData<UiPrefs>(["ui-prefs"], {
        welcome_format: prev?.welcome_format ?? "avatar",
        hide_greeting: true,
        muted_feed: prev?.muted_feed ?? [],
        show_last_seen: prev?.show_last_seen ?? true,
      });
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["ui-prefs"], ctx.prev);
      haptic("error");
    },
    onSuccess: () => haptic("selection"),
  });
  const tab = useUI((s) => s.tab);
  const setTab = useUI((s) => s.setTab);
  const simulationId = useSimulation((s) => s.sessionId);

  // GHG10 (Э4.2): анонс ачивки ведёт по deep link на «свои ачивки».
  // Э20: теперь это вкладка «Лента» — там и ачивки, и остальная активность.
  useEffect(() => {
    const start = getStartParam();
    if (start === "achievements" || start === "feed") setTab("feed");
  }, [setTab]);

  if (me.isPending || users.isPending) {
    return (
      <div className="mx-auto flex h-full w-full max-w-[560px] flex-col p-4 gap-3 animate-pulse">
        <div className="h-12 rounded-xl bg-tg-secondary-bg/60" />
        <div className="h-24 rounded-xl bg-tg-secondary-bg/60" />
        <div className="h-24 rounded-xl bg-tg-secondary-bg/60" />
        <div className="flex-1 rounded-xl bg-tg-secondary-bg/40" />
      </div>
    );
  }

  if (me.isError) {
    const status = me.error && (me.error as { status?: number }).status;
    if (status === 403) {
      return (
        <div className="flex h-full items-center justify-center px-6 text-center">
          <div>
            <div className="text-3xl mb-2">🛑</div>
            <div className="text-lg font-medium">Тебя нет в списке шестёрки</div>
            <div className="text-tg-hint mt-2 text-sm">
              Скинь админу свой Telegram ID командой /whoami боту.
            </div>
          </div>
        </div>
      );
    }
    return (
      <ErrorState
        error={me.error}
        onRetry={() => me.refetch()}
        title="Ошибка авторизации"
      />
    );
  }

  if (users.isError || !users.data) {
    return (
      <ErrorState
        error={users.error}
        onRetry={() => users.refetch()}
        title="Не удалось загрузить участников"
      />
    );
  }

  const meData = me.data!;
  // В режиме проверки админка скрыта: смотрим ровно глазами сотрудника.
  const isAdmin = !!meData.is_admin && !simulationId;
  const canManage = !!(hrMe.data?.is_aup || hrMe.data?.is_staff);

  // Онбординг — первая точка входа, а не форма внутри профиля.
  const onboarding = !!hrMe.data && hrMe.data.onboarding_state !== "done";
  if (onboarding) {
    return (
      <div className="relative mx-auto flex h-full w-full max-w-[560px] flex-col sm:border-x sm:border-tg-hint/10">
        <SimulationBanner />
        <OnboardingScreen employee={hrMe.data!} />
      </div>
    );
  }

  // Если переключились на admin без прав — мягко возвращаем к задачам.
  if (tab === "admin" && !isAdmin) {
    setTab("tasks");
  }
  if (tab === "team" && !canManage) {
    setTab("tasks");
  }
  if (tab === "review" && !canManage) {
    setTab("tasks");
  }

  const greetingHidden = uiPrefs.data?.hide_greeting === true;

  let content: React.ReactNode = null;
  if (tab === "calendar") {
    content = (
      <>
        {/* GHG8 P4: приветствие над календарём. Сводки званий больше нет —
            остались имя и закрытие (P4.1.c), сама пометка — та же ui-prefs
            мутация, что и раньше. */}
        {!greetingHidden && (
          <WelcomeBanner
            meName={meData.display_name}
            onHide={() => hideGreeting.mutate()}
          />
        )}
        <main className="flex-1 overflow-hidden">
          <CalendarView users={users.data} meId={meData.id} />
        </main>
      </>
    );
  } else if (tab === "meetings") {
    // Э21: одна вкладка на встречи и опросы — переключатель внутри экрана.
    content = (
      <>
        {/* GHG11(12): `pr-12`/абсолютный свитчер убраны — тема теперь часть
            строки шапки и выравнивается по тексту, а не «налеплена в угол». */}
        <header className="flex items-center gap-3 border-b border-tg-secondary-bg py-3 pl-4 pr-3">
          <div className="min-w-0 flex-1">
            <div className="text-base font-medium">🤝 Встречи и опросы</div>
            <div className="text-xs text-tg-hint">
              RSVP по встречам и голосования за слот — всё в одном месте.
            </div>
          </div>
          <ThemeSwitcher />
        </header>
        <main className="flex-1 overflow-hidden flex flex-col">
          <MeetingsPollsScreen users={users.data} meId={meData.id} />
        </main>
      </>
    );
  } else if (tab === "tasks") {
    // SemiTaskBot: главный экран смены. Свой заголовок живёт внутри экрана,
    // потому что там же переключатель «Активные / Все» и счётчик просрочек.
    content = (
      <main className="flex-1 overflow-hidden flex flex-col">
        <MyTasksScreen />
      </main>
    );
  } else if (tab === "checklist") {
    content = (
      <main className="flex-1 overflow-hidden flex flex-col">
        <ChecklistScreen />
      </main>
    );
  } else if (tab === "shifts") {
    // Табель: сотрудник видит свой отдел, управляющий — все (правит на сервере).
    content = (
      <main className="flex-1 overflow-hidden flex flex-col">
        <ShiftsScreen />
      </main>
    );
  } else if (tab === "feed") {
    content = (
      <main className="flex-1 overflow-hidden flex flex-col">
        <HrFeedScreen />
      </main>
    );
  } else if (tab === "team") {
    content = (
      <main className="flex-1 overflow-hidden flex flex-col">
        <TeamScreen canManage={!!hrMe.data?.is_staff} />
      </main>
    );
  } else if (tab === "issues") {
    // Журнал проблем: свой заголовок и возврат к задачам внутри экрана.
    content = (
      <main className="flex-1 overflow-hidden flex flex-col">
        <IssuesScreen />
      </main>
    );
  } else if (tab === "handovers") {
    content = (
      <main className="flex-1 overflow-hidden flex flex-col">
        <HandoversScreen />
      </main>
    );
  } else if (tab === "standards") {
    content = (
      <main className="flex-1 overflow-hidden flex flex-col">
        <StandardsScreen />
      </main>
    );
  } else if (tab === "review") {
    // Приёмка — только для АУП: сотруднику сервер всё равно вернёт пустой
    // список, а вкладку незачем даже показывать.
    content = canManage ? (
      <main className="flex-1 overflow-hidden flex flex-col">
        <ReviewScreen />
      </main>
    ) : null;
  } else if (tab === "reports") {
    // Отчёт смены — только руководителю: сотруднику сервер всё равно вернёт
    // 403, а вкладку незачем показывать.
    content = canManage ? (
      <main className="flex-1 overflow-hidden flex flex-col">
        <ReportsScreen />
      </main>
    ) : null;
  } else if (tab === "materials") {
    content = (
      <main className="flex-1 overflow-hidden flex flex-col">
        <MaterialsScreen />
      </main>
    );
  } else if (tab === "links") {

    content = (
      <main className="flex-1 overflow-hidden flex flex-col">
        <LinksScreen />
      </main>
    );
  } else if (tab === "profile") {
    content = (
      <>
        <header className="flex items-center gap-3 border-b border-tg-secondary-bg py-3 pl-4 pr-3">
          <div className="min-w-0 flex-1">
            <div className="text-base font-medium">👤 Профиль</div>
            <div className="text-xs text-tg-hint">
              Подразделение, опыт и обратная связь.
            </div>
          </div>
          <ThemeSwitcher />
        </header>
        <main className="flex-1 overflow-hidden flex flex-col">
          <HrProfileScreen />
        </main>
      </>
    );
  } else if (tab === "admin") {
    content = (
      <>
        <header className="flex items-center gap-3 border-b border-tg-secondary-bg py-3 pl-4 pr-3">
          <div className="min-w-0 flex-1">
            <div className="text-base font-medium">⚙️ Админка</div>
            <div className="text-xs text-tg-hint">
              Только для {meData.display_name}-уровня админов.
            </div>
          </div>
          <ThemeSwitcher />
        </header>
        <main className="flex-1 overflow-hidden flex flex-col">
          <AdminScreen users={users.data} />
        </main>
      </>
    );
  }

  return (
    // DESIGN_SYSTEM §9: центрированная колонка 560px — на планшете/десктопе
    // приложение читается как мини-апп, а не растягивается на всю ширину.
    // GHG11(8) плеер подборки недели (музыкальная механика) убран вместе с
    // остальным шуточным контуром — он уехал в `src/_legacy`, каркас остался.
    <div className="relative mx-auto flex h-full w-full max-w-[560px] flex-col sm:border-x sm:border-tg-hint/10">
      <SimulationBanner />
      {content}
      <TabBar isAdmin={isAdmin} canManage={canManage} />
    </div>
  );
}
