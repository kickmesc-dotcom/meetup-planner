import { ReactNode, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAdminTasks } from "@/api/hr";
import { fetchIssues } from "@/api/issues";
import type { User } from "@/types";
import { haptic } from "@/tg/webapp";
import AttentionScreen from "./AttentionScreen";
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
import AdminTasksScreen from "./AdminTasksScreen";
import Icon, { type IconName } from "@/components/Icon";
import { useUI } from "@/store/ui";

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
  | "attention"
  | "admin-tasks"
  | "journal"
  | "notifications"
  | "employees"
  | "invitations"
  | "checklists"
  | "training-plan"
  | "feed-settings"
  | "kpi"
  | "calendar-settings"
  | "birthdays"
  | "poll-presets"
  | "texts"
  | "intervals"
  | "proxy"
  | "jobs"
  | "space-restart";

/** GHG11(4): допустимые подразделы для deep-link из анонса фичи. */
const VALID_SECTIONS: Section[] = [
  "attention",
  "admin-tasks",
  "journal",
  "notifications",
  "employees",
  "invitations",
  "checklists",
  "training-plan",
  "feed-settings",
  "kpi",
  "calendar-settings",
  "birthdays",
  "poll-presets",
  "texts",
  "intervals",
  "proxy",
  "jobs",
  "space-restart",
];

const GROUP_PEOPLE = "Смена и люди";
const GROUP_RESULT = "Опыт и результат";
const GROUP_CALENDAR = "Календарь";
const GROUP_TEXTS = "Тексты";
const GROUP_SYSTEM = "Система";

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
    title: "Уведомления сотрудников",
    subtitle: "Что ушло и что запланировано; мьют всех алертов",
  },
  {
    id: "employees",
    group: GROUP_PEOPLE,
    icon: "team",
    title: "Пул сотрудников",
    subtitle: "Имя, должность, прогресс, увольнение и корзина",
  },
  {
    id: "invitations",
    group: GROUP_PEOPLE,
    icon: "send",
    title: "Приглашения",
    subtitle: "Ссылка с ролью и сроком — вход без Telegram",
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
    id: "kpi",
    group: GROUP_RESULT,
    icon: "award",
    title: "Опыт и сотрудник недели",
    subtitle: "Сколько стоит работа · рейтинг недели",
  },
  {
    id: "calendar-settings",
    group: GROUP_CALENDAR,
    icon: "calendar",
    title: "Вид календаря",
    subtitle: "Новый таймлайн / legacy-вид",
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
    title: "Пресеты времени",
    subtitle: "Слоты для опросов / авто-подбора (12-15, 15-18 …)",
  },
  {
    id: "texts",
    group: GROUP_TEXTS,
    icon: "edit",
    title: "Тексты приложения",
    subtitle: "Приветствие, подсказки и пустые состояния",
  },
  {
    id: "intervals",
    group: GROUP_SYSTEM,
    icon: "repeat",
    title: "Интервалы напоминаний",
    subtitle: "Как часто проверять очередь напоминаний",
  },
  {
    id: "jobs",
    group: GROUP_SYSTEM,
    icon: "clipboard",
    title: "Запланированные задачи",
    subtitle: "APScheduler-job'ы: изменить, пропустить",
  },
  {
    id: "proxy",
    group: GROUP_SYSTEM,
    icon: "globe",
    title: "Прокси",
    subtitle: "Пул прокси, индикаторы, авто-фолбэк",
  },
  {
    id: "space-restart",
    group: GROUP_SYSTEM,
    icon: "refresh",
    title: "Рестарт Space",
    subtitle: "Кнопка + расписание, если сеть зависла",
  },
];

