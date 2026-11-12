import { ReactNode, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchDashboard } from "@/api/hr";
import type { User } from "@/types";
import { haptic } from "@/tg/webapp";
import FormField from "@/components/FormField";
import AttentionScreen from "./AttentionScreen";
import AttentionStrip from "./AttentionStrip";
import AppTextsScreen from "./AppTextsScreen";
import BirthdaysScreen from "./BirthdaysScreen";
import CalendarSettingsScreen from "./CalendarSettingsScreen";
import ChecklistSettingsScreen from "./ChecklistSettingsScreen";
import EmployeesScreen from "./EmployeesScreen";
import FeedSettingsScreen from "./FeedSettingsScreen";
import IntervalsScreen from "./IntervalsScreen";
import InvitationsScreen from "./InvitationsScreen";
import JobsQueueScreen from "./JobsQueueScreen";
import JournalScreen from "./JournalScreen";
import KpiScreen from "./KpiScreen";
import NotificationsScreen from "./NotificationsScreen";
import PollPresetsScreen from "./PollPresetsScreen";
import ProxyScreen from "./ProxyScreen";
import SpaceRestartScreen from "./SpaceRestartScreen";
import TrainingPlanScreen from "./TrainingPlanScreen";
import LanguagesScreen from "./LanguagesScreen";
import PackScreen from "./PackScreen";
import DemoScreen from "./DemoScreen";
import AdminTasksScreen from "./AdminTasksScreen";
import TeamScreen from "@/features/hr/TeamScreen";
import ReviewScreen from "@/features/hr/ReviewScreen";
import ReportsScreen from "@/features/hr/ReportsScreen";
import MaterialsScreen from "@/features/hr/MaterialsScreen";
import MenuScreen from "./MenuScreen";
import StandardsScreen from "@/features/hr/StandardsScreen";
import SettingsScreen from "@/features/admin/SettingsScreen";
import PlanScreen from "./PlanScreen";
import BillingScreen from "./BillingScreen";
import BrandScreen from "./BrandScreen";
import DomainScreen from "./DomainScreen";
import BranchesScreen from "./BranchesScreen";
import IntegrationsScreen from "./IntegrationsScreen";
import ImportScreen from "./ImportScreen";
import PrivacyScreen from "./PrivacyScreen";
import PlatformScreen from "./PlatformScreen";
import Icon, { type IconName } from "@/components/Icon";
import { useTx } from "@/i18n";
import { useUI } from "@/store/ui";
import { useUxMode } from "./uxMode";

/**
 * Админка управляющего. Здесь только рабочие вещи: люди, смена, контроль,
 * календарь и системные экраны. Наследные шуточные разделы (лох/чухан/игры/
 * реакции/рандомные фразы/пауза) удалены вместе с модулями — их больше нет ни
 * в API, ни в боте.
 *
 * VISUAL_AUDIT P1.9: разделов стало 18, и это был один длинный список: чтобы
 * дойти до «Прокси», приходилось листать полтора экрана, а найти что-то по
 * памяти («где тексты?») было нечем. Теперь:
 *  - сверху поиск по названию, подписи и группе;
 *  - разделы, которые реально открывают, поднимаются в группу «Частое»
 *    (переезжают, а не дублируются) — счётчик живёт в localStorage;
 *  - семантические группы остались: 18 карточек всё равно нужно раскладывать.
 */
type Section =
  | "root"
  | "privacy"
  | "integrations"
  | "import"
  | "attention"
  | "admin-tasks"
  | "journal"
  | "notifications"
  | "employees"
  | "invitations"
  | "team"
  | "review"
  | "reports"
  | "menu"
  | "materials"
  | "standards"
  | "settings"
  | "checklists"
  | "training-plan"
  | "feed-settings"
  | "kpi"
  | "calendar-settings"
  | "birthdays"
  | "poll-presets"
  | "texts"
  | "languages"
  | "pack"
  | "demo"
  | "intervals"
  | "proxy"
  | "jobs"
  | "plan"
  | "billing"
  | "platform"
  | "brand"
  | "domain"
  | "branches"
  | "space-restart";

