import { useEffect, useState } from "react";
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
import { countOpenTasks, fetchEmployee, fetchTasks } from "./api/hr";
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
import AuthScreen, { NoOrgScreen } from "./features/auth/AuthScreen";
import InviteScreen from "./features/auth/InviteScreen";
import { clearInviteTokenFromUrl, inviteTokenFromUrl } from "./features/auth/inviteUrl";
import TabBar from "./features/nav/TabBar";
import DesktopShell from "./features/desktop/DesktopShell";
import OverviewRail from "./features/desktop/OverviewRail";
import { useIsDesktop } from "./lib/useIsDesktop";
import ErrorState from "./components/ErrorState";
import Icon from "./components/Icon";
import TabTransition from "./components/TabTransition";
import ThemeSwitcher from "./components/ThemeSwitcher";
import SimulationBanner from "./components/SimulationBanner";
import { useSimulation } from "./store/simulation";
import { useUI } from "./store/ui";
import { getInitData, getStartParam, haptic } from "./tg/webapp";

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
  // Счётчик на «Задачах»: приём из соцсетей — число на разделе видно до
  // перехода. Ключ тот же, что у «Моих задач» и рельса сводки, поэтому
  // открытие экрана не повторяет запрос. Без HR-профиля (человека нет в
  // штате) запрос не уходит: вкладки «Задачи» у него всё равно нет.
  const tasksQ = useQuery({
    queryKey: ["hr-tasks", false],
    queryFn: () => fetchTasks(false),
    enabled: hrMe.data?.onboarding_state === "done",
    staleTime: 60_000,
    retry: false,
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
  // Широкий экран — отдельный каркас (сайдбар + рабочая область). Нижняя
  // полоса остаётся мобильной навигацией и на ПК не рисуется вовсе.
  const isDesktop = useIsDesktop();
  // Ссылка-приглашение: адрес /invite?token=…, разобранный один раз.
  // Живёт в состоянии, чтобы после принятия экран закрылся без перезагрузки
  // истории браузера.
  const [inviteToken, setInviteToken] = useState(() => inviteTokenFromUrl());

  // GHG10 (Э4.2): анонс ачивки ведёт по deep link на «свои ачивки».
  // Э20: теперь это вкладка «Лента» — там и ачивки, и остальная активность.
  useEffect(() => {
    const start = getStartParam();
    if (start === "achievements" || start === "feed") setTab("feed");
  }, [setTab]);

  if (me.isPending || users.isPending) {
    // На ПК скелет тоже широкий: иначе при загрузке на секунду мелькала бы
    // мобильная колонка 560px, а потом каркас «прыгал» в дэшборд.
    if (isDesktop) {
      return (
        <div className="flex h-full w-full animate-pulse">
          <div className="w-64 shrink-0 space-y-3 border-r border-tg-hint/10 bg-tg-secondary-bg/30 p-4">
            <div className="h-9 rounded-tile bg-tg-secondary-bg/70" />
            <div className="h-4 rounded-tile bg-tg-secondary-bg/50" />
            <div className="h-10 rounded-tile bg-tg-secondary-bg/60" />
            <div className="h-10 rounded-tile bg-tg-secondary-bg/60" />
            <div className="h-10 rounded-tile bg-tg-secondary-bg/60" />
            <div className="h-10 rounded-tile bg-tg-secondary-bg/60" />
          </div>
          <div className="flex-1 space-y-3 p-6">
            <div className="h-10 w-1/3 rounded-card bg-tg-secondary-bg/60" />
            <div className="h-12 rounded-card bg-tg-secondary-bg/50" />
            <div className="h-24 rounded-card bg-tg-secondary-bg/40" />
            <div className="h-24 rounded-card bg-tg-secondary-bg/40" />
            <div className="flex-1 rounded-card bg-tg-secondary-bg/30" />
          </div>
        </div>
      );
    }
    return (
      <div className="mx-auto flex h-full w-full max-w-[560px] flex-col p-4 gap-3 animate-pulse">
        <div className="h-12 rounded-card bg-tg-secondary-bg/60" />
        <div className="h-24 rounded-card bg-tg-secondary-bg/60" />
        <div className="h-24 rounded-card bg-tg-secondary-bg/60" />
        <div className="flex-1 rounded-card bg-tg-secondary-bg/40" />
      </div>
    );
  }

  if (me.isError) {
    const status = me.error && (me.error as { status?: number }).status;
    const authDetail =
      me.error && (me.error as { detail?: string }).detail
        ? String((me.error as { detail?: string }).detail)
        : "";
    if (status === 401) {
      // Вне Telegram личность подтверждает сессия по почте (шаг 2.1). Сессии
      // нет — показываем форму входа. Тупик «нужен вход» остался только для
      // мини-аппа, где `initData` подписал бот, но сервер его не принял.
      if (!getInitData()) {
        return <AuthScreen onDone={() => void me.refetch()} />;
      }
      return (
        <div className="flex h-full items-center justify-center px-6 text-center">
          <div className="max-w-sm">
            <Icon name="lock" size={30} className="mx-auto mb-2 text-tg-hint" />
            <div className="text-lg font-medium">Telegram не подтвердил вход</div>
            <p className="mt-2 text-sm text-tg-hint">
              Подпись мини-аппа не принята: бот могли переподключить к другой
              организации. Открой приложение заново из бота — или возьми ссылку
              для компьютера командой <b>/app</b>.
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-4 min-h-11 rounded-full bg-tg-button px-4 text-xs text-tg-button-text"
            >
              Проверить ещё раз
            </button>
          </div>
        </div>
      );
    }
    if (status === 403) {
      // Почтовый аккаунт есть, членства в организации ещё нет (шаг 2.2).
      // Это не «тебя уволили»: человека просто не пригласили.
      if (authDetail === "org_required") return <NoOrgScreen />;
      if (authDetail === "org_inactive") {
        return (
          <div className="flex h-full items-center justify-center px-6 text-center">
            <div className="max-w-sm">
              <Icon name="lock" size={30} className="mx-auto mb-2 text-tg-hint" />
              <div className="text-lg font-medium">Организация на паузе</div>
              <p className="mt-2 text-sm text-tg-hint">
                Доступ приостановлен на стороне организации. Напиши управляющему:
                когда паузу снимут, вход заработает снова — пароль менять не надо.
              </p>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="mt-4 min-h-11 rounded-full bg-tg-secondary-bg px-4 text-xs text-tg-text"
              >
                Проверить ещё раз
              </button>
            </div>
          </div>
        );
      }
      return (
        <div className="flex h-full items-center justify-center px-6 text-center">
          <div>
            <Icon
              name="alert"
              size={30}
              className="mx-auto mb-2 text-status-busy"
            />
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

  // Приглашение важнее «тебя ещё не пригласили»: человек пришёл по ссылке,
  // и показывать ему тупик было бы странно. Проверка стоит до участников —
  // список людей требует организации, которой у приглашённого ещё нет.
  if (inviteToken) {
    return (
      <InviteScreen
        token={inviteToken}
        onDone={() => {
          clearInviteTokenFromUrl();
          setInviteToken(null);
          // Сессия на сервере уже переведена в новую организацию, но кеш
          // запросов помнит прежнюю (и 403 org_required) — перезагрузка
          // дешевле, чем точечно сбрасывать пять ключей.
          window.location.reload();
        }}
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
  // Открытые поручения — одно число на оба каркаса (нижняя полоса и сайдбар).
  const { open: openTasks } = countOpenTasks(tasksQ.data ?? []);

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
            <div className="flex items-center gap-1.5 text-base font-medium">
              <Icon name="clock" size={17} />
              Встречи и опросы
            </div>
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
    // На широком экране у ленты появляется правый рельс сводки (на мобильном
    // он скрыт классом `hidden lg:block` внутри самого компонента).
    content = (
      <main className="flex min-h-0 flex-1 overflow-hidden">
        <div className="flex min-w-0 flex-1 flex-col">
          <HrFeedScreen />
        </div>
        <OverviewRail />
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
            <div className="flex items-center gap-1.5 text-base font-medium">
              <Icon name="profile" size={17} />
              Профиль
            </div>
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
            <div className="flex items-center gap-1.5 text-base font-medium">
              <Icon name="admin" size={17} />
              Админка
            </div>
            <div className="text-xs text-tg-hint">
              Люди, смены и правила — только для управляющих.
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

  // ПК/браузер: постоянный сайдбар и широкая область. Раньше здесь была та же
  // колонка 560px, что и на телефоне, — на мониторе половина экрана пустовала.
  if (isDesktop) {
    return (
      <div className="relative flex h-full w-full bg-tg-bg">
        <DesktopShell
          canManage={canManage}
          isAdmin={isAdmin}
          openTasks={openTasks}
          meName={hrMe.data?.display_name.replace("[BOT]", "").trim() || meData.display_name}
          meHint={
            hrMe.data?.position ??
            hrMe.data?.department_name ??
            "Сотрудник"
          }
        >
          <SimulationBanner />
          <TabTransition key={tab}>{content}</TabTransition>
        </DesktopShell>
      </div>
    );
  }

  return (
    // DESIGN_SYSTEM §9: центрированная колонка 560px — на планшете/десктопе
    // приложение читается как мини-апп, а не растягивается на всю ширину.
    // GHG11(8) плеер подборки недели (музыкальная механика) убран вместе с
    // остальным шуточным контуром — он уехал в `src/_legacy`, каркас остался.
    <div className="relative mx-auto flex h-full w-full max-w-[560px] flex-col sm:border-x sm:border-tg-hint/10">
      <SimulationBanner />
      {/* VISUAL_AUDIT P3.17: `key={tab}` перезапускает вход для нового экрана. */}
      <TabTransition key={tab}>{content}</TabTransition>
      <TabBar isAdmin={isAdmin} canManage={canManage} openTasks={openTasks} />
    </div>
  );
}
