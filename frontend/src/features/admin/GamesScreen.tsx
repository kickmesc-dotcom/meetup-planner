import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  addGameNomination,
  createGamesPoll,
  fetchGameNominations,
  removeGameNomination,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { ListSkeleton } from "@/components/Skeleton";
import { Spinner } from "@/components/Spinner";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import SubScreen from "./SubScreen";

interface Props {
  onBack: () => void;
}

/**
 * GHG6 E6 — управление номинированными играми и запуск голосования
 * «Во что сыграем». Опционально follow-up «Когда играем» — создаётся
 * автоматически после закрытия первого полла, если включён чекбокс.
 */
export default function GamesScreen({ onBack }: Props) {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["admin", "games"],
    queryFn: fetchGameNominations,
  });

  const [name, setName] = useState("");
  const [timeoutHours, setTimeoutHours] = useState(24);
  const [followUp, setFollowUp] = useState(true);
  // G2.8: чекбокс «📌 Закрепить опрос». Дефолт — false; серверный дефолт из
  // admin_config.polls.pin_default подмешивается ТОЛЬКО когда поле опущено
  // (null). Если пользователь явно тыкнул чекбокс — отправляем булево; иначе
  // null → бэк подставит свой дефолт. Чтобы реализовать «нетронутое»
  // состояние с минимумом UI-сложности, держим стейт как boolean (default
  // false) и шлём false без особой магии: сервер хранит false как
  // «явно не пиним», тоже валидно. Когда сделаем G2.10/G3.6, добавим
  // подгрузку дефолта и установку начального значения чекбокса оттуда.
  const [pinPoll, setPinPoll] = useState(false);

  const add = useMutation({
    mutationFn: addGameNomination,
    onSuccess: () => {
      haptic("success");
      setName("");
      qc.invalidateQueries({ queryKey: ["admin", "games"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const remove = useMutation({
    mutationFn: removeGameNomination,
    onSuccess: () => {
      haptic("success");
      qc.invalidateQueries({ queryKey: ["admin", "games"] });
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const startPoll = useMutation({
    mutationFn: createGamesPoll,
    onSuccess: (r) => {
      haptic("success");
      void showAlert(
        `🗳 Голосование запущено: ${r.options_count} вариантов, закрытие через ${
          timeoutHours
        }ч.${r.follow_up_when ? " Follow-up «Когда играем» — после закрытия." : ""}`,
      );
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const items = list.data?.items ?? [];
  const maxActive = list.data?.max_active ?? 10;
  const canAdd = items.length < maxActive;

  const onAdd = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    haptic("medium");
    add.mutate(trimmed);
  };

  const onRemove = async (id: number, gameName: string) => {
    const ok = await showConfirm(`Удалить «${gameName}» из номинаций?`);
    if (!ok) return;
    haptic("warning");
    remove.mutate(id);
  };

  const onStartPoll = async () => {
    if (items.length < 2) {
      void showAlert("Нужно минимум 2 номинации для голосования.");
      return;
    }
    const msg = followUp
      ? `Запустить голосование «Во что сыграем» на ${timeoutHours}ч + follow-up «Когда играем»?`
      : `Запустить голосование «Во что сыграем» на ${timeoutHours}ч?`;
    const ok = await showConfirm(msg);
    if (!ok) return;
    haptic("medium");
    startPoll.mutate({
      timeout_hours: timeoutHours,
      follow_up_when: followUp,
      pin: pinPoll,
    });
  };

  return (
    <SubScreen title="🎮 Игры" subtitle="Номинации + голосование «Во что сыграем»" onBack={onBack}>
      <section className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-base">📋</span>
          <span className="text-base font-semibold">
            Номинации ({items.length}/{maxActive})
          </span>
        </div>

        {list.isPending ? (
          <ListSkeleton rows={3} />
        ) : list.isError ? (
          <div className="text-status-busy text-sm">
            ⚠ {humanizeApiError(list.error)}
          </div>
        ) : items.length === 0 ? (
          <div className="text-xs text-tg-hint">
            Пока пусто. Добавь хотя бы две игры — и можно запускать голосование.
          </div>
        ) : (
          <ul className="space-y-1.5">
            {items.map((it) => (
              <li
                key={it.id}
                className="flex items-center gap-2 rounded-md bg-tg-bg/40 px-2 py-2"
              >
                <span className="flex-1 text-sm text-tg-text truncate">
                  {it.name}
                </span>
                <button
                  type="button"
                  onClick={() => onRemove(it.id, it.name)}
                  disabled={remove.isPending}
                  className="min-h-8 min-w-8 rounded-md bg-status-busy/15 px-2 text-sm text-status-busy disabled:opacity-50 active:scale-95 transition-transform"
                  aria-label={`Удалить ${it.name}`}
                >
                  🗑
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-3 flex gap-2">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Например: Doom 2"
            maxLength={120}
            disabled={!canAdd || add.isPending}
            className="flex-1 rounded-md bg-tg-bg/70 px-2 py-2 text-sm text-tg-text outline-none border border-transparent focus:border-tg-link disabled:opacity-50"
            onKeyDown={(e) => {
              if (e.key === "Enter") onAdd();
            }}
          />
          <button
            type="button"
            onClick={onAdd}
            disabled={!canAdd || add.isPending || !name.trim()}
            className="min-h-10 px-3 rounded-md bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50 active:scale-95 transition-transform flex items-center gap-1"
          >
            {add.isPending ? <Spinner /> : "➕"}
            Добавить
          </button>
        </div>
        {!canAdd && (
          <div className="mt-2 text-[11px] text-tg-hint">
            Лимит {maxActive} активных. Удали что-нибудь, чтобы добавить новое.
          </div>
        )}
      </section>

      <section className="rounded-xl bg-tg-secondary-bg/60 p-3 space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-base">🗳</span>
          <span className="text-base font-semibold">
            Запустить голосование «Во что сыграем»
          </span>
        </div>

        <div>
          <div className="flex items-center justify-between text-xs text-tg-hint mb-1">
            <span>Длительность опроса</span>
            <span className="tabular-nums text-tg-text">{timeoutHours} ч</span>
          </div>
          <input
            type="range"
            min={12}
            max={24}
            step={1}
            value={timeoutHours}
            onChange={(e) => setTimeoutHours(parseInt(e.target.value, 10))}
            className="w-full"
          />
        </div>

        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={followUp}
            onChange={(e) => setFollowUp(e.target.checked)}
            className="mt-0.5"
          />
          <span className="text-sm text-tg-text">
            После победителя — follow-up «Когда играем»
            <div className="text-[11px] text-tg-hint">
              Второй опрос на 3 ближайших даты, победившая дата → запись в
              календарь с тегом «🎮».
            </div>
          </span>
        </label>

        {/* G2.8: чекбокс пина. Для follow-up «Когда играем» бэк наследует
            это же значение (см. services/games_poll.py: pinned проброс). */}
        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={pinPoll}
            onChange={(e) => setPinPoll(e.target.checked)}
            className="mt-0.5"
          />
          <span className="text-sm text-tg-text">
            📌 Закрепить опрос в чате
            <div className="text-[11px] text-tg-hint">
              Сразу после публикации бот пин-нёт сообщение с опросом
              (disable_notification=true). Follow-up «Когда играем» получит ту
              же опцию.
            </div>
          </span>
        </label>

        <button
          type="button"
          onClick={onStartPoll}
          disabled={startPoll.isPending || items.length < 2}
          className="w-full min-h-11 rounded-lg bg-tg-button py-2 text-sm font-medium text-tg-button-text disabled:opacity-50 active:scale-[0.98] transition-transform flex items-center justify-center gap-2"
        >
          {startPoll.isPending ? <Spinner /> : "🗳"}
          Запустить голосование
        </button>
      </section>
    </SubScreen>
  );
}