/** GHG11(4): допустимые подразделы для deep-link из анонса фичи. */
const VALID_SECTIONS: Section[] = [
  "attention",
  "admin-tasks",
  "journal",
  "notifications",
  "employees",
  "invitations",
  "import",
  "team",
  "review",
  "reports",
  "menu",
  "materials",
  "standards",
  "settings",
  "checklists",
  "training-plan",
  "feed-settings",
  "kpi",
  "calendar-settings",
  "birthdays",
  "poll-presets",
  "texts",
  "pack",
  "demo",
  "intervals",
  "proxy",
  "jobs",
  "plan",
  "billing",
  "platform",
  "brand",
  "domain",
  "branches",
  "privacy",
  "space-restart",
];

const GROUP_PEOPLE = "Смена и люди";
// Команда, приёмка и отчёт смены жили в нижней полосе руководителя. С 02.11.2026
// полоса сотрудника одинакова у всех, а эти три экрана — работа с людьми, то
// есть кабинет. Своя группа, потому что это не «смена и люди» в смысле
// настроек, а надзор за тем, что уже происходит.
const GROUP_TEAM = "Команда и контроль";
// Документы смены (меню, график, методички, инструкции с тестами) сотрудник
// читает у себя, а правит руководитель — значит править должен здесь, в
// кабинете, а не в экране сотрудника по совместительству.
const GROUP_DOCS = "Документы и знания";
const GROUP_RESULT = "Опыт и результат";
const GROUP_CALENDAR = "Календарь";
const GROUP_TEXTS = "Тексты";
const GROUP_SYSTEM = "Система";
// Настройки приложения: язык, тема и виды экранов. Раньше язык и тема висели
// в шапке зоны управления рядом с вкладками — как ещё две вкладки (жалоба
// владельца 02.11.2026).
const GROUP_SETTINGS = "Настройки";

interface SectionDef {
  id: Section;
  group: string;
  icon: IconName;
  title: string;
  subtitle: string;
}

