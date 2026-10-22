import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  HANDOVER_STATUS_LABEL,
  acceptHandover,
  createHandover,
  fetchColleagues,
  fetchHandover,
  fetchHandoverPreview,
  fetchHandovers,
  rejectHandover,
  type HandoverBox,
  type HandoverStatus,
  type HrHandover,
  type HrHandoverItem,
} from "@/api/handovers";
import { humanizeApiError } from "@/api/client";
import BottomSheet from "@/features/actions/BottomSheet";
import ErrorState from "@/components/ErrorState";
import Icon, { type IconName } from "@/components/Icon";
import ChevronToggle from "@/components/ChevronToggle";
import { CardSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";
import { useUI } from "@/store/ui";

/**
 * Передача смены.
 *
 * Сдающий видит, что реально уйдёт следующему (открытые поручения и проблемы),
 * и отправляет карточку конкретному человеку. Принимающий подтверждает или
 * возвращает с причиной — сервер считает права, экран лишь показывает кнопки.
 */

const STATUS_CLASS: Record<HandoverStatus, string> = {
  sent: "bg-status-maybe/20 text-status-maybe",
  accepted: "bg-status-free/20 text-status-free",
  rejected: "bg-status-busy/20 text-status-busy",
};

const BOX_OPTIONS: { value: HandoverBox; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "incoming", label: "Мне" },
  { value: "outgoing", label: "Мои сдачи" },
];

function fmtMoment(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// P1.4: пункт передачи — «поручение» или «проблема». Раньше это были эмодзи,
// и в узкой строке они читались как часть названия.
function itemIcon(item: HrHandoverItem): IconName {
  return item.kind === "task" ? "check" : "alert";
}

export default function HandoversScreen() {
  const setTab = useUI((s) => s.setTab);
  const qc = useQueryClient();
  const [box, setBox] = useState<HandoverBox>("all");
  const [creating, setCreating] = useState(false);

  const handoversQ = useQuery({
    queryKey: ["handovers", box],
    queryFn: () => fetchHandovers(box),
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["handovers"] });
    void qc.invalidateQueries({ queryKey: ["handover"] });
  };

  if (handoversQ.isError) {
    return (
      <ErrorState
        error={handoversQ.error}
        onRetry={() => void handoversQ.refetch()}
        title="Передача смены не открылась"
      />
    );
  }

  const data = handoversQ.data;
  const summary = data?.summary;
  const items = data?.items ?? [];

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-tg-secondary-bg px-4 py-3">
        <div className="flex items-start gap-2">
          <button
            type="button"
            onClick={() => {
              haptic("light");
              setTab("tasks");
            }}
            className="-ml-1 min-h-11 min-w-11 rounded-tile text-lg text-tg-hint"
            aria-label="Назад к задачам"
          >
            ‹
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="flex items-center gap-2 text-lg font-semibold text-tg-text">
              <Icon name="send" size={18} />
              Передача смены
            </h1>
            <p className="mt-0.5 text-xs text-tg-hint">
              {summary
                ? summary.pending > 0
                  ? `Тебе передали смену: ${summary.pending} — нужно подтвердить.`
                  : "Чужих хвостов на тебе нет. Сдай свои, когда уходишь."
                : "Что осталось открытым и кому это передали."}
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              haptic("light");
              setCreating(true);
            }}
            className="min-h-9 shrink-0 rounded-tile bg-tg-button px-3 text-xs font-medium text-tg-button-text"
          >
            Сдать смену
          </button>
        </div>

        <div className="mt-3 flex gap-1.5">
          {BOX_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => {
                haptic("light");
                setBox(option.value);
              }}
              className={[
                "min-h-8 rounded-full px-3 text-xs transition-colors",
                box === option.value
                  ? "bg-tg-button text-tg-button-text"
                  : "bg-tg-secondary-bg text-tg-hint",
              ].join(" ")}
            >
              {option.label}
              {option.value === "incoming" && summary?.pending
                ? ` · ${summary.pending}`
                : ""}
            </button>
          ))}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2.5">
        {handoversQ.isLoading && (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}

        {!handoversQ.isLoading && items.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center">
            <Icon name="send" size={34} className="text-tg-hint" />
            <div className="mt-2 text-sm font-medium text-tg-text">
              Передач пока нет
            </div>
            <div className="mt-1 text-xs text-tg-hint">
              Нажми «Сдать смену»: приложение соберёт открытые поручения и
              проблемы, а следующий человек подтвердит приём.
            </div>
          </div>
        )}

        {items.map((handover) => (
          <HandoverCard
            key={handover.id}
            handover={handover}
            onChanged={invalidate}
          />
        ))}
      </div>

      {creating && (
        <CreateHandoverSheet
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            invalidate();
            setBox("outgoing");
          }}
        />
      )}
    </div>
  );
}

