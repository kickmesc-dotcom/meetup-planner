/**
 * GHG11(9): колокольчик личных уведомлений в мини-аппе.
 *
 * Первый (и пока единственный) повод — лайк твоего трека: в общий чат такое не
 * уходит, а автору знать надо. Колокольчик стоит в шапке ленты, показывает число
 * непрочитанных, а список раскрывается поверх экрана — уведомления не мешают
 * ленте и не требуют отдельной вкладки.
 *
 * Прочитанными отмечаем при открытии списка: бейдж — это «сколько нового», а не
 * «сколько всего пришло». Тексты собирает сервер, так что новые типы уведомлений
 * появятся на фронте без правок — здесь только иконка по `kind` и время.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchNotifications,
  readNotifications,
  type AppNotification,
} from "@/api/game";

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

export default function NotificationsBell() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const notes = useQuery({
    queryKey: NOTIFICATIONS_KEY,
    queryFn: fetchNotifications,
    staleTime: 30_000,
  });
  const markRead = useMutation({
    mutationFn: () => readNotifications({ all: true }),
    // Ответ сервера — готовое новое состояние: кладём его в кэш, без рефетча.
    onSuccess: (data) => qc.setQueryData(NOTIFICATIONS_KEY, data),
  });

  const unread = notes.data?.unread ?? 0;
  const items: AppNotification[] = notes.data?.items ?? [];

  useEffect(() => {
    if (open && unread > 0 && !markRead.isPending) markRead.mutate();
    // `markRead` пересоздаётся каждый рендер — следим только за открытием.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, unread]);

  return (
    <>
      <button
        type="button"
        data-testid="notifications-bell"
        aria-label={
          unread > 0 ? `Уведомления, непрочитанных: ${unread}` : "Уведомления"
        }
        onClick={() => setOpen(true)}
        className="relative shrink-0 rounded-full px-2 py-1 text-base"
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

      {open && (
        <div
          data-testid="notifications-sheet"
          className="absolute inset-0 z-30 flex flex-col gap-3 bg-tg-bg/95 p-3 backdrop-blur"
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">🔔 Уведомления</span>
            <button
              type="button"
              aria-label="Закрыть уведомления"
              onClick={() => setOpen(false)}
              className="rounded-full px-2 text-lg text-tg-hint"
            >
              ✕
            </button>
          </div>

          {notes.isPending ? (
            <div className="text-xs text-tg-hint">Загружаю…</div>
          ) : items.length === 0 ? (
            <div className="text-xs text-tg-hint">
              Пока тихо. Здесь появятся лайки твоих треков в подборках.
            </div>
          ) : (
            <div className="flex flex-1 flex-col gap-1.5 overflow-y-auto">
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
          )}
        </div>
      )}
    </>
  );
}
