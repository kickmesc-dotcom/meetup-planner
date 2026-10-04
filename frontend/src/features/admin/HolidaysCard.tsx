import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createHoliday,
  deleteHoliday,
  fetchHolidays,
} from "@/api/game";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert } from "@/tg/webapp";

/**
 * GHG11: пул праздников — переехал из профиля в админку и объединён с днями
 * рождения в едином экране «Настройки».
 *
 * Праздник — ежегодная дата + поздравление: в этот день +50 XP всему чату, а
 * бот постит поздравление. В админке право править есть всегда (админ — это
 * админ), поэтому гейт по рангу из профиля здесь не нужен.
 */
export default function HolidaysCard() {
  const queryClient = useQueryClient();
  const holidays = useQuery({ queryKey: ["game", "holidays"], queryFn: fetchHolidays });
  const [month, setMonth] = useState("");
  const [day, setDay] = useState("");
  const [message, setMessage] = useState("");

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: ["game", "holidays"] });

  const addMut = useMutation({
    mutationFn: () => createHoliday(Number(month), Number(day), message.trim()),
    onSuccess: () => {
      haptic("success");
      setMonth("");
      setDay("");
      setMessage("");
      invalidate();
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const removeMut = useMutation({
    mutationFn: (id: number) => deleteHoliday(id),
    onSuccess: () => {
      haptic("success");
      invalidate();
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const data = holidays.data;
  const ready = month.trim() && day.trim() && message.trim();

  return (
    <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
      <h2 className="text-base font-semibold">🎉 Праздники</h2>
      <div className="mb-2 text-xs text-tg-hint">
        В эти дни всем участникам капает +50 XP, а бот поздравляет в чате
      </div>

      {holidays.isError ? (
        <div className="py-1 text-xs text-status-busy">
          Не удалось загрузить список — попробуй позже.
        </div>
      ) : data?.items.length ? (
        <ul className="space-y-1">
          {data.items.map((h) => (
            <li key={h.id} className="flex items-center gap-2 text-sm">
              <span className="shrink-0 tabular-nums text-tg-hint">
                {String(h.day).padStart(2, "0")}.{String(h.month).padStart(2, "0")}
              </span>
              <span className="min-w-0 flex-1 truncate">{h.message}</span>
              <button
                type="button"
                onClick={() => {
                  haptic("selection");
                  removeMut.mutate(h.id);
                }}
                disabled={removeMut.isPending}
                className="shrink-0 rounded bg-tg-bg/60 px-2 py-1 text-xs text-status-busy active:scale-95 disabled:opacity-60"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div className="py-1 text-xs text-tg-hint">Пока ни одного праздника.</div>
      )}

      <div className="mt-3 space-y-2 border-t border-tg-bg/60 pt-2">
        <div className="flex gap-2">
          <input
            value={day}
            onChange={(e) => setDay(e.target.value.replace(/\D/g, "").slice(0, 2))}
            inputMode="numeric"
            placeholder="ДД"
            className="w-14 rounded bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
          />
          <input
            value={month}
            onChange={(e) => setMonth(e.target.value.replace(/\D/g, "").slice(0, 2))}
            inputMode="numeric"
            placeholder="ММ"
            className="w-14 rounded bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
          />
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value.slice(0, 120))}
            placeholder="Что за праздник"
            className="min-w-0 flex-1 rounded bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
          />
        </div>
        <button
          type="button"
          onClick={() => {
            haptic("selection");
            addMut.mutate();
          }}
          disabled={!ready || addMut.isPending}
          className="w-full rounded-lg bg-tg-button px-3 py-2 text-sm font-medium text-tg-button-text active:scale-[0.98] disabled:opacity-60"
        >
          + Добавить праздник
        </button>
      </div>
    </section>
  );
}
