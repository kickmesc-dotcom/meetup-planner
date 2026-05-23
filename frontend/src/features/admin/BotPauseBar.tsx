/**
 * GHG6 E11: панель управления глобальной паузой бота в админке.
 *
 * Два режима:
 * 1. Активная пауза: красная sticky-плашка с reason, live-таймером (до ends_at)
 *    и кнопкой «▶️ Снять паузу». Если ends_at=null — «бессрочно», таймера нет.
 * 2. Нет паузы: серая полоска «Бот в эфире» + кнопка «⏸ Поставить на паузу»,
 *    открывающая модалку с выбором длительности (1/3/7 дн или бессрочно).
 *
 * После старта/снятия паузы — invalidate `["admin","bot-pause"]` плюс
 * scheduled/reactions/zaebal-settings, потому что бэк во время паузы
 * перезаписывает master-toggles → false (apply_pause_overrides). При снятии
 * восстанавливает из snapshot — UI должен подтянуть новые значения.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchBotPauseCurrent,
  startBotPause,
  stopBotPause,
  type BotPauseState,
} from "@/api/admin";
import { humanizeApiError } from "@/api/client";
import { haptic, showAlert, showConfirm } from "@/tg/webapp";
import { Spinner } from "@/components/Spinner";

const REASON_LABEL: Record<string, string> = {
  manual_admin: "вручную из админки",
  zaebal_threshold: "/zaebal порог в чате",
  zaebal_vote: "/zaebal-vote большинством",
  auto_monthly: "авто-зэбал бота",
};

// Опросы статуса часто хочется иметь свежими — но при активной паузе
// длинноживущая (часы) ситуация. 30 секунд — компромисс: пользователь увидит
// снятие/старт ≤30с задержки, серверу не накладно.
const POLL_INTERVAL_MS = 30_000;

function formatRemaining(endsAt: string | null): string | null {
  if (!endsAt) return null;
  const ms = new Date(endsAt).getTime() - Date.now();
  if (ms <= 0) return "истекла";
  const totalSec = Math.floor(ms / 1000);
  const days = Math.floor(totalSec / 86400);
  const hours = Math.floor((totalSec % 86400) / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  const seconds = totalSec % 60;
  if (days > 0) return `${days}д ${hours}ч ${minutes}м`;
  if (hours > 0) return `${hours}ч ${minutes}м ${seconds}с`;
  if (minutes > 0) return `${minutes}м ${seconds}с`;
  return `${seconds}с`;
}

export default function BotPauseBar() {
  const qc = useQueryClient();

  const state = useQuery({
    queryKey: ["admin", "bot-pause"],
    queryFn: fetchBotPauseCurrent,
    refetchInterval: POLL_INTERVAL_MS,
    staleTime: 5_000,
  });

  // Тик каждую секунду для live-таймера. Дёшево — пересчёт строки в памяти.
  const [, setNowTick] = useState(0);
  useEffect(() => {
    if (!state.data?.active || !state.data.ends_at) return;
    const id = setInterval(() => setNowTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [state.data?.active, state.data?.ends_at]);

  const invalidateAffected = () => {
    // Pause-старт/стоп перезаписывает master-toggles (scheduled/reactions/
    // zaebal) — фронт должен подхватить новые значения.
    qc.invalidateQueries({ queryKey: ["admin", "bot-pause"] });
    qc.invalidateQueries({ queryKey: ["admin", "scheduled"] });
    qc.invalidateQueries({ queryKey: ["admin", "bot-reactions"] });
    qc.invalidateQueries({ queryKey: ["admin", "zaebal-settings"] });
  };

  const stopMut = useMutation({
    mutationFn: stopBotPause,
    onSuccess: () => {
      haptic("success");
      invalidateAffected();
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const startMut = useMutation({
    mutationFn: startBotPause,
    onSuccess: () => {
      haptic("warning");
      invalidateAffected();
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const [modalOpen, setModalOpen] = useState(false);

  if (state.isPending) {
    return (
      <div className="rounded-xl bg-tg-secondary-bg/40 p-3 text-xs text-tg-hint">
        Загрузка статуса паузы…
      </div>
    );
  }
  if (state.isError) {
    return (
      <div className="rounded-xl bg-status-busy/10 p-3 text-xs text-status-busy">
        ⚠ {humanizeApiError(state.error)}
      </div>
    );
  }

  const data = state.data as BotPauseState;

  if (data.active) {
    const remaining = formatRemaining(data.ends_at);
    const reasonLabel = data.reason
      ? REASON_LABEL[data.reason] || data.reason
      : "неизвестно";
    return (
      <div className="sticky top-0 z-10 -mx-3 -mt-3 mb-2 border-b border-status-busy/30 bg-status-busy/15 p-3">
        <div className="flex items-start gap-2">
          <span className="text-2xl shrink-0">⏸</span>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold text-tg-text">
              Бот на паузе
            </div>
            <div className="text-[11px] text-tg-hint">
              Причина: {reasonLabel}
            </div>
            {remaining ? (
              <div className="mt-1 text-xs tabular-nums text-tg-text">
                ⏱ Осталось: <b>{remaining}</b>
              </div>
            ) : (
              <div className="mt-1 text-xs text-tg-text">
                ⏱ <b>Бессрочно</b> — снимется только вручную
              </div>
            )}
          </div>
        </div>
        <button
          type="button"
          disabled={stopMut.isPending}
          onClick={async () => {
            haptic("warning");
            const ok = await showConfirm(
              "Снять паузу? Все master-toggles будут восстановлены из snapshot.",
            );
            if (!ok) return;
            stopMut.mutate();
          }}
          className="mt-2 w-full min-h-10 rounded-lg bg-tg-button px-3 py-2 text-sm font-medium text-tg-button-text disabled:opacity-50 active:scale-[0.98] transition-transform flex items-center justify-center gap-2"
        >
          {stopMut.isPending && <Spinner />}
          ▶️ Снять паузу
        </button>
      </div>
    );
  }

  // Нет активной паузы — кнопка инициации.
  return (
    <>
      <div className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-base">▶️</span>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-tg-text">
                Бот в эфире
              </div>
              <div className="text-[11px] text-tg-hint">
                Все master-toggle активны как настроено
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              haptic("selection");
              setModalOpen(true);
            }}
            className="shrink-0 min-h-9 rounded-lg bg-tg-bg/60 px-3 text-xs text-tg-text active:scale-[0.98] transition-transform"
          >
            ⏸ Пауза
          </button>
        </div>
      </div>
      {modalOpen && (
        <PauseDurationModal
          onCancel={() => setModalOpen(false)}
          onPick={(days) => {
            setModalOpen(false);
            startMut.mutate(days);
          }}
          pending={startMut.isPending}
        />
      )}
    </>
  );
}

interface PauseModalProps {
  onCancel: () => void;
  onPick: (days: number | null) => void;
  pending: boolean;
}

/**
 * Модалка выбора длительности паузы. Не использую WebApp.showPopup —
 * у него ограниченные варианты ответов (≤3 кнопки, нет кастомного содержимого).
 */
