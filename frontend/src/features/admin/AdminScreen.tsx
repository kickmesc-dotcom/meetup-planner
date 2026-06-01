import { ReactNode, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  fetchRandomPhrasesPool,
  triggerRandomPhrases,
} from "@/api/admin";
import type { User } from "@/types";
import { haptic } from "@/tg/webapp";
import ChukhanScreen from "./ChukhanScreen";
import LoserScreen from "./loser/LoserScreen";
import ScheduledPublicationsScreen from "./ScheduledPublicationsScreen";
import RandomPhrasesScheduleScreen from "./RandomPhrasesScheduleScreen";
import RandomPhrasesGeneratorScreen from "./RandomPhrasesGeneratorScreen";
import AutoLoserScreen from "./AutoLoserScreen";
import HistoryScreen from "./HistoryScreen";
import BirthdaysScreen from "./BirthdaysScreen";
import CalendarSettingsScreen from "./CalendarSettingsScreen";
import PollPresetsScreen from "./PollPresetsScreen";
import ProxyScreen from "./ProxyScreen";
import GamesScreen from "./GamesScreen";
import ZaebalSettingsScreen from "./ZaebalSettingsScreen";
import IntervalsScreen from "./IntervalsScreen";
import BotPauseBar from "./BotPauseBar";
import JobsQueueScreen from "./JobsQueueScreen";

type Section =
  | "root"
  | "chukhan"
  | "loser"
  | "scheduled-pubs"
  | "rp-schedule"
  | "rp-generator"
  | "autoloser"
  | "history"
  | "birthdays"
  | "calendar-settings"
  | "poll-presets"
  | "proxy"
  | "games"
  | "zaebal"
  | "intervals"
  | "jobs";

interface Props {
  users: User[];
}

