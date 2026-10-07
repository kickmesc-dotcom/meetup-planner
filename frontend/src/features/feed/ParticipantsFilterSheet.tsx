/**
 * GHG11(7): фильтр ленты «по участникам».
 *
 * Отдельное всплывающее окно: чекбоксами выбираем, чьи события скрывать в СВОЕЙ
 * ленте. Вверху два мастер-пикера — «Все» (скрыть всех) и «Никто» (показать
 * всех). Своя галочка неснимаемая: свои события из ленты не выкидываются, иначе
 * лента «сломается» (сервер тоже защищается, но UX должен быть честным).
 *
 * Список хранится в персональных UI-настройках (`muted_feed`), поэтому фильтр
 * переживает перезапуск приложения и работает на любом устройстве.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchUsers, fetchUiPrefs, updateUiPrefs } from "@/api/availability";
import { Checkbox } from "@/components/Checkbox";
import { Spinner } from "@/components/Spinner";
import { haptic } from "@/tg/webapp";

export default function ParticipantsFilterSheet({
  meId,
  onClose,
}: {
  meId: number;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const usersQ = useQuery({
    queryKey: ["users"],
    queryFn: fetchUsers,
    staleTime: 5 * 60 * 1000,
  });
  const prefsQ = useQuery({ queryKey: ["ui-prefs"], queryFn: fetchUiPrefs });
  const save = useMutation({
    mutationFn: (next: number[]) => updateUiPrefs({ muted_feed: next }),
    onSuccess: (out) => {
      qc.setQueryData(["ui-prefs"], out);
      // Список изменился — лента должна немедленно пересобраться.
      void qc.invalidateQueries({ queryKey: ["game-feed"] });
    },
    onError: () => haptic("error"),
  });

  const muted = prefsQ.data?.muted_feed ?? [];
  const users = usersQ.data ?? [];
  const me = users.find((u) => u.id === meId);
  const others = users.filter((u) => u.id !== meId);
  const busy = save.isPending || !prefsQ.data;

  const toggle = (id: number, on: boolean) => {
    haptic("selection");
    save.mutate(on ? [...muted, id] : muted.filter((i) => i !== id));
  };
  // «Все»: скрываем всех, КРОМЕ себя. «Никто»: показываем всех.
  const muteAll = () => {
    haptic("medium");
    save.mutate(others.map((u) => u.id));
  };
  const muteNone = () => {
    haptic("medium");
    save.mutate([]);
  };

  return (
    <div className="absolute inset-0 z-50 flex flex-col bg-black/40" onClick={onClose}>
      <div
        className="mt-auto flex max-h-[80%] flex-col rounded-t-2xl bg-tg-bg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-tg-secondary-bg px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold">👥 Фильтр по участникам</div>
            <div className="text-[11px] text-tg-hint">
              Чьи события не показывать в моей ленте
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              haptic("light");
              onClose();
            }}
            aria-label="Закрыть фильтр"
            className="rounded-lg bg-tg-secondary-bg/70 px-3 py-1.5 text-sm text-tg-text"
          >
            Готово
          </button>
        </div>

        {/* Мастер-пикеры: вверху, как просили. */}
        <div className="flex gap-2 border-b border-tg-secondary-bg px-4 py-2">
          <button
            type="button"
            onClick={muteAll}
            disabled={busy}
            className="flex-1 rounded-lg bg-tg-secondary-bg/70 py-2 text-xs font-semibold text-tg-text active:scale-[0.98] disabled:opacity-50"
          >
            Все
          </button>
          <button
            type="button"
            onClick={muteNone}
            disabled={busy}
            className="flex-1 rounded-lg bg-tg-secondary-bg/70 py-2 text-xs font-semibold text-tg-text active:scale-[0.98] disabled:opacity-50"
          >
            Никто
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2">
          {usersQ.isPending || !prefsQ.data ? (
            <div className="flex items-center gap-2 py-4 text-sm text-tg-hint">
              <Spinner size={14} /> Загружаем…
            </div>
          ) : (
            <ul className="divide-y divide-tg-bg/40">
              {me && (
                <li className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm text-tg-text">
                      {me.display_name}
                    </div>
                    <div className="text-[10px] text-tg-hint">
                      Это ты — свои события видны всегда
                    </div>
                  </div>
                  <Checkbox checked disabled onChange={() => {}} />
                </li>
              )}
              {others.map((u) => (
                <li
                  key={u.id}
                  className="flex items-center justify-between gap-3 py-2"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <div
                      className="h-7 w-7 shrink-0 overflow-hidden rounded-full bg-tg-secondary-bg text-center text-[11px] leading-7 text-white"
                      style={{ background: u.color_hex ?? "#888" }}
                    >
                      {u.avatar_url ? (
                        <img
                          src={u.avatar_url}
                          alt=""
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        u.display_name[0]
                      )}
                    </div>
                    <span className="truncate text-sm text-tg-text">
                      {u.display_name}
                    </span>
                  </div>
                  <Checkbox
                    checked={muted.includes(u.id)}
                    disabled={busy}
                    onChange={(on) => toggle(u.id, on)}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
