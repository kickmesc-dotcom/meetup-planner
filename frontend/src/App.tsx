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
import MeetingsScreen from "./features/meetings/MeetingsScreen";
import PollsScreen from "./features/polls/PollsScreen";
import ProfileScreen from "./features/profile/ProfileScreen";
import GuestProfileScreen from "./features/profile/GuestProfileScreen";
import WelcomeBanner from "./features/welcome/WelcomeBanner";
import AdminScreen from "./features/admin/AdminScreen";
import TabBar from "./features/nav/TabBar";
import ErrorState from "./components/ErrorState";
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

  // GHG10 (Э4.2): анонс ачивки в чате ведёт по deep link на «свои ачивки».
  // Открываем профиль — там живут ранг и лист ачивок (наполнение — Э5).
  useEffect(() => {
    if (getStartParam() === "achievements") setTab("profile");
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

  // Если переключились на admin без прав — мягко возвращаем на календарь.
  if (tab === "admin" && !isAdmin) {
    setTab("calendar");
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
    <div className="relative mx-auto flex h-full w-full max-w-[560px] flex-col sm:border-x sm:border-tg-hint/10">
      {content}
      <TabBar isAdmin={isAdmin} />
      {guestUserId !== null && (
        <GuestProfileScreen userId={guestUserId} onClose={closeGuest} />
      )}
    </div>
  );
}
