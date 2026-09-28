/**
 * GHG10 Э5.5: экран игровой системы в админке.
 *
 * Зачем он нужен: рубильник `game.enabled` до этого жил только в БД, а проверить
 * новый ранг/ачивку можно было лишь SQL'ем. Здесь три вещи:
 *
 * 1. рубильник + список отладочных TG-id (кому гейтинг не указ);
 * 2. карточка игрока: ранг, опыт, собранные ачивки и накопители;
 * 3. отладка — ручная выдача ачивки, сброс (в т.ч. накопителей) и установка
 *    опыта абсолютным числом («поставь 800» → проверь иммунитет 9 ранга).
 *
 * Гейтинга по рангам тут нет: админ — это админ. Ручной опыт НЕ выставляет
 * уведомление о левел-апе, поэтому отладка не всплывает у игрока в профиле.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchGameAdmin,
  fetchGamePlayer,
  grantGameAchievement,
  resetGameAchievements,
  setGamePlayerXp,
  updateGameAdmin,
  type GamePlayerState,
} from "@/api/admin";
import type { User } from "@/types";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import { humanizeApiError } from "@/api/client";
import { Spinner } from "@/components/Spinner";
import SubScreen from "./SubScreen";

interface Props {
  users: User[];
  onBack: () => void;
}

const QUERY_KEY = ["admin", "game"] as const;

export default function GameScreen({ users, onBack }: Props) {
  const queryClient = useQueryClient();
  const state = useQuery({ queryKey: QUERY_KEY, queryFn: fetchGameAdmin });
  const [selected, setSelected] = useState<number | null>(null);
  const [code, setCode] = useState("");
  const [xpDraft, setXpDraft] = useState("");
  const [debugDraft, setDebugDraft] = useState<string | null>(null);

  const player = useQuery({
    queryKey: ["admin", "game", "player", selected],
    queryFn: () => fetchGamePlayer(selected as number),
    enabled: selected !== null,
  });

  const refreshPlayer = (data: GamePlayerState) => {
    queryClient.setQueryData(["admin", "game", "player", selected], data);
  };

  const toggleMut = useMutation({
    mutationFn: (enabled: boolean) => updateGameAdmin({ enabled }),
    onSuccess: () => {
      haptic("success");
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const debugMut = useMutation({
    mutationFn: (ids: number[]) => updateGameAdmin({ enabled: true, debug_tg_ids: ids }),
    onSuccess: () => {
      haptic("success");
      setDebugDraft(null);
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const grantMut = useMutation({
    mutationFn: () =>
      grantGameAchievement(selected as number, code.trim()),
    onSuccess: (data) => {
      haptic("success");
      setCode("");
      refreshPlayer(data);
      void showAlert(`Выдал: ${data.achievements.length} ачивок у игрока.`);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const resetMut = useMutation({
    mutationFn: (opts: { code?: string; counters?: boolean }) =>
      resetGameAchievements(
        selected as number,
        opts.code ? { code: opts.code, counters: opts.counters } : opts,
      ),
    onSuccess: (data) => {
      haptic("success");
      refreshPlayer(data);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const xpMut = useMutation({
    mutationFn: () => setGamePlayerXp(selected as number, Number(xpDraft)),
    onSuccess: (data) => {
      haptic("success");
      setXpDraft("");
      refreshPlayer(data);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const onToggle = async () => {
    if (!state.data || toggleMut.isPending) return;
    haptic("selection");
    const next = !state.data.enabled;
    const ok = await showConfirm(
      next
        ? "Включить игровую систему? Пойдут начисления опыта, ачивки и гейтинг по рангам."
        : "Выключить игровую систему? Опыт и ачивки перестанут начисляться, гейтинг по рангам снимется.",
    );
    if (!ok) return;
    toggleMut.mutate(next);
  };

  const onResetAll = async () => {
    haptic("selection");
    const ok = await showConfirm(
      "Сбросить ВСЕ ачивки игрока (и накопители)? Опыт останется как есть.",
    );
    if (!ok) return;
    resetMut.mutate({ counters: true });
  };

  const debugIds = state.data?.debug_tg_ids ?? [];

  return (
    <SubScreen title="🎮 Игровая система" subtitle="Рубильник, ачивки, отладка" onBack={onBack}>
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="text-sm font-semibold">Рубильник</div>
            <div className="text-[11px] text-tg-hint">
              Выключенный модуль молчит целиком: ни опыта, ни ачивок, ни гейтинга
            </div>
          </div>
          <button
            type="button"
            onClick={() => void onToggle()}
            disabled={state.isPending || toggleMut.isPending}
            className={[
              "shrink-0 rounded-lg px-3 py-2 text-sm font-medium active:scale-[0.98] disabled:opacity-60",
              state.data?.enabled
                ? "bg-status-busy/20 text-status-busy"
                : "bg-tg-button text-tg-button-text",
            ].join(" ")}
          >
            {toggleMut.isPending ? "…" : state.data?.enabled ? "Выключить" : "Включить"}
          </button>
        </div>
        <div className="text-[11px] text-tg-hint">
          Сейчас: {state.data?.enabled ? "включена" : "выключена"} ·{" "}
          {state.data?.players ?? 0} профилей · ачивок в каталоге:{" "}
          {state.data?.achievements_total ?? 0} · максимум {state.data?.max_level ?? 10} рангов
        </div>
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="text-sm font-semibold">Отладочные TG-id</div>
        <div className="text-[11px] text-tg-hint">
          Им ранговый гейтинг не указ (по умолчанию добавь свой id, иначе
          проверять новые функции придётся с 1 ранга)
        </div>
        <input
          value={debugDraft ?? debugIds.join(", ")}
          onChange={(e) => setDebugDraft(e.target.value)}
          placeholder="123456, 789012"
          inputMode="numeric"
          className="w-full rounded bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
        />
        <button
          type="button"
          onClick={() => {
            haptic("selection");
            const ids = (debugDraft ?? debugIds.join(", "))
              .split(/[,\s]+/)
              .map((s) => s.trim())
              .filter(Boolean)
              .map(Number)
              .filter((n) => Number.isFinite(n));
            debugMut.mutate(ids);
          }}
          disabled={debugDraft === null || debugMut.isPending}
          className="w-full rounded-lg bg-tg-button px-3 py-2 text-sm font-medium text-tg-button-text active:scale-[0.98] disabled:opacity-60"
        >
          Сохранить список
        </button>
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-2">
        <div className="text-sm font-semibold">Отладка игрока</div>
        <select
          value={selected ?? ""}
          onChange={(e) => {
            haptic("selection");
            setSelected(e.target.value ? Number(e.target.value) : null);
          }}
          className="w-full rounded bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
        >
          <option value="">— выбери участника —</option>
          {users.map((u) => (
            <option key={u.id} value={u.telegram_id}>
              {u.display_name}
            </option>
          ))}
        </select>

        {player.isPending && selected !== null && (
          <div className="text-xs text-tg-hint">
            <Spinner size={12} /> Считаем…
          </div>
        )}

        {player.data && (
          <>
            <div className="rounded-lg bg-tg-bg/50 p-2 text-xs">
              <div className="text-sm font-medium">
                {player.data.name} — {player.data.level}-й «{player.data.rank_name}»
              </div>
              <div className="text-tg-hint">
                {player.data.xp} XP
                {player.data.prestige > 0 ? ` · престиж ${player.data.prestige}` : ""} ·
                ачивок: {player.data.achievements.length}
              </div>
              {Object.keys(player.data.counters).length > 0 && (
                <div className="text-tg-hint">
                  накопители:{" "}
                  {Object.entries(player.data.counters)
                    .map(([k, v]) => `${k}=${v}`)
                    .join(", ")}
                </div>
              )}
              {player.data.achievements.length > 0 && (
                <div className="mt-1 break-words text-tg-hint">
                  {player.data.achievements.join(", ")}
                </div>
              )}
            </div>

            <div className="flex gap-2">
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="код ачивки (chin_up)"
                className="min-w-0 flex-1 rounded bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
              />
              <button
                type="button"
                onClick={() => {
                  haptic("selection");
                  grantMut.mutate();
                }}
                disabled={!code.trim() || grantMut.isPending}
                className="shrink-0 rounded-lg bg-tg-button px-3 py-2 text-xs font-medium text-tg-button-text disabled:opacity-60"
              >
                Выдать
              </button>
            </div>

            <div className="flex gap-2">
              <input
                value={xpDraft}
                onChange={(e) => setXpDraft(e.target.value.replace(/\D/g, "").slice(0, 6))}
                inputMode="numeric"
                placeholder="XP всего (напр. 800)"
                className="min-w-0 flex-1 rounded bg-tg-bg/60 px-2 py-1.5 text-sm text-tg-text"
              />
              <button
                type="button"
                onClick={() => {
                  haptic("selection");
                  xpMut.mutate();
                }}
                disabled={!xpDraft.trim() || xpMut.isPending}
                className="shrink-0 rounded-lg bg-tg-secondary-bg px-3 py-2 text-xs font-medium disabled:opacity-60"
              >
                Поставить
              </button>
            </div>

            <button
              type="button"
              onClick={() => void onResetAll()}
              disabled={resetMut.isPending}
              className="w-full rounded-lg bg-status-busy/15 px-3 py-2 text-xs font-medium text-status-busy active:scale-[0.98] disabled:opacity-60"
            >
              🧹 Сбросить ачивки и накопители
            </button>
          </>
        )}
      </section>
    </SubScreen>
  );
}