const SECTIONS: SectionDef[] = [
  {
    id: "attention",
    group: GROUP_PEOPLE,
    icon: "alert",
    title: "Требует внимания",
    subtitle: "Просроченные поручения и открытые проблемы",
  },
  {
    id: "admin-tasks",
    group: GROUP_PEOPLE,
    icon: "clipboard",
    title: "Поручения",
    subtitle: "Создать, назначить, срок с точностью до секунды",
  },
  {
    id: "notifications",
    group: GROUP_PEOPLE,
    icon: "bell",
    title: "Уведомления",
    subtitle: "Что отправлено и что запланировано",
  },
  {
    id: "employees",
    group: GROUP_PEOPLE,
    icon: "team",
    title: "Сотрудники",
    subtitle: "Кто работает, прогресс и увольнение",
  },
  {
    id: "invitations",
    group: GROUP_PEOPLE,
    icon: "send",
    title: "Приглашения",
    subtitle: "Ссылка с ролью и сроком — вход без Telegram",
  },
  {
    // 04.11.2026, шаг 6.3: первый день клиента — это двадцать человек и неделя
    // графика. Ручное заведение съедало наше время при каждом внедрении.
    id: "import",
    group: GROUP_PEOPLE,
    icon: "inbox",
    title: "Загрузить из таблицы",
    subtitle: "Люди и график из CSV: проверить и загрузить",
  },
  {
    id: "team",
    group: GROUP_TEAM,
    icon: "team",
    title: "Команда",
    subtitle: "Кто на смене, активность и карточки сотрудников",
  },
  {
    id: "review",
    group: GROUP_TEAM,
    icon: "checklist",
    title: "Проверить работы",
    subtitle: "Принять или вернуть с причиной",
  },
  {
    id: "reports",
    group: GROUP_TEAM,
    icon: "layout",
    title: "Отчёт смены",
    subtitle: "Срез дня по стандартам и выгрузка CSV",
  },
  {
    id: "menu",
    group: GROUP_DOCS,
    icon: "book",
    title: "Меню смены",
    subtitle: "Позиции и цены: убрать на сегодня, вернуть, добавить",
  },
  {
    id: "materials",
    group: GROUP_DOCS,
    icon: "book",
    title: "Материалы",
    subtitle: "Меню, график и методички",
  },
  {
    id: "standards",
    group: GROUP_DOCS,
    icon: "checklist",
    title: "Стандарты",
    subtitle: "Инструкции и тесты по ним: добавить и поправить",
  },
  {
    id: "checklists",
    group: GROUP_PEOPLE,
    icon: "checklist",
    title: "Чек-листы",
    subtitle: "Пункты по залам, закрытие смены, фотоотчёт",
  },
  {
    id: "training-plan",
    group: GROUP_PEOPLE,
    icon: "book",
    title: "Обучение и ставка",
    subtitle: "Учебные и обычные смены по дням, полная/частичная ставка",
  },
  {
    id: "journal",
    group: GROUP_PEOPLE,
    icon: "book",
    title: "Журнал событий",
    subtitle: "Поручения человеческим языком, включая автоматику",
  },
  {
    id: "feed-settings",
    group: GROUP_PEOPLE,
    icon: "layout",
    title: "Вид ленты",
    subtitle: "Компактный (миниатюры участников) / классический",
  },
  {
    // Группа «Смена и люди», а не «Тексты»: пакет — про людей в команде, и
    // решает его владелец, а не тот, кто правит подписи. В «Текстах» он ещё
    // и ломал бы вид группы: она бы перестала быть пустой при переносе
    // «Текстов приложения» в частое.
    id: "languages",
    group: GROUP_PEOPLE,
    icon: "globe",
    title: "Языки",
    subtitle: "Узбекский пакет для команды: включён по умолчанию",
  },
  {
    // Пакет отрасли — рядом с «Языками»: это тоже «что видит команда», а не
    // настройка экрана. Термины, чек-листы, веса опыта и должности — один
    // ответ на вопрос «мы не ресторан, почему у нас залы».
    id: "pack",
    group: GROUP_PEOPLE,
    icon: "layout",
    title: "Пакет отрасли",
    subtitle: "Термины, KPI и должности под ваш бизнес",
  },
  {
    // Демо — рядом с пакетом: это один и тот же разговор «мы не ресторан»,
    // только на витрине. Показ клиенту идёт до его данных, а не после.
    id: "demo",
    group: GROUP_PEOPLE,
    icon: "sparkles",
    title: "Демо-данные",
    subtitle: "Показать приложение на тестовых людях за пять минут",
  },
  {
    id: "kpi",
    group: GROUP_RESULT,
    icon: "award",
    title: "Опыт и рейтинг",
    subtitle: "Сколько стоит работа и кто лучший на неделе",
  },
  {
    id: "calendar-settings",
    group: GROUP_CALENDAR,
    icon: "calendar",
    title: "Вид календаря",
    subtitle: "Таймлайн или старый вид",
  },
  {
    id: "birthdays",
    group: GROUP_CALENDAR,
    icon: "cake",
    title: "Дни рождения и праздники",
    subtitle: "Даты, поздравления и напоминания",
  },
  {
    id: "poll-presets",
    group: GROUP_CALENDAR,
    icon: "clock",
    title: "Слоты для опросов",
    subtitle: "Готовые интервалы: 12–15, 15–18…",
  },
  {
    id: "texts",
    group: GROUP_TEXTS,
    icon: "edit",
    title: "Тексты приложения",
    subtitle: "Приветствие, подсказки и пустые состояния",
  },
  {
    id: "settings",
    group: GROUP_SETTINGS,
    icon: "settings",
    title: "Настройки",
    subtitle: "Язык, тема и вид экранов",
  },
  {
    id: "intervals",
    group: GROUP_SYSTEM,
    icon: "repeat",
    title: "Частота напоминаний",
    subtitle: "Как часто проверять очередь напоминаний",
  },
  {
    id: "jobs",
    group: GROUP_SYSTEM,
    icon: "clipboard",
    title: "Запланированные задачи",
    subtitle: "Фоновые задачи: изменить или пропустить",
  },
  {
    id: "plan",
    group: GROUP_SETTINGS,
    icon: "award",
    title: "Тариф и лимиты",
    subtitle: "Места, подразделения и срок пробного периода",
  },
  {
    // Рядом с «Тарифом»: лимит и его цена — один разговор, и человек ищет
    // оплату там же, где увидел, что места кончились.
    // Бренд рядом с оплатой: это один разговор «как выглядит наш продукт»,
    // и настраивает его владелец, а не тот, кто правит подписи.
    id: "brand",
    group: GROUP_SETTINGS,
    icon: "edit",
    title: "Бренд",
    subtitle: "Своё имя, цвет и логотип вместо SemiTaskBot",
  },
  {
    // Рядом с брендом и оплатой: это тоже «наши настройки с сервисом»,
    // а не работа смены (шаг 5.5).
    id: "privacy",
    group: GROUP_SETTINGS,
    icon: "check",
    title: "Данные и приватность",
    subtitle: "Копия данных, удаление организации, журнал доступа",
  },
  {
    // Интеграции рядом с приватностью: это тоже «кто получает наши данные»,
    // и решает это владелец (шаг 6.1).
    id: "integrations",
    group: GROUP_SETTINGS,
    icon: "link",
    title: "Интеграции",
    subtitle: "Ключи API и вебхуки для внешних систем",
  },
  {
    id: "billing",
    group: GROUP_SETTINGS,
    icon: "award",
    title: "Оплата и счета",
    subtitle: "Тарифы, счёт на оплату и история платежей",
  },
  {
    id: "platform",
    group: GROUP_SYSTEM,
    icon: "admin",
    title: "Платформа",
    subtitle: "Клиенты, тарифы, блокировки и подтверждение оплат",
  },
  {
    id: "proxy",
    group: GROUP_SYSTEM,
    icon: "globe",
    title: "Прокси",
    subtitle: "Пул прокси и авто-переключение",
  },
  {
    id: "space-restart",
    group: GROUP_SYSTEM,
    icon: "refresh",
    title: "Рестарт Space",
    subtitle: "Перезапуск, если сеть зависла",
  },
];

