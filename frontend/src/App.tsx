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
import ProfileScreen from "./features/profile/ProfileScreen";
import GuestProfileScreen from "./features/profile/GuestProfileScreen";
import FeedScreen from "./features/feed/FeedScreen";
import WelcomeBanner from "./features/welcome/WelcomeBanner";
import AdminScreen from "./features/admin/AdminScreen";
import TabBar from "./features/nav/TabBar";
import ErrorState from "./components/ErrorState";
import { PlayerBar, PlayerProvider } from "./components/GlobalPlayer";
import NotificationsBell from "./features/notifications/NotificationsBell";
import { useUI } from "./store/ui";
import { getStartParam, haptic } from "./tg/webapp";

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
      qc.setQueryData<UiPrefs>(["ui-prefs"], {
        welcome_format: prev?.welcome_format ?? "avatar",
        hide_greeting: true,
        muted_feed: prev?.muted_feed ?? [],
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
  // Э19: гостевой профиль (клик по аватарке на календаре) — оверлей поверх вкладок.
  const guestUserId = useUI((s) => s.guestUserId);
  const closeGuest = useUI((s) => s.closeGuest);

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
  const isAdmin = !!meData.is_admin;

  // Если переключились на admin без прав — мягко возвращаем на ленту.
  if (tab === "admin" && !isAdmin) {
    setTab("feed");
  }

  const greetingHidden = uiPrefs.data?.hide_greeting === true;

  let content: React.ReactNode = null;
  if (tab === "calendar") {
    content = (
      <>
        {/* GHG8 P4: приветствие с быстрой инфой по званиям (welcome-screen).
            Закрытие — confirm внутри баннера (P4.1.c), сама пометка —
            та же ui-prefs мутация что и раньше. */}
        {!greetingHidden && (
          <WelcomeBanner
            users={users.data}
            meName={meData.display_name}
            format={uiPrefs.data?.welcome_format ?? "avatar"}
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
        <header className="px-4 py-3 border-b border-tg-secondary-bg">
          <div className="text-base font-medium">🤝 Встречи и опросы</div>
          <div className="text-xs text-tg-hint">
            RSVP по встречам и голосования за слот — всё в одном месте.
          </div>
        </header>
        <main className="flex-1 overflow-hidden flex flex-col">
          <MeetingsPollsScreen users={users.data} meId={meData.id} />
        </main>
      </>
    );
  } else if (tab === "feed") {
    content = (
      <>
        {/* GHG11: заголовок ленты — ОДНОЙ строкой (раньше дублировался внутри
            FeedScreen). Сама лента ниже отдаёт строку управления. */}
        <header className="relative flex items-center gap-2 overflow-hidden border-b border-tg-secondary-bg px-4 py-2.5">
          <span className="shrink-0 text-base font-medium">🏆 Лента</span>
          <span className="min-w-0 flex-1 truncate text-xs text-tg-hint">
            Кто что открыл и с кем что случилось.
          </span>
          {/* GHG11(9): личные уведомления (лайки своих треков) — в шапке ленты. */}
          <NotificationsBell />
        </header>
        <main className="flex-1 overflow-hidden flex flex-col">
          <FeedScreen meId={meData.id} />
        </main>
      </>
    );
  } else if (tab === "profile") {
    content = (
      <>
        <header className="px-4 py-3 border-b border-tg-secondary-bg">
          <div className="text-base font-medium">👤 Профиль</div>
          <div className="text-xs text-tg-hint">
            Топы, история и настройки приветствия.
          </div>
        </header>
        <main className="flex-1 overflow-hidden flex flex-col">
          <ProfileScreen users={users.data} me={meData} />
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
    // DESIGN_SYSTEM §9: центрированная колонка 560px — на планшете/десктопе
    // приложение читается как мини-апп, а не растягивается на всю ширину.
    <PlayerProvider>
      <div className="relative mx-auto flex h-full w-full max-w-[560px] flex-col sm:border-x sm:border-tg-hint/10">
        {content}
        {/* GHG11(8): плеер подборки недели — в общем каркасе, поэтому играет
            поверх всех вкладок и не сбрасывается при переключении. */}
        <PlayerBar />
        <TabBar isAdmin={isAdmin} />
        {guestUserId !== null && (
          <GuestProfileScreen userId={guestUserId} onClose={closeGuest} />
        )}
      </div>
    </PlayerProvider>
  );
}