function PauseDurationModal({ onCancel, onPick, pending }: PauseModalProps) {
  const choices: { label: string; days: number | null }[] = [
    { label: "1 день", days: 1 },
    { label: "3 дня", days: 3 },
    { label: "7 дней", days: 7 },
    { label: "Бессрочно", days: null },
  ];
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-3">
      <div className="w-full max-w-sm rounded-xl bg-tg-bg p-4 shadow-xl">
        <div className="text-base font-semibold text-tg-text mb-1">
          ⏸ Поставить бота на паузу
        </div>
        <div className="text-[11px] text-tg-hint mb-3">
          На время паузы публикации в группе остановятся (автопост фраз, лох,
          чухан, реакции на reply/mention, дни рождения, авто-zaebal).
          Текущие значения настроек запомнятся и восстановятся после снятия.
        </div>
        <div className="space-y-2">
          {choices.map((c) => (
            <button
              key={c.label}
              type="button"
              disabled={pending}
              onClick={() => {
                haptic("medium");
                onPick(c.days);
              }}
              className="w-full min-h-10 rounded-lg bg-tg-secondary-bg/80 px-3 py-2 text-sm text-tg-text active:scale-[0.98] transition-transform disabled:opacity-50 flex items-center justify-between"
            >
              <span>{c.label}</span>
              <span className="text-tg-hint">›</span>
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => {
            haptic("light");
            onCancel();
          }}
          className="mt-3 w-full min-h-9 rounded-lg bg-tg-bg px-3 py-2 text-xs text-tg-link border border-tg-hint/20 active:scale-[0.98] transition-transform"
        >
          Отмена
        </button>
      </div>
    </div>
  );
}
