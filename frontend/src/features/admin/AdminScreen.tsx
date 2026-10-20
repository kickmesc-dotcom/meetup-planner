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
import EmployeesScreen from "./EmployeesScreen";
import FeedSettingsScreen from "./FeedSettingsScreen";
import IntervalsScreen from "./IntervalsScreen";
import JobsQueueScreen from "./JobsQueueScreen";
import JournalScreen from "./JournalScreen";
import KpiScreen from "./KpiScreen";
import NotificationsScreen from "./NotificationsScreen";
import PollPresetsScreen from "./PollPresetsScreen";
import ProxyScreen from "./ProxyScreen";
import SpaceRestartScreen from "./SpaceRestartScreen";
import TrainingPlanScreen from "./TrainingPlanScreen";
import AdminTasksScreen from "./AdminTasksScreen";
import { useUI } from "@/store/ui";

/**
 * Админка управляющего. Здесь только рабочие вещи: люди, смена, контроль,
 * календарь и системные экраны. Наследные шуточные разделы (лох/чухан/игры/
 * реакции/рандомные фразы/пауза) удалены вместе с модулями — их больше нет ни
 * в API, ни в боте.
 */
type Section =
  | "root"
  | "attention"
  | "admin-tasks"
  | "journal"
  | "notifications"
  | "employees"
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

interface Props {
  users: User[];
}

export default function AdminScreen({ users }: Props) {
  void users;
  const [section, setSection] = useState<Section>("root");

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
    setSection(s);
  };

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-4">
      <SectionGroup icon="🧑‍🍳" title="Смена и люди">
        <Card
          icon="🚨"
          title="Требует внимания"
          subtitle="Просроченные поручения и открытые проблемы"
          onClick={() => select("attention")}
          badge={attentionCount}
        />
        <Card
          icon="📝"
          title="Поручения"
          subtitle="Создать, назначить, срок с точностью до секунды"
          onClick={() => select("admin-tasks")}
        />
        <Card
          icon="🔔"
          title="Уведомления сотрудников"
          subtitle="Что ушло и что запланировано; мьют всех алертов"
          onClick={() => select("notifications")}
        />
        <Card
          icon="🧑‍🍳"
          title="Пул сотрудников"
          subtitle="Имя, должность, прогресс, увольнение и корзина"
          onClick={() => select("employees")}
        />
        <Card
          icon="🎓"
          title="Обучение и ставка"
          subtitle="Учебные и обычные смены по дням, полная/частичная ставка"
          onClick={() => select("training-plan")}
        />
        <Card
          icon="🗂"
          title="Журнал событий"
          subtitle="Поручения человеческим языком, включая автоматику"
          onClick={() => select("journal")}
        />
        <Card
          icon="📰"
          title="Вид ленты"
          subtitle="Компактный (миниатюры участников) / классический"
          onClick={() => select("feed-settings")}
        />
      </SectionGroup>

      <SectionGroup icon="🏅" title="Опыт и результат">
        <Card
          icon="🏅"
          title="Опыт и сотрудник недели"
          subtitle="Сколько стоит работа · рейтинг недели"
          onClick={() => select("kpi")}
        />
      </SectionGroup>

      <SectionGroup icon="📅" title="Календарь">
        <Card
          icon="🆕"
          title="Вид календаря"
          subtitle="Новый таймлайн / legacy-вид"
          onClick={() => select("calendar-settings")}
        />
        <Card
          icon="⚙️"
          title="Дни рождения и праздники"
          subtitle="Даты, поздравления и напоминания"
          onClick={() => select("birthdays")}
        />
        <Card
          icon="🕒"
          title="Пресеты времени"
          subtitle="Слоты для опросов / авто-подбора (12-15, 15-18 …)"
          onClick={() => select("poll-presets")}
        />
      </SectionGroup>

      <SectionGroup icon="✍️" title="Тексты">
        <Card
          icon="✍️"
          title="Тексты приложения"
          subtitle="Приветствие, подсказки и пустые состояния"
          onClick={() => select("texts")}
        />
      </SectionGroup>

      <SectionGroup icon="⚙️" title="Система">
        <Card
          icon="🎛"
          title="Интервалы напоминаний"
          subtitle="Как часто проверять очередь напоминаний"
          onClick={() => select("intervals")}
        />
        <Card
          icon="📋"
          title="Запланированные задачи"
          subtitle="APScheduler-job'ы: ✎ изменить, ⏭ пропустить"
          onClick={() => select("jobs")}
        />
        <Card
          icon="🌐"
          title="Прокси"
          subtitle="Пул прокси, индикаторы, авто-фолбэк"
          onClick={() => select("proxy")}
        />
        <Card
          icon="🔄"
          title="Рестарт Space"
          subtitle="Кнопка + расписание, если сеть зависла"
          onClick={() => select("space-restart")}
        />
      </SectionGroup>
    </div>
  );
}

function SectionGroup({
  icon,
  title,
  children,
}: {
  icon: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="border-t border-tg-hint/15 pt-3 first:border-t-0 first:pt-0">
      <div className="flex items-center gap-2 mb-2 px-1">
        <span className="text-base">{icon}</span>
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
  icon: string;
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
      className="w-full text-left rounded-xl bg-tg-secondary-bg/60 p-3 flex items-center gap-3 active:scale-[0.98] transition-transform"
    >
      <div className="w-10 h-10 rounded-lg bg-tg-bg/60 flex items-center justify-center text-2xl shrink-0">
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold text-tg-text">{title}</div>
        <div className="text-[11px] text-tg-hint truncate">{subtitle}</div>
      </div>
      {badge !== undefined && badge > 0 && (
        <div className="min-w-5 h-5 px-1.5 rounded-full bg-status-busy text-white text-[11px] font-semibold tabular-nums flex items-center justify-center shrink-0">
          {badge}
        </div>
      )}
      <div className="text-tg-hint text-base">›</div>
    </button>
  );
}