const GROUPS: { title: string; icon: IconName }[] = [
  { title: GROUP_PEOPLE, icon: "team" },
  { title: GROUP_RESULT, icon: "award" },
  { title: GROUP_CALENDAR, icon: "calendar" },
  { title: GROUP_TEXTS, icon: "edit" },
  { title: GROUP_SYSTEM, icon: "admin" },
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

function topFrequent(usage: Record<string, number>): SectionDef[] {
  return SECTIONS.filter((s) => (usage[s.id] ?? 0) > 0)
    .sort((a, b) => (usage[b.id] ?? 0) - (usage[a.id] ?? 0))
    .slice(0, FREQUENT_LIMIT);
}

interface Props {
  users: User[];
}

export default function AdminScreen({ users }: Props) {
  void users;
  const [section, setSection] = useState<Section>("root");
  const [query, setQuery] = useState("");
  const [usage, setUsage] = useState<Record<string, number>>(readUsage);

  // GHG11(4): переход из анонса фичи — сразу открыть нужный подраздел.
  const pendingAdminSection = useUI((s) => s.pendingAdminSection);
  const setPendingAdminSection = useUI((s) => s.setPendingAdminSection);
  useEffect(() => {
    if (!pendingAdminSection) return;
    if (VALID_SECTIONS.includes(pendingAdminSection as Section)) {
      setSection(pendingAdminSection as Section);
    }
    setPendingAdminSection(null);
  }, [pendingAdminSection, setPendingAdminSection]);

  // Бейдж «требует внимания» — просроченные поручения + срочные проблемы.
  const tasks = useQuery({
    queryKey: ["admin", "tasks", "attention"],
    queryFn: () => fetchAdminTasks(),
    staleTime: 60_000,
  });
  const issues = useQuery({
    queryKey: ["issues", "attention"],
    queryFn: () => fetchIssues({ statuses: ["open", "in_progress"], limit: 50 }),
    staleTime: 60_000,
  });
  const attentionCount =
    (tasks.data ?? []).filter(
      (t) => t.is_overdue && t.status !== "done" && t.status !== "failed",
    ).length + (issues.data?.summary.attention ?? 0);

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
  if (section === "checklists") return <ChecklistSettingsScreen onBack={back} />;
  if (section === "training-plan") return <TrainingPlanScreen onBack={back} />;
  if (section === "feed-settings") return <FeedSettingsScreen onBack={back} />;
  if (section === "kpi") return <KpiScreen onBack={back} />;
  if (section === "calendar-settings") return <CalendarSettingsScreen onBack={back} />;
  if (section === "birthdays") return <BirthdaysScreen onBack={back} />;
  if (section === "poll-presets") return <PollPresetsScreen onBack={back} />;
  if (section === "texts") return <AppTextsScreen onBack={back} />;
  if (section === "intervals") return <IntervalsScreen onBack={back} />;
  if (section === "proxy") return <ProxyScreen onBack={back} />;
  if (section === "jobs") return <JobsQueueScreen onBack={back} />;
  if (section === "space-restart") return <SpaceRestartScreen onBack={back} />;

  const select = (s: Section) => {
    haptic("selection");
    const next = { ...usage, [s]: (usage[s] ?? 0) + 1 };
    setUsage(next);
    writeUsage(next);
    setSection(s);
  };

  const needle = query.trim().toLowerCase();
  const found = needle
    ? SECTIONS.filter((s) =>
        `${s.title} ${s.subtitle} ${s.group}`.toLowerCase().includes(needle),
      )
    : [];
  const frequent = needle ? [] : topFrequent(usage);
  const lifted = new Set(frequent.map((s) => s.id));
  const frequentCount = (s: Section) => (s === "attention" ? attentionCount : undefined);

  const card = (s: SectionDef) => (
    <Card
      key={s.id}
      icon={s.icon}
      title={s.title}
      subtitle={s.subtitle}
      onClick={() => select(s.id)}
      badge={frequentCount(s.id)}
    />
  );

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-4">
      <div className="relative">
        <Icon
          name="search"
          size={18}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-tg-hint"
        />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Поиск: поручения, тексты, прокси…"
          aria-label="Поиск по разделам"
          data-testid="admin-search"
          className="min-h-11 w-full rounded-tile bg-tg-secondary-bg pl-10 pr-3 text-sm text-tg-text placeholder:text-tg-hint"
        />
      </div>

      {needle ? (
        <>
          <p className="px-1 text-xs text-tg-hint" role="status">
            {found.length > 0
              ? `Найдено: ${found.length}`
              : "Ничего не нашли — попробуй другое слово."}
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
              Сбросить поиск
            </button>
          )}
        </>
      ) : (
        <>
          {frequent.length > 0 && (
            <SectionGroup icon="clock" title="Частое">
              {frequent.map(card)}
            </SectionGroup>
          )}
          {GROUPS.map((group) => {
            const items = SECTIONS.filter(
              (s) => s.group === group.title && !lifted.has(s.id),
            );
            if (items.length === 0) return null;
            return (
              <SectionGroup key={group.title} icon={group.icon} title={group.title}>
                {items.map(card)}
              </SectionGroup>
            );
          })}
        </>
      )}
    </div>
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
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-card bg-tg-secondary-bg/60 p-3 text-left transition-transform active:scale-[0.98]"
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
      <div className="text-base text-tg-hint">›</div>
    </button>
  );
}
