/**
 * GHG11(9/13/14/16): колокольчик личных уведомлений в мини-аппе.
 *
 * Повод один — лайк твоего трека: в общий чат такое не уходит, а автору знать
 * надо. Колокольчик стоит в шапке ленты и показывает число непрочитанных.
 *
 * Механика менялась трижды, и это важно помнить:
 * GHG11(13) — колокольчик раскрывал панель в потоке над лентой;
 * GHG11(14) — панель стала только уведомлениями (фильтры ушли в саму ленту),
 * но осталась тумблером: тот же колокольчик и выдвигал, и вдвигал её обратно;
 * GHG11(16) — тумблера НЕТ. Колокольчик только открывает нижний шит — тот же
 * язык, что у лоха, номинаций и фильтра участников («списки — в шит»). Лента
 * при этом не теряет высоту, а закрывать есть чем без поиска кнопки: подложка
 * (тап по затемнению), клавиша Esc и любое действие внутри. Отдельный крестик
 * не нужен — он был лекарством именно от механики «свернуть тем же колокольчиком».
 *
 * Прочитанными отмечаем при показе списка: бейдж — это «сколько нового».
 * Тексты собирает сервер, так что новые типы уведомлений появятся на фронте без
 * правок — здесь только иконка по `kind` и время.
 */
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchNotifications,
  readNotifications,
  type AppNotification,
} from "../../../api/game";
import { useUI } from "../../../store/ui";
import BottomSheet from "../../../features/actions/BottomSheet";

/** Ключ кэша уведомлений — один на всё приложение (колокольчик один). */
export const NOTIFICATIONS_KEY = ["notifications"] as const;

/** Иконка по типу уведомления; незнакомый тип не ломает строку. */
export function notificationIcon(kind: string): string {
  if (kind === "music_like") return "❤️";
  return "🔔";
}

/** «5 мин назад» / «вчера» — коротко, без библиотек и дат. */
export function relativeTime(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "";
  const at = new Date(iso).getTime();
  if (!Number.isFinite(at)) return "";
  const minutes = Math.floor(Math.max(0, now - at) / 60_000);
  if (minutes < 1) return "только что";
  if (minutes < 60) return `${minutes} мин назад`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ч назад`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "вчера" : `${days} дн. назад`;
}

/** Общий запрос уведомлений: и бейдж в шапке, и список в шите читают его. */
export function useNotifications() {
  return useQuery({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: fetchNotifications,
    staleTime: 30_000,
  });
}

/**
 * Список уведомлений. Сам отмечает прочитанными, когда его показали (пометка
 * «прочитано» — не «сколько всего пришло»). Заголовок и закрытие — на шите.
 */
export function NotificationsList() {
  const qc = useQueryClient();
  const notes = useNotifications();
  const markRead = useMutation({
    mutationFn: () => readNotifications({ all: true }),
    // Ответ сервера — готовое новое состояние: кладём его в кэш, без рефетча.
    onSuccess: (data) => qc.setQueryData(NOTIFICATIONS_KEY, data),
  });

  const unread = notes.data?.unread ?? 0;
  const items: AppNotification[] = notes.data?.items ?? [];

  useEffect(() => {
    if (unread > 0 && !markRead.isPending) markRead.mutate();
    // `markRead` пересоздаётся каждый рендер — следим только за числом.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unread]);

  if (notes.isPending) {
    return (
      <div data-testid="notifications-list" className="text-xs text-tg-hint">
        Загружаю…
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div data-testid="notifications-list" className="text-xs text-tg-hint">
        Пока тихо. Здесь появятся лайки твоих треков в подборках.
      </div>
    );
  }

  return (
    <div data-testid="notifications-list" className="flex flex-col gap-1.5">
      {items.map((n) => (
        <div
          key={n.id}
          data-testid="notification-row"
          className={[
            "rounded-lg px-2.5 py-2 text-xs",
            n.read ? "bg-tg-secondary-bg/50" : "bg-tg-secondary-bg",
          ].join(" ")}
        >
          <div className="flex items-start gap-1.5">
            <span>{notificationIcon(n.kind)}</span>
            <span className="min-w-0 flex-1 text-tg-text">{n.text}</span>
          </div>
          <div className="mt-0.5 text-[10px] text-tg-hint">
            {relativeTime(n.created_at)}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * GHG11(16): уведомления живут в нижнем шите — привычная мобильная поверхность
 * для списка. Шит закрывается подложкой, Esc и любым свайпом-вниз на системе;
 * колокольчик в этом не участвует.
 */
export function NotificationsSheet() {
  const close = useUI((s) => s.setShowNotificationsSheet);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  return (
    <BottomSheet title="🔔 Уведомления" onClose={() => close(false)}>
      <NotificationsList />
    </BottomSheet>
  );
}

/**
 * GHG11(16): колокольчик — только вход. Он открывает шит уведомлений и никогда
 * его не сворачивает: обратной дороги к той же кнопке нет по построению (шит
 * перекрывает шапку), а закрытие живёт в самом шите.
 *
 * Бейдж — по-прежнему «сколько непрочитанных». Фильтры ленты от колокольчика не
 * зависят вовсе.
 */
export default function NotificationsBell() {
  const open = useUI((s) => s.setShowNotificationsSheet);
  const notes = useNotifications();
  const unread = notes.data?.unread ?? 0;

  return (
    <button
      type="button"
      data-testid="notifications-bell"
      aria-haspopup="dialog"
      aria-label={
        unread > 0 ? `Уведомления, непрочитанных: ${unread}` : "Уведомления"
      }
      onClick={() => open(true)}
      className="relative shrink-0 rounded-full px-2 py-1 text-base transition-colors active:bg-tg-secondary-bg"
    >
      🔔
      {unread > 0 && (
        <span
          data-testid="notifications-badge"
          className="absolute -right-0.5 -top-0.5 rounded-full bg-status-busy px-1.5 text-[10px] font-semibold text-tg-bg"
        >
          {unread > 9 ? "9+" : unread}
        </span>
      )}
    </button>
  );
}