const GROUPS: { title: string; icon: IconName }[] = [
  { title: GROUP_PEOPLE, icon: "team" },
  { title: GROUP_TEAM, icon: "check" },
  { title: GROUP_DOCS, icon: "book" },
  { title: GROUP_RESULT, icon: "award" },
  { title: GROUP_CALENDAR, icon: "calendar" },
  { title: GROUP_TEXTS, icon: "edit" },
  { title: GROUP_SETTINGS, icon: "settings" },
  { title: GROUP_SYSTEM, icon: "admin" },
];

/**
 * Разделы платформы, а не клиента: прокси, рестарт Space, тексты, интервалы
 * напоминаний и очередь задач. Владелец организации — администратор своей
 * компании (чек-листы, люди, приглашения), но не хозяин сервера: эти карточки
 * ему не нужны и только пугают.
 */
/**
 * Что остаётся в простом режиме: люди, контроль над сменой, результат и
 * настройки. Документы, календарь и системы — по кнопке «Показать все».
 * Это не запрет, а порядок: спрятанное остаётся в одном нажатии.
 */
const SIMPLE_GROUPS = [GROUP_PEOPLE, GROUP_TEAM, GROUP_RESULT, GROUP_SETTINGS];

const PLATFORM_SECTIONS: Section[] = [
  // Админка платформы: клиенты всех организаций. Владельцу салона она не
  // нужна и опасна — он увидел бы чужие компании.
  "platform",
  "texts",
  "intervals",
  "jobs",
  "proxy",
  "space-restart",
];

/** Сколько частых разделов поднимаем наверх: больше — уже не «частое». */
const FREQUENT_LIMIT = 3;
const USAGE_KEY = "admin.usage.v1";

function readUsage(): Record<string, number> {
  try {
    const raw = localStorage.getItem(USAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    const result: Record<string, number> = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof value === "number" && value > 0) result[key] = value;
    }
    return result;
  } catch {
    // Приватный режим или мусор в хранилище — просто без истории.
    return {};
  }
}

function writeUsage(usage: Record<string, number>): void {
  try {
    localStorage.setItem(USAGE_KEY, JSON.stringify(usage));
  } catch {
    // Нечего делать: частое — удобство, а не данные.
  }
}

function topFrequent(
  usage: Record<string, number>,
  sections: SectionDef[] = SECTIONS,
): SectionDef[] {
  return sections.filter((s) => (usage[s.id] ?? 0) > 0)
    .sort((a, b) => (usage[b.id] ?? 0) - (usage[a.id] ?? 0))
    .slice(0, FREQUENT_LIMIT);
}

interface Props {
  users: User[];
  /** Прописанный админ платформы: видит системные разделы. */
  platform?: boolean;
  /** Руководитель: видит команду, приёмку и отчёт смены. */
  canManage?: boolean;
}