function HandoverCard({
  handover,
  onChanged,
}: {
  handover: HrHandover;
  onChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  const detailQ = useQuery({
    queryKey: ["handover", handover.id],
    queryFn: () => fetchHandover(handover.id),
    enabled: expanded,
  });

  const acceptM = useMutation({
    mutationFn: () => acceptHandover(handover.id),
    onSuccess: () => {
      haptic("success");
      onChanged();
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const rejectM = useMutation({
    mutationFn: () => rejectHandover(handover.id, reason.trim()),
    onSuccess: () => {
      haptic("success");
      setRejecting(false);
      setReason("");
      onChanged();
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const busy = acceptM.isPending || rejectM.isPending;
  const card = detailQ.data ?? handover;

  return (
    <article className="rounded-card bg-tg-secondary-bg/60 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-tg-text">
            {handover.from_name ?? "—"} → {handover.to_name ?? "—"}
          </div>
          <div className="mt-0.5 text-xs text-tg-hint">
            смена {handover.shift_date} · {fmtMoment(handover.created_at)}
            {handover.department_name ? ` · ${handover.department_name}` : ""}
          </div>
        </div>
        <span
          className={[
            "shrink-0 rounded-full px-2 py-0.5 text-xs",
            STATUS_CLASS[handover.status],
          ].join(" ")}
        >
          {HANDOVER_STATUS_LABEL[handover.status]}
        </span>
      </div>

      <button
        type="button"
        onClick={() => {
          haptic("light");
          setExpanded((v) => !v);
        }}
        aria-expanded={expanded}
        className="mt-2 inline-flex min-h-8 items-center gap-1 rounded-tile bg-tg-bg/50 px-2.5 text-xs text-tg-hint"
      >
        {handover.items_count > 0
          ? `Открытых пунктов: ${handover.items_count}`
          : "Открытых пунктов нет"}
        <ChevronToggle open={expanded} size={12} />
      </button>

      {expanded && (
        <div className="mt-2 space-y-1.5">
          {detailQ.isLoading && <div className="text-xs text-tg-hint">Загружаю…</div>}
          {card.items.map((item) => (
            <div
              key={`${item.kind}-${item.ref_id ?? item.id}-${item.id}`}
              className="rounded-tile bg-tg-bg/50 px-2.5 py-1.5"
            >
              <div className="text-xs text-tg-text">
                <Icon name={itemIcon(item)} size={13} className="mr-1 inline-block align-[-2px] text-tg-hint" />
                {item.title}
              </div>
              <div className="mt-0.5 text-xs text-tg-hint">
                {item.status}
                {item.meta ? ` · ${item.meta}` : ""}
              </div>
            </div>
          ))}
          {!detailQ.isLoading && card.items.length === 0 && (
            <div className="text-xs text-tg-hint">
              На момент сдачи открытых пунктов не было.
            </div>
          )}
        </div>
      )}

      {handover.note && (
        <p className="mt-2 whitespace-pre-wrap break-words text-xs text-tg-text/90">
          {handover.note}
        </p>
      )}
      {handover.reject_reason && (
        <p className="mt-2 rounded-tile bg-status-busy/10 px-2.5 py-1.5 text-xs text-status-busy">
          Возвращено: {handover.reject_reason}
        </p>
      )}
      {handover.accepted_at && (
        <div className="mt-1 text-xs text-tg-hint">
          Принял(а): {handover.accepted_by_name ?? handover.to_name} ·{" "}
          {fmtMoment(handover.accepted_at)}
        </div>
      )}

      {handover.can_accept && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => acceptM.mutate()}
            className="min-h-10 rounded-tile bg-tg-button px-3 text-xs font-medium text-tg-button-text disabled:opacity-50"
          >
            Принять смену
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              haptic("light");
              setRejecting((v) => !v);
            }}
            className="min-h-10 rounded-tile bg-tg-secondary-bg px-3 text-xs font-medium text-tg-text disabled:opacity-50"
          >
            {rejecting ? "Отмена" : "Вернуть"}
          </button>
        </div>
      )}

      {rejecting && handover.can_reject && (
        <div className="mt-2">
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            maxLength={2000}
            placeholder="Почему не принимаешь? Без причины вернуть нельзя."
            className="w-full rounded-tile bg-tg-bg/60 p-2 text-sm text-tg-text"
          />
          <button
            type="button"
            disabled={rejectM.isPending || reason.trim().length === 0}
            onClick={() => rejectM.mutate()}
            className="mt-2 min-h-10 w-full rounded-tile bg-status-busy/20 text-xs font-medium text-status-busy disabled:opacity-50"
          >
            Вернуть с причиной
          </button>
        </div>
      )}
    </article>
  );
}

function CreateHandoverSheet({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [toId, setToId] = useState<number | null>(null);
  const [note, setNote] = useState("");

  const colleaguesQ = useQuery({
    queryKey: ["handover-colleagues"],
    queryFn: fetchColleagues,
  });
  const previewQ = useQuery({
    queryKey: ["handover-preview"],
    queryFn: fetchHandoverPreview,
  });

  const m = useMutation({
    mutationFn: () =>
      createHandover({ to_employee_id: toId as number, note: note.trim() || null }),
    onSuccess: () => {
      haptic("success");
      onCreated();
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const colleagues = colleaguesQ.data ?? [];

  return (
    <BottomSheet title="Сдать смену" onClose={onClose}>
      <div className="text-xs text-tg-hint">Кому передаёшь</div>
      {colleaguesQ.isLoading && (
        <div className="mt-1 text-xs text-tg-hint">Загружаю коллег…</div>
      )}
      {!colleaguesQ.isLoading && colleagues.length === 0 && (
        <div className="mt-1 text-xs text-status-busy">
          Некому передать: в отделе нет других активных сотрудников.
        </div>
      )}
      <div className="mt-1 flex flex-wrap gap-1.5">
        {colleagues.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => {
              haptic("light");
              setToId(c.id);
            }}
            className={[
              "min-h-9 rounded-full px-3 text-xs transition-colors",
              toId === c.id
                ? "bg-tg-button text-tg-button-text"
                : "bg-tg-secondary-bg text-tg-hint",
            ].join(" ")}
          >
            {c.display_name}
          </button>
        ))}
      </div>

      <div className="mt-3 text-xs text-tg-hint">
        Что уйдёт в сдачу
        {previewQ.data
          ? ` — поручений ${previewQ.data.tasks}, проблем ${previewQ.data.issues}`
          : ""}
      </div>
      <div className="mt-1 space-y-1.5">
        {previewQ.isLoading && (
          <div className="text-xs text-tg-hint">Собираю открытые пункты…</div>
        )}
        {(previewQ.data?.items ?? []).map((item) => (
          <div
            key={`${item.kind}-${item.ref_id ?? item.id}`}
            className="rounded-tile bg-tg-secondary-bg/60 px-2.5 py-1.5"
          >
            <div className="text-xs text-tg-text">
              <Icon name={itemIcon(item)} size={13} className="mr-1 inline-block align-[-2px] text-tg-hint" />
              {item.title}
            </div>
            <div className="mt-0.5 text-xs text-tg-hint">
              {item.status}
              {item.meta ? ` · ${item.meta}` : ""}
            </div>
          </div>
        ))}
        {previewQ.data && previewQ.data.items.length === 0 && (
          <div className="text-xs text-tg-hint">
            Открытых пунктов нет — передашь только заметку.
          </div>
        )}
      </div>

      <label className="mt-3 block text-xs text-tg-hint">
        Заметка следующему (необязательно)
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          maxLength={2000}
          placeholder="Что важно знать: ключи, гости, недоделанное"
          className="mt-1 w-full rounded-tile bg-tg-secondary-bg p-2 text-sm text-tg-text"
        />
      </label>

      <button
        type="button"
        disabled={m.isPending || toId === null}
        onClick={() => m.mutate()}
        className="mt-4 min-h-11 w-full rounded-tile bg-tg-button text-sm font-medium text-tg-button-text disabled:opacity-50"
      >
        {m.isPending ? "Передаю…" : "Передать смену"}
      </button>
      <p className="mt-2 text-center text-xs text-tg-hint">
        Принимающий получит уведомление и подтвердит приём — или вернёт с
        причиной. Снимок открытых пунктов сохранится в истории.
      </p>
    </BottomSheet>
  );
}
