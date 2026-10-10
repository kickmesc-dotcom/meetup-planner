/**
 * GHG11(9/13): колокольчик личных уведомлений в мини-аппе.
 *
 * Повод один — лайк твоего трека: в общий чат такое не уходит, а автору знать
 * надо. Колокольчик стоит в шапке ленты и показывает число непрочитанных.
 *
 * GHG11(13): раньше колокольчик раскрывался ПУСТЫМ листом на весь экран — и
 * когда лайков не было, выглядело это как «спрятали ленту и показали ничего».
 * Теперь колокольчик — это переключатель выдвижной панели ленты (`feedPanel`):
 * там же фильтры, действия и, ниже, список уведомлений. Панель ничего не
 * перекрывает — просто занимает свою высоту над лентой.
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
} from "@/api/game";
import { useUI } from "@/store/ui";

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

/** Общий запрос уведомлений: и бейдж в шапке, и список в панели читают его. */
export function useNotifications() {
  return useQuery({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: fetchNotifications,
    staleTime: 30_000,
  });
}

/**
 * GHG11(13): список уведомлений для панели ленты. Сам отмечает прочитанными,
 * когда его показали (пометка «прочитано» — не «сколько всего пришло»).
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

  return (
    <div data-testid="notifications-list" className="border-t border-tg-hint/10 px-3 py-2">
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-tg-hint">
        <span aria-hidden>🔔</span>
        Уведомления
      </div>
      {notes.isPending ? (
        <div className="mt-1 text-[11px] text-tg-hint">Загружаю…</div>
      ) : items.length === 0 ? (
        <div className="mt-1 text-[11px] text-tg-hint">
          Пока тихо. Здесь появятся лайки твоих треков в подборках.
        </div>
      ) : (
        <div className="mt-1.5 flex flex-col gap-1.5">
          {items.map((n) => (
            <div
              key={n.id}
              data-testid="notification-row"
              className={[
                "rounded-lg px-2.5 py-2 text-xs",
                n.read ? "bg-tg-bg/40" : "bg-tg-secondary-bg",
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
      )}
    </div>
  );
}

/**
 * GHG11(13): колокольчик-переключатель панели ленты.
 *
 * Бейдж — по-прежнему «сколько непрочитанных», но клик не открывает отдельный
 * экран, а выдвигает панель (`feedPanel`) под шапкой: фильтры, действия и
 * уведомления. Иконка остаётся колокольчиком — единственный «личный» вход.
 */
export default function NotificationsBell() {
  const feedPanel = useUI((s) => s.feedPanel);
  const toggleFeedPanel = useUI((s) => s.toggleFeedPanel);
  const notes = useNotifications();
  const unread = notes.data?.unread ?? 0;

  return (
    <button
      type="button"
      data-testid="notifications-bell"
      aria-expanded={feedPanel}
      aria-label={
        unread > 0
          ? `Панель ленты, непрочитанных уведомлений: ${unread}`
          : "Панель ленты: фильтры и уведомления"
      }
      onClick={toggleFeedPanel}
      className={[
        "relative shrink-0 rounded-full px-2 py-1 text-base transition-colors",
        feedPanel ? "bg-tg-secondary-bg" : "",
      ].join(" ")}
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
