import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addDays, format, startOfDay } from "date-fns";
import {
  autoPick,
  createAutoPickPoll,
  type AutoPickSlot,
} from "@/api/meetings";
import { fetchUsers } from "@/api/availability";
import { fetchPollPresetsPublic } from "@/api/admin";
import { useUI } from "@/store/ui";
import { haptic, showAlert } from "@/tg/webapp";
import { humanizeApiError } from "@/api/client";
import BottomSheet from "./BottomSheet";

export default function AutoPickSheet() {
  const close = () => useUI.getState().setShowAutoPickSheet(false);
  const [windowDays, setWindowDays] = useState(14);
  const [slots, setSlots] = useState<AutoPickSlot[] | null>(null);

  const usersQ = useQuery({ queryKey: ["users"], queryFn: fetchUsers, staleTime: 60_000 });
  const usersById = new Map((usersQ.data ?? []).map((u) => [u.id, u]));
  const presetsQ = useQuery({
    queryKey: ["poll-presets"],
    queryFn: fetchPollPresetsPublic,
    staleTime: 60_000,
  });
  const qc = useQueryClient();
  const [pollMsg, setPollMsg] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: () => {
      const start = startOfDay(new Date());
      return autoPick({
        window_start: start.toISOString(),
        window_end: addDays(start, windowDays).toISOString(),
        // Длительность/шаг игнорируются бэком (use_presets=true по умолчанию),
        // но в схеме обязательные поля → передаём заглушку.
        duration_minutes: 120,
        step_minutes: 60,
        top_n: 5,
      });
    },
    onSuccess: (resp) => {
      haptic("success");
      setSlots(resp.slots);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const pollMut = useMutation({
    mutationFn: () => {
      const start = startOfDay(new Date());
      return createAutoPickPoll({
        window_start: start.toISOString(),
        window_end: addDays(start, windowDays).toISOString(),
        duration_minutes: 120,
        step_minutes: 60,
        top_n: 3,
        question: "Когда соберёмся?",
        closes_in_hours: 24,
      });
    },
    onSuccess: () => {
      haptic("success");
      setPollMsg("📊 Опрос опубликован в чате — голосуйте.");
      qc.invalidateQueries({ queryKey: ["polls"] });
    },
    onError: (e) => {
      haptic("error");
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes("not_enough_slots")) {
        setPollMsg("Слотов меньше двух — расширь окно или подними пилюли.");
      } else {
        setPollMsg(`Ошибка: ${humanizeApiError(e)}`);
      }
    },
  });

  return (
    <BottomSheet title="Авто-подбор времени" onClose={close}>
      <div className="grid grid-cols-1 gap-2">
        <label className="text-sm">
          <div className="mb-1 text-xs text-tg-hint">Окно</div>
          <select
            value={windowDays}
            onChange={(e) => setWindowDays(Number(e.target.value))}
            className="w-full rounded-lg bg-tg-secondary-bg px-2 py-2"
          >
            <option value={7}>Неделя</option>
            <option value={14}>2 недели</option>
            <option value={30}>Месяц</option>
          </select>
        </label>
        {presetsQ.data && presetsQ.data.length > 0 && (
          <div className="rounded-lg bg-tg-secondary-bg/60 px-3 py-2 text-xs text-tg-hint">
            🕒 Слоты времени:{" "}
            <span className="text-tg-text">
              {presetsQ.data.map((p) => `${p.start}–${p.end}`).join(", ")}
            </span>
            <div className="mt-0.5 text-[10px]">
              Меняются в админке → «🕒 Пресеты времени».
            </div>
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={() => {
          haptic("light");
          mut.mutate();
        }}
        disabled={mut.isPending}
        className="mt-3 w-full rounded-xl bg-tg-button py-3 font-medium text-tg-button-text disabled:opacity-50"
      >
        {mut.isPending ? "Считаем…" : "Найти слоты"}
      </button>

      {slots && slots.length === 0 && (
        <div className="mt-3 text-center text-tg-hint">
          Нет подходящих слотов. Скажи всем разметить календарь.
        </div>
      )}

      {slots && slots.length > 0 && (
        <ul className="mt-3 space-y-2">
          {slots.map((s, i) => (
            <li key={i} className="rounded-xl bg-tg-secondary-bg p-3">
              <div className="flex items-baseline justify-between">
                <div className="font-medium">
                  {format(new Date(s.starts_at), "EEE d MMM, HH:mm")} →{" "}
                  {format(new Date(s.ends_at), "HH:mm")}
                </div>
                <div className="text-xs text-tg-hint">★ {s.score.toFixed(1)}</div>
              </div>
              <div className="mt-1 text-xs">
                <span className="text-status-free">
                  ✓ {s.available_user_ids.map((id) => usersById.get(id)?.display_name ?? id).join(", ") || "—"}
                </span>
                {s.maybe_user_ids.length > 0 && (
                  <span className="ml-2 text-status-maybe">
                    ? {s.maybe_user_ids.map((id) => usersById.get(id)?.display_name ?? id).join(", ")}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {slots && slots.length >= 2 && (
        <button
          type="button"
          onClick={() => {
            haptic("medium");
            setPollMsg(null);
            pollMut.mutate();
          }}
          disabled={pollMut.isPending}
          className="mt-3 w-full rounded-xl bg-status-maybe/20 py-3 font-medium text-tg-text disabled:opacity-50"
        >
          {pollMut.isPending ? "Публикуем…" : "📊 Опубликовать опрос топ-3"}
        </button>
      )}
      {pollMsg && (
        <div className="mt-2 text-center text-xs text-tg-hint">{pollMsg}</div>
      )}

      <button
        type="button"
        onClick={close}
        className="mt-4 w-full rounded-xl bg-tg-secondary-bg py-3 font-medium"
      >
        Закрыть
      </button>
    </BottomSheet>
  );
}