export default function AdminScreen({ users }: Props) {
  const [section, setSection] = useState<Section>("root");
  const [poolOpen, setPoolOpen] = useState(false);

  const runPhrases = useMutation({
    mutationFn: triggerRandomPhrases,
    onSuccess: () => haptic("success"),
    onError: () => haptic("error"),
  });

  const pool = useQuery({
    queryKey: ["admin", "rp-pool"],
    queryFn: fetchRandomPhrasesPool,
    enabled: poolOpen,
    staleTime: 30_000,
  });

  const back = () => setSection("root");

  if (section === "chukhan") return <ChukhanScreen users={users} onBack={back} />;
  if (section === "loser") return <LoserScreen users={users} onBack={back} />;
  if (section === "scheduled-pubs") return <ScheduledPublicationsScreen onBack={back} />;
  if (section === "rp-schedule") return <RandomPhrasesScheduleScreen onBack={back} />;
  if (section === "rp-generator") return <RandomPhrasesGeneratorScreen onBack={back} />;
  if (section === "autoloser") return <AutoLoserScreen onBack={back} />;
  if (section === "history") return <HistoryScreen users={users} onBack={back} />;
  if (section === "birthdays") return <BirthdaysScreen onBack={back} />;
  if (section === "calendar-settings") return <CalendarSettingsScreen onBack={back} />;
  if (section === "poll-presets") return <PollPresetsScreen onBack={back} />;
  if (section === "proxy") return <ProxyScreen onBack={back} />;
  if (section === "games") return <GamesScreen onBack={back} />;
  if (section === "zaebal") return <ZaebalSettingsScreen onBack={back} />;
  if (section === "intervals") return <IntervalsScreen onBack={back} />;
  if (section === "jobs") return <JobsQueueScreen onBack={back} />;

  const select = (s: Section) => {
    haptic("selection");
    setSection(s);
  };

  return (
    <div className="flex-1 overflow-y-auto p-3 space-y-4">
      {/* GHG6 E11: статус глобальной паузы — sticky-плашка при active, иначе
          компактная полоска «в эфире» с кнопкой инициации паузы. */}
      <BotPauseBar />

      {/* ⚡ Quick actions
          GHG6 D4: убрали «Крутануть лоха» — он игнорил cooldown и не показывал recent;
          force-reroll переехал в подраздел «Лох». «Прогон фразы» доступен и тут,
          и из главной (ActionBar внизу календаря). */}
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <SectionHeader icon="⚡" title="Быстрые действия" />

        <button
          type="button"
          disabled={runPhrases.isPending}
          onClick={() => {
            haptic("medium");
            runPhrases.mutate();
          }}
          className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-50 active:scale-[0.98] transition-transform"
        >
          {runPhrases.isPending ? "⏳ Постим…" : "🚀 Прогнать рандомную фразу сейчас"}
        </button>
        {runPhrases.isError && (
          <div className="mt-2 rounded-md bg-status-busy/10 p-2 text-xs text-status-busy">
            ⚠ {String((runPhrases.error as Error)?.message ?? runPhrases.error)}
          </div>
        )}
        {runPhrases.isSuccess && !runPhrases.isPending && (
          <div className="mt-2 rounded-md bg-status-free/10 p-2 text-xs text-status-free">
            ✓ Запустили — проверь чат.
          </div>
        )}

        <button
          type="button"
          onClick={() => {
            haptic("selection");
            setPoolOpen((v) => !v);
          }}
          className="mt-2 w-full min-h-9 rounded-lg bg-tg-bg/60 px-2 py-1.5 text-xs text-tg-text flex items-center justify-between active:scale-[0.99] transition-transform"
        >
          <span>📊 Пул фраз сейчас{pool.data ? ` (${pool.data.total_chunks})` : ""}</span>
          <span className="text-tg-hint">{poolOpen ? "▾" : "▸"}</span>
        </button>
        {poolOpen && (
          <div className="mt-2 rounded-md bg-tg-bg/40 p-2 text-xs">
            {pool.isPending ? (
              <div className="text-tg-hint">Считаем…</div>
            ) : pool.isError ? (
              <div className="text-status-busy">⚠ {String((pool.error as Error)?.message ?? pool.error)}</div>
            ) : pool.data ? (
              <>
                <div className="text-tg-hint mb-1">
                  За {pool.data.lookback_days} дн · всего {pool.data.total_chunks} кусков
                </div>
                <ul className="space-y-0.5">
                  {pool.data.rows.map((r) => (
                    <li
                      key={r.user_id}
                      className="flex items-center justify-between gap-2"
                    >
                      <span className="truncate text-tg-text">{r.display_name}</span>
                      <span
                        className={`tabular-nums ${
                          r.chunks_count === 0 ? "text-status-busy" : "text-tg-text"
                        }`}
                      >
                        {r.chunks_count}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
        )}
      </section>

      {/* GHG6 D4: новый порядок — прокси сразу после quick actions (самое важное),
          потом запланированные публикации, потом календарь, лох, чухан, история. */}
      <SectionGroup icon="🌐" title="Прокси">
        <Card
          icon="🌐"
          title="Прокси"
          subtitle="Пул прокси, индикаторы, парсер, авто-фолбэк"
          onClick={() => select("proxy")}
        />
      </SectionGroup>

      {/* GHG6 M6 (п.17): «Очередь задач» поднята СРАЗУ под Прокси — пользователь
          просил видеть её ближе к топу. Раньше та же таблица жила внутри
          ScheduledPublicationsScreen, теперь это отдельный экран с reschedule
          и skip-next кнопками. */}
      <SectionGroup icon="📋" title="Очередь задач">
        <Card
          icon="📋"
          title="Запланированные задачи"
          subtitle="APScheduler-job'ы + напоминания. ✎ изменить, ⏭ пропустить"
          onClick={() => select("jobs")}
        />
      </SectionGroup>

      <SectionGroup icon="⏰" title="Запланированные публикации">
        <Card
          icon="⏱️"
          title="Расписание задач"
          subtitle="Master-toggles, дефолты опросов, опросы в чате"
          onClick={() => select("scheduled-pubs")}
        />
        <Card
          icon="💬"
          title="Автопост рандомных фраз"
          subtitle="Расписание (N раз/день, фикс-времена, рандом-интервал)"
          onClick={() => select("rp-schedule")}
        />
        <Card
          icon="🧪"
          title="Генератор рандомных фраз"
          subtitle="Длина цитаты, глубина истории, шансы"
          onClick={() => select("rp-generator")}
        />
        <Card
          icon="👑"
          title="Лох дня"
          subtitle="Бот сам выбирает лоха в окне дня"
          onClick={() => select("autoloser")}
        />
        <Card
          icon="⏸"
          title="Пауза и /zaebal"
          subtitle="Порог голосов, длительности, авто-зэбал"
          onClick={() => select("zaebal")}
        />
      </SectionGroup>

      <SectionGroup icon="📅" title="Календарь">
        <Card
          icon="🆕"
          title="Вид календаря"
          subtitle="Новый таймлайн / legacy-вид (по умолчанию legacy)"
          onClick={() => select("calendar-settings")}
        />
        <Card
          icon="🎂"
          title="Дни рождения"
          subtitle="Дата + что напоминать по каждому"
          onClick={() => select("birthdays")}
        />
        <Card
          icon="🕒"
          title="Пресеты времени"
          subtitle="Слоты для опросов / авто-подбора (12-15, 15-18 …)"
          onClick={() => select("poll-presets")}
        />
      </SectionGroup>

      {/* GHG6 E6: номинации игр + голосование «Во что сыграем». Отдельный раздел,
          чтобы не путать с обычными meetup-полами. */}
      <SectionGroup icon="🎮" title="Игры">
        <Card
          icon="🗳"
          title="Номинации и голосование"
          subtitle="Добавить игру, запустить «Во что сыграем», follow-up «Когда»"
          onClick={() => select("games")}
        />
      </SectionGroup>

      <SectionGroup icon="🤡" title="Лох">
        <Card
          icon="🎲"
          title="Лох дня"
          subtitle="Force-reroll, история, шаблоны фраз"
          onClick={() => select("loser")}
        />
      </SectionGroup>

      <SectionGroup icon="💩" title="Чухан">
        <Card
          icon="⚖️"
          title="Чухан недели"
          subtitle="Веса, ре-ролл, история, шаблоны фраз"
          onClick={() => select("chukhan")}
        />
      </SectionGroup>

      <SectionGroup icon="📜" title="История">
        <Card
          icon="📜"
          title="Сводная история"
          subtitle="Чуханы недели + лохи дня в одном списке"
          onClick={() => select("history")}
        />
      </SectionGroup>

      {/* GHG6 I (п.16): единый линейный экран всех числовых/временных параметров
          расписания. Стоит самым нижним — «выставил и забыл», рубильники живут
          в «Запланированных публикациях». */}
      <SectionGroup icon="⏱" title="Интервалы">
        <Card
          icon="🎛"
          title="Интервалы и окна"
          subtitle="Тик напоминаний, частота автолоха, окна фраз и чухана"
          onClick={() => select("intervals")}
        />
      </SectionGroup>
    </div>
  );
}

function SectionHeader({ icon, title }: { icon: string; title: string }) {
  return (
    <div className="flex items-center gap-2 mb-2">
      <span className="text-base">{icon}</span>
      <span className="text-base font-semibold text-tg-text">{title}</span>
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
    <section className="border-t border-tg-hint/15 pt-3">
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
}: {
  icon: string;
  title: string;
  subtitle: string;
  onClick: () => void;
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
      <div className="text-tg-hint text-base">›</div>
    </button>
  );
}
