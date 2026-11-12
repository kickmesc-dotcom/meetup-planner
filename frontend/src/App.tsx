import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchMe,
  fetchUiPrefs,
  fetchUsers,
  updateUiPrefs,
  type UiPrefs,
} from "./api/availability";
import { useBootstrap } from "./api/bootstrap";
import { getAccessToken, getSessionToken, isNetworkError } from "./api/client";

const MeetingsPollsScreen = lazy(() => import("./features/meetings/MeetingsPollsScreen"));
// SemiTaskBot: рабочие экраны сотрудника.
const MyTasksScreen = lazy(() => import("./features/hr/MyTasksScreen"));
const ChecklistScreen = lazy(() => import("./features/hr/ChecklistScreen"));
const ShiftsScreen = lazy(() => import("./features/shifts/ShiftsScreen"));
import {
  countOpenTasks,
  fetchEmployee,
  fetchOrgSetup,
  fetchTasks,
} from "./api/hr";
const HrFeedScreen = lazy(() => import("./features/hr/HrFeedScreen"));
const IssuesScreen = lazy(() => import("./features/issues/IssuesScreen"));
const HandoversScreen = lazy(() => import("./features/handovers/HandoversScreen"));
const StandardsScreen = lazy(() => import("./features/hr/StandardsScreen"));
const AskScreen = lazy(() => import("./features/hr/AskScreen"));
// Весь код управления (кабинет, приёмка, отчёт смены) живёт в зоне управления
// и грузится отдельными чанками оттуда: сотрудник его не открывает никогда, и
// незачем тянуть чужие полторы тысячи строк в первую загрузку его экрана.
const LinksScreen = lazy(() => import("./features/hr/LinksScreen"));
const MaterialsScreen = lazy(() => import("./features/hr/MaterialsScreen"));
const HrProfileScreen = lazy(() => import("./features/hr/HrProfileScreen"));
const OnboardingScreen = lazy(() => import("./features/hr/OnboardingScreen"));
const OrgSetupScreen = lazy(() => import("./features/hr/OrgSetupScreen"));
import { sectionEnabled } from "./features/hr/sections";
import WelcomeBanner from "./features/welcome/WelcomeBanner";
// Кабинет управления — отдельный каркас (`ManageZone`), а не вкладка внутри
// приложения сотрудника. Он сам лениво тянет AdminScreen, поэтому здесь его нет.
import ManageZone from "./features/admin/ManageZone";
import ModeSwitch from "./features/nav/ModeSwitch";
import ZoneHint from "./features/nav/ZoneHint";
import AuthScreen from "./features/auth/AuthScreen";
import StartScreen from "./features/auth/StartScreen";
import InviteScreen from "./features/auth/InviteScreen";
import { clearInviteTokenFromUrl, inviteTokenFromUrl } from "./features/auth/inviteUrl";
import TabBar from "./features/nav/TabBar";
import { SAFE_AREA_ROOT } from "./tg/safeArea";
import DesktopShell from "./features/desktop/DesktopShell";
import OverviewRail from "./features/desktop/OverviewRail";
import { useIsDesktop } from "./lib/useIsDesktop";
import ErrorState from "./components/ErrorState";
import { Skeleton } from "./components/Skeleton";
import Icon from "./components/Icon";
import TabTransition from "./components/TabTransition";
import ThemeSwitcher from "./components/ThemeSwitcher";
import LanguageSwitcher from "./components/LanguageSwitcher";
import { useLocale, useT } from "./i18n";
import SimulationBanner from "./components/SimulationBanner";
import { useSimulation } from "./store/simulation";
import { useUI } from "./store/ui";
import { getInitData, getStartParam, haptic } from "./tg/webapp";
import {
  clearDeepLink,
  deepLinkFromLocation,
  parseDeepLink,
} from "./tg/deepLink";
import { useTx } from "@/i18n";
export default function App() {
  const { tx } = useTx();
  const qc = useQueryClient();
  // Старт одним запросом: сервер отдаёт профиль, участников, HR-профиль,
  // поручения, настройку организации и личные настройки разом, а хук кладёт
  // их в кеш под обычными ключами — экраны про это не знают.
  const boot = useBootstrap();
  // Не вышло — включаем прежние шесть запросов поштучно (человек без
  // членства в организации, старый сервер без ручки). Деградация до
  // вчерашнего поведения, а не пустой экран.
  const bootFailed = boot.isError;
  const me = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    enabled: bootFailed,
    staleTime: 60_000,
  });
  const users = useQuery({
    queryKey: ["users"],
    queryFn: fetchUsers,
    enabled: bootFailed,
    staleTime: 60_000,
  });
  // HR-профиль нужен не только экрану профиля: от его роли зависит, есть ли
  // вкладка «Команда» (руководитель) и кабинет (прописанный админ).
  const hrMe = useQuery({
    queryKey: ["hr-employee"],
    queryFn: fetchEmployee,
    enabled: bootFailed,
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
    enabled: bootFailed && hrMe.data?.onboarding_state === "done",
    staleTime: 60_000,
    retry: false,
  });
  // Настройка организации: от неё зависят и разделы в каркасе, и правила
  // приватности. Читают все, меняет руководитель — поэтому запрос не под
  // условием роли.
  const orgSetup = useQuery({
    queryKey: ["org-setup"],
    queryFn: fetchOrgSetup,
    enabled: bootFailed,
    retry: false,
    staleTime: 5 * 60_000,
  });
  const uiPrefs = useQuery({
    queryKey: ["ui-prefs"],
    queryFn: fetchUiPrefs,
    enabled: bootFailed,
    staleTime: 60_000,
  });
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
  const { t } = useT();
  const setTab = useUI((s) => s.setTab);
  const mode = useUI((s) => s.mode);
  const setMode = useUI((s) => s.setMode);
  const setPendingAdminSection = useUI((s) => s.setPendingAdminSection);
  const setPendingTaskId = useUI((s) => s.setPendingTaskId);
  const setPendingIssueId = useUI((s) => s.setPendingIssueId);
  // §2 `skip-links` и `focus-on-route-change`: клавиатура и скринридер не должны
  // проходить заново через всю шапку на каждой смене вкладки. Первый рендер
  // пропускаем — там фокус ещё ничей, и забирать его незачем.
  const mainRef = useRef<HTMLDivElement | null>(null);
  const firstTabRef = useRef(true);
  useEffect(() => {
    if (firstTabRef.current) {
      firstTabRef.current = false;
      return;
    }
    mainRef.current?.focus({ preventScroll: true });
  }, [tab]);
  const simulationId = useSimulation((s) => s.sessionId);
  // Кому вообще можно управлять: руководитель отдела (`aup`), владелец
  // организации или прописанный разработчик. Считается по сырым данным, до
  // первых `return` — страховка от «застрявшего» режима нужна выше них.
  const canManageZone =
    !!(
      me.data?.is_admin ||
      hrMe.data?.is_admin ||
      hrMe.data?.is_aup ||
      hrMe.data?.is_staff
    ) && !simulationId;
  // Режим проверки и смена роли отбирают кабинет. Без этого человек остался бы
  // внутри зоны, которая ему больше не принадлежит, и видел бы там ошибки
  // доступа вместо своего экрана.
  useEffect(() => {
    if (mode === "manage" && !canManageZone) setMode("staff");
  }, [mode, canManageZone, setMode]);
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

  // M3: диплинк из уведомления. Сервер присылает `/?task=42`, service worker
  // по тапу либо открывает окно, либо пишет в уже открытое. Второй случай
  // важен: человек с открытым приложением не должен получать вторую копию —
  // он должен увидеть нужный раздел в том же окне.
  useEffect(() => {
    const apply = (raw: string) => {
      const link = parseDeepLink(raw);
      if (!link) return;
      setTab(link.tab);
      // §3 `deep-link`: вкладка — только половина дела. Номер записи
      // передаём экрану, а он сам решает, как её показать.
      if (link.taskId !== null) setPendingTaskId(link.taskId);
      if (link.issueId !== null) setPendingIssueId(link.issueId);
    };
    const initial = deepLinkFromLocation();
    if (initial) {
      setTab(initial.tab);
      if (initial.taskId !== null) setPendingTaskId(initial.taskId);
      if (initial.issueId !== null) setPendingIssueId(initial.issueId);
      clearDeepLink();
    }
    if (!("serviceWorker" in navigator)) return;
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; url?: string } | undefined;
      if (data?.type === "semitask:navigate" && typeof data.url === "string") {
        apply(data.url);
      }
    };
    navigator.serviceWorker.addEventListener("message", onMessage);
    return () => navigator.serviceWorker.removeEventListener("message", onMessage);
  }, [setTab, setPendingTaskId, setPendingIssueId]);

  // Языковой пакет (план, 8.3): включён ли узбекский в этой организации.
  // Флаг приходит вместе с настройками, которые читает каждый вошедший. Если
  // пакет выключили, пока человек был внутри, его вернут на русский сразу -
  // иначе экран оставался бы на языке, которого организация больше не обещает.
  const setUzPackAvailable = useLocale((s) => s.setUzPackAvailable);
  const uzPack = orgSetup.data?.uz_pack;
  useEffect(() => {
    if (typeof uzPack === "boolean") setUzPackAvailable(uzPack);
  }, [uzPack, setUzPackAvailable]);

  // Без сохранённого входа форма нужна сразу: ждать отказа сервера, чтобы
  // её показать, значит держать нового человека на пустой загрузке.
  const hasStoredAuth =
    !!getInitData() || !!getSessionToken() || !!getAccessToken();
  const authScreen = (
    <AuthScreen
      // Пока человек вводил пароль, `/users` и `/me/ui-prefs` уже
      // запросили API без токена и попали в ошибку. Без сброса кеша
      // после входа экран показывал «Не удалось загрузить участников /
      // Нет доступа», и надо было догадаться нажать «Повторить».
      onDone={() => {
        void qc.invalidateQueries();
        void me.refetch();
      }}
      invited={!!inviteToken}
    />
  );
  // Скелет — только пока старт действительно идёт. Запрос, вставший без
  // сети (`fetchStatus: "paused"`), не должен оставлять человека на
  // бесконечной загрузке: ниже его встретит форма или экран повтора.
  const bootStarting = boot.isPending && boot.fetchStatus !== "paused";
  const fallbackStarting =
    bootFailed &&
    (me.isPending || users.isPending) &&
    (me.fetchStatus === "fetching" || users.fetchStatus === "fetching");
  if (bootStarting || fallbackStarting) {
    // На ПК скелет тоже широкий: иначе при загрузке на секунду мелькала бы
    // мобильная колонка 560px, а потом каркас «прыгал» в дэшборд.
    if (isDesktop) {
      return (
        <div className="flex h-full w-full animate-pulse motion-reduce:animate-none">
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
      <div className="mx-auto flex h-full w-full max-w-[560px] flex-col p-4 gap-3 animate-pulse motion-reduce:animate-none">
        <div className="h-12 rounded-card bg-tg-secondary-bg/60" />
        <div className="h-24 rounded-card bg-tg-secondary-bg/60" />
        <div className="h-24 rounded-card bg-tg-secondary-bg/60" />
        <div className="flex-1 rounded-card bg-tg-secondary-bg/40" />
      </div>
    );
  }

  if (me.isError) {
    // Сеть пропала до входа. Экран «Ошибка авторизации» здесь врал бы: вход
    // не отклонён, сервер просто не ответил. Форма сохраняет введённое и
    // отправится, когда связь вернётся — а без неё человек видел тупик.
    if (!hasStoredAuth && isNetworkError(me.error)) return authScreen;
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
        return authScreen;
      }
      return (
        <div className="flex h-full items-center justify-center px-6 text-center">
          <div className="max-w-sm">
            <Icon name="lock" size={30} className="mx-auto mb-2 text-tg-hint" />
            <div className="text-lg font-medium">
              {tx("Telegram не подтвердил вход")}
            </div>
            <p className="mt-2 text-sm text-tg-hint">
              {tx(
                "Подпись мини-аппа не принята: бот могли переподключить к другой организации. Открой приложение заново из бота — или возьми ссылку для компьютера командой",
              )}{" "}
              <b>/app</b>.
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-4 min-h-11 rounded-full bg-tg-button px-4 text-xs text-tg-button-text"
            >
              {tx("Проверить ещё раз")}
            </button>
          </div>
        </div>
      );
    }
    if (status === 403) {
      // Почтовый аккаунт есть, членства в организации ещё нет (шаг 2.2).
      // Это не «тебя уволили» — человека ещё не пригласили. Теперь здесь не
      // тупик, а выбор: сотрудник входит по коду от руководителя, руководитель
      // заводит организацию сам.
      if (authDetail === "org_required") {
        return (
          <StartScreen onDone={() => window.location.reload()} />
        );
      }
      if (authDetail === "org_inactive") {
        return (
          <div className="flex h-full items-center justify-center px-6 text-center">
            <div className="max-w-sm">
              <Icon name="lock" size={30} className="mx-auto mb-2 text-tg-hint" />
              <div className="text-lg font-medium">
                {tx("Организация на паузе")}
              </div>
              <p className="mt-2 text-sm text-tg-hint">
                {tx(
                  "Доступ приостановлен на стороне организации. Напиши управляющему: когда паузу снимут, вход заработает снова — пароль менять не надо.",
                )}
              </p>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="mt-4 min-h-11 rounded-full bg-tg-secondary-bg px-4 text-xs text-tg-text"
              >
                {tx("Проверить ещё раз")}
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
            <div className="text-lg font-medium">
              {tx("Тебя нет в списке шестёрки")}
            </div>
            <div className="text-tg-hint mt-2 text-sm">
              {tx("Скинь админу свой Telegram ID командой /whoami боту.")}
            </div>
          </div>
        </div>
      );
    }
    return (
      <ErrorState
        error={me.error}
        onRetry={() => me.refetch()}
        title={tx("Ошибка авторизации")}
      />
    );
  }

  // Данных профиля нет, и запрос не идёт: сеть пропала или запрос встал.
  // Без сохранённого входа это обычный первый запуск — форма входа, а не
  // скелет; с сохранённым — экран связи с кнопкой повтора.
  if (!me.data) {
    if (!hasStoredAuth) return authScreen;
    return (
      <ErrorState
        error={me.error}
        onRetry={() => {
          void boot.refetch();
          void me.refetch();
          void users.refetch();
        }}
        title={tx("Нет связи с сервером")}
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
        title={tx("Не удалось загрузить участников")}
      />
    );
  }

  const meData = me.data!;
  // В режиме проверки админка скрыта: смотрим ровно глазами сотрудника.
  //
  // Владелец организации — администратор своей компании, даже если он вошёл
  // по почте и его Telegram-ID нет в списке платформы. Раньше кабинет
  // открывался только прописанным админам: B2B-клиент не видел ни чек-листов,
  // ни отделов, ни приглашений — а именно там они и живут.
  const canManage = !!(hrMe.data?.is_aup || hrMe.data?.is_staff);
  // Открытые поручения — одно число на оба каркаса (нижняя полоса и сайдбар).
  const { open: openTasks } = countOpenTasks(tasksQ.data ?? []);

  // Сначала — настройка организации для руководителя (это про предприятие
  // целиком), потом личное знакомство сотрудника.
  if (orgSetup.data?.can_edit && !orgSetup.data.done && hrMe.data) {
    return (
      <div
      className="relative mx-auto flex h-full w-full max-w-[560px] flex-col sm:border-x sm:border-tg-hint/10"
      style={SAFE_AREA_ROOT}
    >
        <SimulationBanner />
        {/* Экран грузится отдельным чанком: большинство людей его не видят. */}
        <Suspense fallback={<main className="flex flex-1 flex-col gap-3 overflow-hidden p-4">
          <Skeleton className="h-10" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </main>}>
          <OrgSetupScreen
            setup={orgSetup.data}
          onClose={() => {
            void orgSetup.refetch();
            // Мастер закрыл знакомство руководителя на сервере — без
            // обновления `hr-employee` в кеше приложение ещё минуту показывало
            // бы анкету сотрудника «где ты работаешь».
            void qc.invalidateQueries({ queryKey: ["hr-employee"] });
            // Следующий шаг руководителя — люди, а не пустая лента: «Команда»
            // держит приглашение и код компании.
              setTab("team");
            }}
          />
        </Suspense>
      </div>
    );
  }

  // Онбординг — первая точка входа, а не форма внутри профиля.
  const onboarding = !!hrMe.data && hrMe.data.onboarding_state !== "done";
  if (onboarding) {
    return (
      <div
      className="relative mx-auto flex h-full w-full max-w-[560px] flex-col sm:border-x sm:border-tg-hint/10"
      style={SAFE_AREA_ROOT}
    >
        <SimulationBanner />
        <Suspense fallback={<main className="flex flex-1 flex-col gap-3 overflow-hidden p-4">
          <Skeleton className="h-10" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </main>}>
          <OnboardingScreen employee={hrMe.data!} />
        </Suspense>
      </div>
    );
  }

  // Управленческие экраны — не вкладки зоны сотрудника, а разделы кабинета
  // (02.11.2026): команда, приёмка и отчёт плюс старые входы «Админка» из
  // профиля, полосы и deep link'ов. Человека с правом отправляем в зону
  // управления сразу в нужный раздел, без права — к его работе, а не в
  // кабинет, который ему не принадлежит.
  if (
    tab === "admin" ||
    tab === "team" ||
    tab === "review" ||
    tab === "reports"
  ) {
    if (canManageZone) {
      if (tab !== "admin") setPendingAdminSection(tab);
      setTab("feed");
      setMode("manage");
    } else {
      setTab("tasks");
    }
  }
  // Раздел выключен в настройке организации — возвращаем на события. Данные
  // грузятся один раз, поэтому до ответа ничего не прячем (иначе вкладки
  // мигали бы).
  const sections = orgSetup.data?.sections ?? null;
  if (sections !== null && !sectionEnabled(tab, sections)) {
    setTab("feed");
  }

  // Зона управления — отдельный экран целиком: своя шапка с переключателем,
  // без нижней полосы сотрудника. Права проверены выше: без них режим уже
  // вернулся бы в `staff`.
  if (mode === "manage" && canManageZone) {
    // 04.11.2026: на широком экране кабинет переезжает в тот же каркас, что и
    // зона сотрудника. Раньше он рисовал свой заголовок и нижнюю полосу, и при
    // переключении зон навигация прыгала из левого столбца в нижнюю строку.
    if (isDesktop) {
      return (
        <div
          className="relative flex h-full w-full bg-tg-bg"
          style={SAFE_AREA_ROOT}
        >
          <DesktopShell
            zone="manage"
            sections={sections ?? undefined}
            meName={
              hrMe.data?.display_name.replace("[BOT]", "").trim() ||
              meData.display_name
            }
            meHint={
              hrMe.data?.position ??
              hrMe.data?.department_name ??
              tx("Руководитель")
            }
            canManage={canManage}
            platform={!!meData.is_admin}
          >
            <SimulationBanner />
            <div className="flex justify-center border-b border-tg-secondary-bg px-3 py-2">
              <ModeSwitch className="w-full max-w-[320px]" />
            </div>
            <ManageZone
              desktop
              users={users.data}
              platform={!!meData.is_admin}
              canManage={canManage}
            />
          </DesktopShell>
        </div>
      );
    }
    return (
      <ManageZone
        users={users.data}
        platform={!!meData.is_admin}
        canManage={canManage}
      />
    );
  }

  const greetingHidden = uiPrefs.data?.hide_greeting === true;

  let content: React.ReactNode = null;
  if (tab === "calendar") {
    // Вкладка «Календарь» — наследство планировщика встреч: сетка свободного
    // времени по участникам. В рабочем приложении она показывала имена людей,
    // которых в смене уже нет, а вместо графика — пустые полосы. Теперь это
    // расписание смен (план, 13.1): та же неделя, но с реальной работой.
    // Отдельного пункта в меню у старой сетки больше нет.
    content = (
      <>
        {!greetingHidden && (
          <WelcomeBanner
            meName={meData.display_name}
            onHide={() => hideGreeting.mutate()}
          />
        )}
        <main className="flex-1 overflow-hidden flex flex-col">
          <ShiftsScreen />
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
              {tx("Встречи и опросы")}
            </div>
            <div className="text-xs text-tg-hint">
              {tx("RSVP по встречам и голосования за слот — всё в одном месте.")}
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
  } else if (tab === "ask") {
    // Поиск по знаниям: из него открываются «Стандарты» и «Смена», поэтому
    // он сам — отдельный экран, а не строка внутри одного из них.
    content = (
      <main className="flex-1 overflow-hidden flex flex-col">
        <AskScreen />
      </main>
    );
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
            <h1 className="flex items-center gap-1.5 text-base font-medium">
              <Icon name="profile" size={17} />
              {t("app.profile.title")}
            </h1>
            <div className="text-xs text-tg-hint">
              {t("app.profile.hint")}
            </div>
          </div>
          <LanguageSwitcher />
          <ThemeSwitcher />
        </header>
        <main className="flex-1 overflow-hidden flex flex-col">
          <HrProfileScreen sections={sections ?? undefined} />
        </main>
      </>
    );
  }

  // Отдельный чанк подгружается по переходу — поэтому вокруг экранов стоит
  // Suspense. На месте будущего экрана — каркас той же формы (DESIGN_SYSTEM §9),
  // а не надпись «Загрузка…».
  const screen = (
    <Suspense
      fallback={
        <main className="flex flex-1 flex-col gap-3 overflow-hidden p-4">
          <Skeleton className="h-10" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </main>
      }
    >
      {content}
    </Suspense>
  );

  // ПК/браузер: постоянный сайдбар и широкая область. Раньше здесь была та же
  // колонка 560px, что и на телефоне, — на мониторе половина экрана пустовала.
  if (isDesktop) {
    return (
      <div
        className="relative flex h-full w-full bg-tg-bg"
        style={SAFE_AREA_ROOT}
      >
        <DesktopShell
          sections={sections ?? undefined}
          openTasks={openTasks}
          canManage={canManageZone}
          meName={hrMe.data?.display_name.replace("[BOT]", "").trim() || meData.display_name}
          meHint={
            hrMe.data?.position ??
            hrMe.data?.department_name ??
            tx("Сотрудник")
          }
        >
          {/* §2 `skip-links`: первый Tab с клавиатуры уводит к содержимому,
              а не заставляет проходить сайдбар и переключатель режима. */}
          <a
            href="#main-content"
            className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-overlay focus:rounded-tile focus:bg-tg-bg focus:px-3 focus:py-2 focus:text-sm focus:text-tg-text focus:shadow-floating"
          >
            {tx("К содержимому")}
          </a>
          <SimulationBanner />
          {canManageZone && (
            <div className="flex justify-center border-b border-tg-secondary-bg px-3 py-2">
              <ModeSwitch className="w-full max-w-[320px]" />
            </div>
          )}
          <div
            ref={mainRef}
            id="main-content"
            tabIndex={-1}
            className="flex min-h-0 flex-1 flex-col outline-none"
          >
            <TabTransition key={tab}>{screen}</TabTransition>
          </div>
        </DesktopShell>
      </div>
    );
  }

  return (
    // DESIGN_SYSTEM §9: центрированная колонка 560px — на планшете/десктопе
    // приложение читается как мини-апп, а не растягивается на всю ширину.
    // GHG11(8) плеер подборки недели (музыкальная механика) убран вместе с
    // остальным шуточным контуром — он уехал в `src/_legacy`, каркас остался.
    <div
      className="relative mx-auto flex h-full w-full max-w-[560px] flex-col sm:border-x sm:border-tg-hint/10"
      style={SAFE_AREA_ROOT}
    >
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-overlay focus:rounded-tile focus:bg-tg-bg focus:px-3 focus:py-2 focus:text-sm focus:text-tg-text focus:shadow-floating"
      >
        {tx("К содержимому")}
      </a>
      <SimulationBanner />
      {/* Верхние вкладки — только у того, кому есть что переключать. У
          сотрудника их нет вовсе: его зона одна. */}
      {canManageZone && (
        <div className="border-b border-tg-secondary-bg px-3 py-2">
          <ModeSwitch />
          <ZoneHint canManage={canManageZone} />
        </div>
      )}
      {/* VISUAL_AUDIT P3.17: `key={tab}` перезапускает вход для нового экрана. */}
      <div
        ref={mainRef}
        id="main-content"
        tabIndex={-1}
        className="flex min-h-0 flex-1 flex-col outline-none"
      >
        <TabTransition key={tab}>{screen}</TabTransition>
      </div>
      <TabBar sections={sections ?? undefined} openTasks={openTasks} />
    </div>
  );
}