/** Разделы надзора за людьми: нужны руководителю, а не владельцу платформы. */
const MANAGER_SECTIONS: Section[] = [
  "team",
  "review",
  "reports",
  "menu",
  "materials",
  "standards",
];

export default function AdminScreen({
  users,
  platform = false,
  canManage = false,
}: Props) {
  void users;
  const { tx } = useTx();
  const sections = SECTIONS.filter((s) => {
    if (PLATFORM_SECTIONS.includes(s.id)) return platform;
    if (MANAGER_SECTIONS.includes(s.id)) return canManage || platform;
    return true;
  });
  // Раздел — в сторе, а не локально: его переключает и нижняя полоса зоны
  // управления, и deep link из профиля. Два источника состояния на один экран
  // разошлись бы (полоса подсветила бы одно, кабинет показал другое).
  const section = useUI((s) => s.adminSection) as Section;
  const setSection = useUI((s) => s.setAdminSection);
  const setTab = useUI((s) => s.setTab);
  const setMode = useUI((s) => s.setMode);
  const [query, setQuery] = useState("");
  const [usage, setUsage] = useState<Record<string, number>>(readUsage);
  // §11: простой режим прячет редкие группы за одну кнопку, расширенный
  // показывает всё сразу. Поиск и «Частое» работают одинаково в обоих.
  const uxMode = useUxMode();
  const [showAll, setShowAll] = useState(false);
  const simple = uxMode === "simple" && !showAll;

  // GHG11(4): переход из анонса фичи — сразу открыть нужный подраздел.
  const pendingAdminSection = useUI((s) => s.pendingAdminSection);
  const setPendingAdminSection = useUI((s) => s.setPendingAdminSection);
  useEffect(() => {
    if (!pendingAdminSection) return;
    if (VALID_SECTIONS.includes(pendingAdminSection as Section)) {
      setSection(pendingAdminSection as Section);
    }
    setPendingAdminSection(null);
  }, [pendingAdminSection, setPendingAdminSection, setSection]);

  // Сводка первым экраном: один запрос вместо двух. Раньше корень кабинета
  // тянул поручения и проблемы только ради бейджа, а «сколько чего горит»
  // руководитель собирал глазами по трём разделам. Теперь те же числа, но
  // одним ответом и сразу на виду; область видимости `/api/admin/dashboard`
  // считает сам по роли (руководитель — своё подразделение, админ — всё).
  const dashboard = useQuery({
    queryKey: ["admin", "dashboard"],
    queryFn: fetchDashboard,
    staleTime: 60_000,
  });
  const attentionCount =
    (dashboard.data?.tasks_overdue ?? 0) + (dashboard.data?.open_issues ?? 0);

  const back = () => setSection("root");

  if (section === "attention") {
    return (
      <AttentionScreen onBack={back} onOpenTasks={() => setSection("admin-tasks")} />
    );
  }
  if (section === "admin-tasks") return <AdminTasksScreen onBack={back} />;
  if (section === "journal") return <JournalScreen onBack={back} />;
  if (section === "notifications") return <NotificationsScreen onBack={back} />;
  if (section === "employees") return <EmployeesScreen onBack={back} />;
  if (section === "invitations") return <InvitationsScreen onBack={back} />;
  if (section === "team") return <TeamScreen canManage={false} onBack={back} />;
  if (section === "review") return <ReviewScreen onBack={back} />;
  if (section === "reports") return <ReportsScreen onBack={back} />;
  if (section === "menu") return <MenuScreen onBack={back} />;
  if (section === "materials") return <MaterialsScreen onBack={back} />;
  if (section === "pack") return <PackScreen onBack={back} />;
  if (section === "demo") return <DemoScreen onBack={back} />;
  if (section === "standards") return <StandardsScreen onBack={back} />;
  if (section === "settings") {
    return (
      <SettingsScreen
        platform={platform}
        onBack={back}
        onOpen={(next) => setSection(next)}
      />
    );
  }
  if (section === "checklists") return <ChecklistSettingsScreen onBack={back} />;
  if (section === "training-plan") return <TrainingPlanScreen onBack={back} />;
  if (section === "feed-settings") return <FeedSettingsScreen onBack={back} />;
  if (section === "kpi") return <KpiScreen onBack={back} />;
  if (section === "calendar-settings") return <CalendarSettingsScreen onBack={back} />;
  if (section === "birthdays") return <BirthdaysScreen onBack={back} />;
  if (section === "poll-presets") return <PollPresetsScreen onBack={back} />;
  if (section === "texts") return <AppTextsScreen onBack={back} />;
  if (section === "languages") return <LanguagesScreen onBack={back} />;
  if (section === "intervals") return <IntervalsScreen onBack={back} />;
  if (section === "proxy") return <ProxyScreen onBack={back} />;
  if (section === "jobs") return <JobsQueueScreen onBack={back} />;
  if (section === "space-restart") return <SpaceRestartScreen onBack={back} />;
  if (section === "plan") return <PlanScreen onBack={back} />;
  if (section === "billing") return <BillingScreen onBack={back} />;
  if (section === "platform") return <PlatformScreen onBack={back} />;
  if (section === "brand") return <BrandScreen onBack={back} />;
  if (section === "domain") return <DomainScreen onBack={back} />;
  if (section === "branches") return <BranchesScreen onBack={back} />;
  if (section === "privacy") return <PrivacyScreen onBack={back} />;
  if (section === "integrations") return <IntegrationsScreen onBack={back} />;
  if (section === "import") return <ImportScreen onBack={back} />;

  const select = (s: Section) => {
    haptic("selection");
    const next = { ...usage, [s]: (usage[s] ?? 0) + 1 };
    setUsage(next);
    writeUsage(next);
    setSection(s);
  };

  const needle = query.trim().toLowerCase();
  // Ищем и по переводу: на английском человек набирает "tasks", а в коде
  // раздел по-прежнему называется «Поручения» — без этого поиск пустел.
  const found = needle
    ? sections.filter((s) =>
        `${s.title} ${s.subtitle} ${s.group} ${tx(s.title)} ${tx(s.subtitle)} ${tx(s.group)}`
          .toLowerCase()
          .includes(needle),
      )
    : [];
  const frequent = needle ? [] : topFrequent(usage, sections);
  const lifted = new Set(frequent.map((s) => s.id));
  const frequentCount = (s: Section) => (s === "attention" ? attentionCount : undefined);

  const card = (s: SectionDef) => (
    <Card
      key={s.id}
      icon={s.icon}
      title={tx(s.title)}
      subtitle={tx(s.subtitle)}
      onClick={() => select(s.id)}
      badge={frequentCount(s.id)}
    />
  );

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-4">
      {/* Сводка «что горит» стоит первой: это ответ на главный вопрос
          руководителя, а не ещё одна карточка каталога. */}
      {!needle && (
        <AttentionStrip
          data={dashboard.data}
          loading={dashboard.isPending}
          onOpen={select}
        />
      )}
      {!needle && <QuickActions onPick={select} />}

      {!needle && (
        <button
          type="button"
          onClick={() => {
            haptic("selection");
            setTab("shifts");
            setMode("staff");
          }}
          className="flex min-h-11 w-full items-center gap-2 rounded-tile bg-tg-secondary-bg/60 px-3 text-left text-sm text-tg-text press"
        >
          <Icon name="calendar" size={18} className="shrink-0 text-tg-link" />
          <span className="min-w-0 flex-1 truncate">
            {tx("Открыть график смен")}
          </span>
          <span className="shrink-0 text-xs text-tg-hint">
            {tx("у сотрудников")}
          </span>
        </button>
      )}

      {uxMode === "simple" && (
        <button
          type="button"
          onClick={() => setShowAll((value) => !value)}
          className="min-h-11 w-full rounded-tile bg-tg-secondary-bg text-sm text-tg-link press"
        >
          {showAll
            ? tx("Свернуть лишние разделы")
            : tx("Показать все разделы")}
        </button>
      )}

      <div className="relative">
        <Icon
          name="search"
          size={18}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-tg-hint"
        />
        <FormField
          id="admin-search"
          label={tx("Поиск по разделам")}
          labelClassName="sr-only"
        >
          {(field) => (
            <input
              {...field}
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={tx("Поиск: поручения, тексты, прокси…")}
              data-testid="admin-search"
              className="min-h-11 w-full rounded-tile bg-tg-secondary-bg pl-10 pr-3 text-sm text-tg-text placeholder:text-tg-hint"
            />
          )}
        </FormField>
      </div>

      {needle ? (
        <>
          <p className="px-1 text-xs text-tg-hint" role="status">
            {found.length > 0
              ? tx("Найдено: {count}", { count: found.length })
              : tx("Ничего не нашли — попробуй другое слово.")}
          </p>
          {found.length > 0 && (
            <div className="space-y-2">{found.map(card)}</div>
          )}
          {found.length === 0 && (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="min-h-11 w-full rounded-tile bg-tg-secondary-bg text-sm text-tg-link"
            >
              {tx("Сбросить поиск")}
            </button>
          )}
        </>
      ) : (
        <>
          {frequent.length > 0 && (
            <SectionGroup icon="clock" title={tx("Частое")}>
              {frequent.map(card)}
            </SectionGroup>
          )}
          {GROUPS.filter(
            (group) => !simple || SIMPLE_GROUPS.includes(group.title),
          ).map((group) => {
            const items = sections.filter(
              (s) => s.group === group.title && !lifted.has(s.id),
            );
            if (items.length === 0) return null;
            return (
              <SectionGroup
                key={group.title}
                icon={group.icon}
                title={tx(group.title)}
              >
                {items.map(card)}
              </SectionGroup>
            );
          })}
        </>
      )}
    </div>
  );
}

