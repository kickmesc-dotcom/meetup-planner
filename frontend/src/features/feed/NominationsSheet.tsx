import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addNomination,
  fetchNominations,
  voteNomination,
} from "@/api/game";
import { haptic, showAlert } from "@/tg/webapp";
import { humanizeApiError } from "@/api/client";
import BottomSheet from "@/features/actions/BottomSheet";

/**
 * GHG11: номинации игр и голосование «во что сыграем» прямо в мини-аппе.
 *
 * Один выбор на игрока: повторный тап по своей номинации снимает голос.
 * Добавлять можно любую игру, пока не достигнут лимит активных номинаций.
 * Если фича `nominations` в режиме «только апп»/«и в чат, и в апп», сервер
 * сам дублирует активность в ленту активности.
 */
export default function NominationsSheet({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");

  const q = useQuery({
    queryKey: ["game-nominations"],
    queryFn: fetchNominations,
    staleTime: 15_000,
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["game-nominations"] });
    void qc.invalidateQueries({ queryKey: ["game-feed"] });
  };

  const vote = useMutation({
    mutationFn: (id: number) => voteNomination(id),
    onSuccess: () => {
      haptic("success");
      invalidate();
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const add = useMutation({
    mutationFn: (value: string) => addNomination(value),
    onSuccess: (res) => {
      haptic("success");
      setName("");
      qc.setQueryData(["game-nominations"], res);
      invalidate();
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const data = q.data;

  return (
    <BottomSheet title="🎮 Номинации" onClose={onClose}>
      {q.isPending ? (
        <div className="py-6 text-center text-sm text-tg-hint">Загружаем…</div>
      ) : q.isError ? (
        <div className="py-6 text-center text-sm text-status-busy">
          Не удалось загрузить номинации.
        </div>
      ) : !data?.enabled ? (
        <div className="rounded-xl bg-tg-secondary-bg p-4 text-center text-sm text-tg-hint">
          Номинации выключены.
        </div>
      ) : (
        <>
          <div className="text-xs text-tg-hint">
            Голосуй за то, во что хотите сыграть. Повторный тап снимает голос.
          </div>

          <ul className="mt-3 space-y-1.5">
            {data.items.length === 0 && (
              <li className="rounded-xl bg-tg-secondary-bg/50 px-3 py-3 text-center text-sm text-tg-hint">
                Пока ничего не номинировано — предложи игру первым.
              </li>
            )}
            {data.items.map((n) => {
              const mine = data.my_vote_id === n.id;
              return (
                <li key={n.id}>
                  <button
                    type="button"
                    disabled={vote.isPending}
                    onClick={() => {
                      haptic("selection");
                      vote.mutate(n.id);
                    }}
                    className={[
                      "flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left transition-colors disabled:opacity-60",
                      mine
                        ? "bg-tg-link/15 ring-1 ring-tg-link/50"
                        : "bg-tg-secondary-bg/50",
                    ].join(" ")}
                  >
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">
                      {n.name}
                    </span>
                    <span
                      className={[
                        "shrink-0 rounded-full px-2 py-0.5 text-xs tabular-nums",
                        mine ? "bg-tg-link text-white" : "bg-tg-secondary-bg text-tg-hint",
                      ].join(" ")}
                    >
                      {mine ? "✓ " : ""}
                      {n.votes}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          {data.can_add ? (
            <div className="mt-3 flex gap-1.5">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Название игры…"
                maxLength={80}
                className="min-w-0 flex-1 rounded-lg bg-tg-secondary-bg px-3 py-2 text-sm text-tg-text"
              />
              <button
                type="button"
                disabled={add.isPending || !name.trim()}
                onClick={() => {
                  haptic("light");
                  add.mutate(name.trim());
                }}
                className="shrink-0 rounded-lg bg-tg-button px-3 py-2 text-sm font-medium text-tg-button-text disabled:opacity-50"
              >
                {add.isPending ? "…" : "Номинировать"}
              </button>
            </div>
          ) : (
            <div className="mt-3 rounded-lg bg-tg-secondary-bg/60 px-3 py-2 text-center text-xs text-tg-hint">
              Достигнут лимит активных номинаций ({data.max_active}).
            </div>
          )}
        </>
      )}

      <button
        type="button"
        onClick={onClose}
        className="mt-4 w-full rounded-xl bg-tg-secondary-bg py-3 font-medium"
      >
        Закрыть
      </button>
    </BottomSheet>
  );
}
