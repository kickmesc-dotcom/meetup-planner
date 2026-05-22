import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchMe,
  fetchUiPrefs,
  fetchUsers,
  updateUiPrefs,
  type UiPrefs,
} from "./api/availability";
import CalendarView from "./features/calendar/CalendarView";
import MeetingsScreen from "./features/meetings/MeetingsScreen";
import PollsScreen from "./features/polls/PollsScreen";
import LeaderboardScreen from "./features/leaderboard/LeaderboardScreen";
import AdminScreen from "./features/admin/AdminScreen";
import TabBar from "./features/nav/TabBar";
import { useUI } from "./store/ui";
import { haptic } from "./tg/webapp";

export default function App() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: fetchMe });
  const users = useQuery({ queryKey: ["users"], queryFn: fetchUsers });
  const uiPrefs = useQuery({ queryKey: ["ui-prefs"], queryFn: fetchUiPrefs });
  const hideGreeting = useMutation({
    mutationFn: () => updateUiPrefs({ hide_greeting: true }),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ["ui-prefs"] });
      const prev = qc.getQueryData<UiPrefs>(["ui-prefs"]);
      qc.setQueryData<UiPrefs>(["ui-prefs"], { hide_greeting: true });
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

  if (me.isPending || users.isPending) {
    return (
      <div className="flex h-full flex-col p-4 gap-3 animate-pulse">
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
      <div className="p-6 text-status-busy">
        Ошибка авторизации: {String(me.error)}
      </div>
    );
  }

  if (users.isError || !users.data) {
    return <div className="p-6 text-status-busy">Не удалось загрузить участников</div>;
  }

  const meData = me.data!;
  const isAdmin = !!meData.is_admin;

  // Если переключились на admin без прав — мягко возвращаем на календарь.
  if (tab === "admin" && !isAdmin) {
    setTab("calendar");
  }

  const greetingHidden = uiPrefs.data?.hide_greeting === true;

  let content: React.ReactNode = null;
  if (tab === "calendar") {
    content = (
      <>
        {!greetingHidden && (
          <header className="relative px-4 py-3 border-b border-tg-secondary-bg pr-10">
            <div className="text-base font-medium">Привет, {meData.display_name} 👋</div>
            <div className="text-xs text-tg-hint">
              Не размечен день = считается{" "}
              <span className="text-status-busy">занятым</span>. Тапай по дате,
              чтобы открыть редактор.
            </div>
            <button
              type="button"
              onClick={() => {
                haptic("warning");
                hideGreeting.mutate();
              }}
              disabled={hideGreeting.isPending}
              aria-label="Скрыть приветствие"
              title="Не показывать в следующий раз"
              className="absolute top-2 right-2 min-h-8 min-w-8 rounded-md text-tg-hint hover:text-tg-text active:scale-95 transition-transform disabled:opacity-50"
            >
              ✕
            </button>
          </header>
        )}
        <main className="flex-1 overflow-hidden">
          <CalendarView users={users.data} meId={meData.id} />
        </main>
      </>
    );
  } else if (tab === "meetings") {
    content = (
      <>
        <header className="px-4 py-3 border-b border-tg-secondary-bg">
          <div className="text-base font-medium">🤝 Ближайшие встречи</div>
          <div className="text-xs text-tg-hint">
            На 3 месяца вперёд. Жми RSVP, чтобы остальные знали.
          </div>
        </header>
        <main className="flex-1 overflow-hidden flex flex-col">
          <MeetingsScreen users={users.data} meId={meData.id} />
        </main>
      </>
    );
  } else if (tab === "polls") {
    content = (
      <>
        <header className="px-4 py-3 border-b border-tg-secondary-bg">
          <div className="text-base font-medium">🗳️ Опросы</div>
          <div className="text-xs text-tg-hint">
            Голосование за слот встречи. Голосуй в TG-чате — результат тут.
          </div>
        </header>
        <main className="flex-1 overflow-hidden flex flex-col">
          <PollsScreen users={users.data} meId={meData.id} />
        </main>
      </>
    );
  } else if (tab === "leaderboard") {
    content = (
      <>
        <header className="px-4 py-3 border-b border-tg-secondary-bg">
          <div className="text-base font-medium">🏆 Топы</div>
          <div className="text-xs text-tg-hint">
            Кто чаще всех попадает в чуханы и лохи.
          </div>
        </header>
        <main className="flex-1 overflow-hidden flex flex-col">
          <LeaderboardScreen users={users.data} />
        </main>
      </>
    );
  } else if (tab === "admin") {
    content = (
      <>
        <header className="px-4 py-3 border-b border-tg-secondary-bg">
          <div className="text-base font-medium">⚙️ Админка</div>
          <div className="text-xs text-tg-hint">
            Только для {meData.display_name}-уровня админов.
          </div>
        </header>
        <main className="flex-1 overflow-hidden flex flex-col">
          <AdminScreen users={users.data} />
        </main>
      </>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {content}
      <TabBar isAdmin={isAdmin} />
    </div>
  );
}