/**
 * Два ответа на вопрос «что мне сейчас нужно сделать?» (промпт §4.2).
 *
 * Почему не три. «Проверить, что горит» уже делает сводка `AttentionStrip`
 * выше: у неё есть числа и переходы в те же разделы. Третья равная кнопка
 * дублировала главный блок и размывала акцент (8laws: Хик, фон Ресторфа,
 * Миллер). Остались действия, которых в сводке нет: дать поручение и
 * пригласить человека. Возможности не потеряны — только убран повтор.
 */
function QuickActions({ onPick }: { onPick: (s: Section) => void }) {
  const { tx } = useTx();
  const actions: { id: Section; icon: IconName; label: string }[] = [
    { id: "admin-tasks", icon: "clipboard", label: tx("Дать поручение") },
    { id: "invitations", icon: "send", label: tx("Пригласить сотрудника") },
  ];
  return (
    <section aria-label={tx("Что будем делать?")} data-testid="admin-quick-actions">
      <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-tg-hint">
        {tx("Что будем делать?")}
      </h2>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {actions.map((action) => (
          <button
            key={action.id}
            type="button"
            onClick={() => onPick(action.id)}
            className="flex min-h-11 items-center gap-2 rounded-tile bg-tg-secondary-bg px-3 text-left text-sm font-medium text-tg-text press"
          >
            <Icon
              name={action.icon}
              size={18}
              className="shrink-0 text-tg-link"
            />
            <span className="truncate">{action.label}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function SectionGroup({
  icon,
  title,
  children,
}: {
  icon: IconName;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="border-t border-tg-hint/15 pt-3 first:border-t-0 first:pt-0">
      <div className="mb-2 flex items-center gap-2 px-1">
        <Icon name={icon} size={18} className="text-tg-hint" />
        <span className="text-xs font-semibold uppercase tracking-wide text-tg-hint">
          {title}
        </span>
      </div>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function Card({
  icon,
  title,
  subtitle,
  onClick,
  badge,
}: {
  icon: IconName;
  title: string;
  subtitle: string;
  onClick: () => void;
  /** Опц. счётчик справа; >0 → красный. */
  badge?: number;
}) {
  // §10: на ПК карточка приподнимается под курсором (`.lift` живёт внутри
  // `@media (hover: hover)`), на телефоне остаётся только отклик нажатия.
  return (
    <button
      type="button"
      onClick={onClick}
      className="lift flex w-full items-center gap-3 rounded-card bg-tg-secondary-bg/60 p-3 text-left press"
    >
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-tile bg-tg-bg/60 text-tg-text">
        <Icon name={icon} size={22} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-tg-text">{title}</div>
        <div className="truncate text-xs text-tg-hint">{subtitle}</div>
      </div>
      {badge !== undefined && badge > 0 && (
        <div className="flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-status-busy px-1.5 text-xs font-semibold tabular-nums text-white">
          {badge}
        </div>
      )}
      <div className="flex items-center text-tg-hint"><Icon name="chevron" size={16} /></div>
    </button>
  );
}
