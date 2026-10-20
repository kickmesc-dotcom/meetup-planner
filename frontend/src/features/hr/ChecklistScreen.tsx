import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  chooseHall,
  completeChecklistItem,
  fetchChecklist,
  fetchHalls,
  type ChecklistKind,
  type HrChecklistItem,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import { useAppText } from "@/api/texts";
import type { MediaItem } from "@/api/media";
import Icon from "@/components/Icon";
import PhotoAttach, { PhotoThumbs } from "@/components/PhotoAttach";
import ErrorState from "@/components/ErrorState";
import ProgressBar from "@/components/ProgressBar";
import { CardSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";

/**
 * SemiTaskBot: «Чек-лист смены».
 *
 * Открытие зала начинается с выбора зала: у первого и второго зала свои
 * пункты (DOCX владельца), поэтому чек-лист показывается только после выбора.
 * Выбор запоминается на смену и меняется одной кнопкой. Закрытие смены —
 * отдельная вкладка и общий чек-лист: вечером зал уже не важен. Последний
 * пункт закрытия — «показать рабочее место» с фотоотчётом.
 */
const KIND_LABEL: Record<ChecklistKind, string> = {
  shift: "Открытие",
  close: "Закрытие",
  first_day: "Первый день",
};

export default function ChecklistScreen() {
  const qc = useQueryClient();
  const emptyTitle = useAppText("checklist.empty.title", "Чек-лист не назначен");
  const [kind, setKind] = useState<ChecklistKind>("shift");
  const [noteFor, setNoteFor] = useState<number | null>(null);
  const [changingHall, setChangingHall] = useState(false);

  const q = useQuery({
    queryKey: ["hr-checklist", kind],
    queryFn: () => fetchChecklist(kind),
  });

  const data = q.data;
  const showingHallPicker =
    kind === "shift" && (changingHall || Boolean(data?.needs_hall));

  const hallsQ = useQuery({
    queryKey: ["hr-halls"],
    queryFn: fetchHalls,
    enabled: showingHallPicker,
    staleTime: 5 * 60_000,
  });

  const pickHall = useMutation({
    mutationFn: (hallId: number) => chooseHall(hallId),
    onSuccess: (next) => {
      haptic("success");
      qc.setQueryData(["hr-checklist", "shift"], next);
      setChangingHall(false);
      void qc.invalidateQueries({ queryKey: ["hr-feed"] });
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  const complete = useMutation({
    mutationFn: (body: {
      item_id: number;
      note?: string | null;
      photo_file_id?: string;
      media_id?: number | null;
    }) => completeChecklistItem(body),
    onSuccess: (next) => {
      haptic("success");
      qc.setQueryData(["hr-checklist", kind], next);
      void qc.invalidateQueries({ queryKey: ["hr-feed"] });
      setNoteFor(null);
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  if (q.isError)
    return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-tg-secondary-bg px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h1 className="text-lg font-semibold text-tg-text">Чек-лист смены</h1>
          {data && data.total > 0 && (
            <span className="text-xs tabular-nums text-tg-hint">
              {data.progress_text}
            </span>
          )}
        </div>
        <div className="mt-3 flex gap-1.5">
          {(["shift", "close", "first_day"] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => {
                haptic("light");
                setKind(v);
                setChangingHall(false);
                setNoteFor(null);
              }}
              className={[
                "min-h-11 rounded-full px-3 text-xs transition-colors",
                kind === v
                  ? "bg-tg-button text-tg-button-text"
                  : "bg-tg-secondary-bg text-tg-hint",
              ].join(" ")}
            >
              {KIND_LABEL[v]}
            </button>
          ))}
        </div>
        {kind === "shift" && data?.hall_name && !showingHallPicker && (
          <div className="mt-2 flex items-center justify-between gap-2 rounded-lg bg-tg-secondary-bg/50 px-3 py-1.5">
            <span className="flex items-center gap-1.5 text-xs text-tg-text">
              <Icon name="door" size={16} />
              Сегодня работаешь: <b>{data.hall_name}</b>
            </span>
            <button
              type="button"
              onClick={() => {
                haptic("light");
                setChangingHall(true);
              }}
              className="min-h-11 px-2 text-[11px] text-tg-link"
            >
              сменить
            </button>
          </div>
        )}
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        {q.isLoading && (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}

        {showingHallPicker && (
          <HallPicker
            halls={hallsQ.data ?? []}
            loading={hallsQ.isLoading}
            busy={pickHall.isPending}
            selectedId={data?.hall_id ?? null}
            onChange={(id) => {
              haptic("selection");
              pickHall.mutate(id);
            }}
          />
        )}

        {!showingHallPicker && data && data.items.length === 0 && (
          <EmptyState title={emptyTitle} kind={kind} />
        )}

        {!showingHallPicker && data && data.items.length > 0 && (
          <ProgressBar
            value={data.done}
            total={data.total}
            label={data.template_title ?? "Чек-лист"}
          />
        )}

        {!showingHallPicker &&
          data?.items.map((item) => (
            <ItemRow
              key={item.id}
              item={item}
              busy={complete.isPending}
              noteOpen={noteFor === item.id}
              onToggleNote={() => {
                haptic("light");
                setNoteFor(noteFor === item.id ? null : item.id);
              }}
              onToggle={() => {
                if (item.done) return;
                complete.mutate({ item_id: item.id });
              }}
              onPhoto={(media: MediaItem) =>
                complete.mutate({ item_id: item.id, media_id: media.id })
              }
              onSaveNote={(note) => complete.mutate({ item_id: item.id, note })}
            />
          ))}

        {!showingHallPicker && data?.status === "done" && (
          <div className="rounded-xl bg-status-free/10 p-3 text-center text-xs text-status-free">
            ✓ {kind === "close" ? "Смена закрыта" : "Смена открыта"}.
            {kind === "close" ? " Спасибо за работу!" : " Хорошей смены!"}
          </div>
        )}
      </div>
    </div>
  );
}

function HallPicker({
  halls,
  loading,
  busy,
  selectedId,
  onChange,
}: {
  halls: { id: number; name: string }[];
  loading: boolean;
  busy: boolean;
  selectedId: number | null;
  onChange: (hallId: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="rounded-xl bg-tg-secondary-bg/60 p-3">
        <div className="text-sm font-semibold text-tg-text">
          В каком зале работаешь?
        </div>
        <div className="mt-0.5 text-[11px] text-tg-hint">
          У каждого зала свой чек-лист открытия. Выбор запомнится на сегодня —
          сменить можно в любой момент.
        </div>
      </div>
      {loading && <CardSkeleton />}
      {!loading && halls.length === 0 && (
        <div className="rounded-xl bg-tg-secondary-bg/40 p-3 text-xs text-tg-hint">
          Залы не заведены. Попроси руководителя добавить их в разделе
          «Чек-листы».
        </div>
      )}
      {halls.map((hall) => (
        <button
          key={hall.id}
          type="button"
          disabled={busy}
          onClick={() => onChange(hall.id)}
          className={[
            "flex w-full items-center justify-between rounded-xl px-4 py-3 text-left text-sm transition-transform active:scale-[0.99] disabled:opacity-60",
            hall.id === selectedId
              ? "bg-tg-button text-tg-button-text"
              : "bg-tg-secondary-bg/60 text-tg-text",
          ].join(" ")}
        >
          <span className="flex items-center gap-2">
            <Icon name="door" size={18} />
            {hall.name}
          </span>
          <span className="text-xs opacity-70">
            {hall.id === selectedId ? "выбран" : "выбрать"}
          </span>
        </button>
      ))}
    </div>
  );
}

function EmptyState({ title, kind }: { title: string; kind: ChecklistKind }) {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <Icon name="checklist" size={36} className="text-tg-hint" />
      <div className="mt-2 text-sm font-medium text-tg-text">{title}</div>
      <div className="mt-1 text-xs text-tg-hint">
        Попроси руководителя назначить шаблон{" "}
        {kind === "close"
          ? "закрытия смены"
          : kind === "shift"
            ? "открытия зала"
            : "первого дня"}
        .
      </div>
    </div>
  );
}

function ItemRow({
  item,
  busy,
  noteOpen,
  onToggle,
  onToggleNote,
  onPhoto,
  onSaveNote,
}: {
  item: HrChecklistItem;
  busy: boolean;
  noteOpen: boolean;
  onToggle: () => void;
  onToggleNote: () => void;
  onPhoto: (media: MediaItem) => void;
  onSaveNote: (note: string) => void;
}) {
  const [note, setNote] = useState(item.note ?? "");
  const photoBlocks = item.requires_photo && !item.done;

  return (
    <div
      className={[
        "rounded-xl p-3",
        item.done ? "bg-tg-secondary-bg/40" : "bg-tg-secondary-bg/60",
      ].join(" ")}
    >
      <div className="flex items-start gap-3">
        <button
          type="button"
          aria-pressed={item.done}
          aria-label={
            photoBlocks ? "Пункт закрывается фотоотчётом" : "Отметить пункт"
          }
          disabled={busy || item.done || photoBlocks}
          onClick={onToggle}
          className={[
            "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border text-sm",
            item.done
              ? "border-status-free bg-status-free/20 text-status-free"
              : "border-tg-hint/40 text-transparent",
          ].join(" ")}
        >
          ✓
        </button>

        <div className="min-w-0 flex-1">
          <div
            className={[
              "text-sm",
              item.done ? "text-tg-hint line-through" : "text-tg-text",
            ].join(" ")}
          >
            {item.title}
            {!item.is_mandatory && (
              <span className="ml-1 text-[11px] text-tg-hint">(опц.)</span>
            )}
          </div>
          {item.description && (
            <div className="mt-0.5 text-[11px] text-tg-hint">
              {item.description}
            </div>
          )}
          {item.requires_photo && (
            <div className="mt-1 text-[11px] text-tg-hint">
              📷{" "}
              {item.done
                ? "фотоотчёт приложен"
                : "нужен фотоотчёт: снимок с камеры или из галереи"}
            </div>
          )}
          {!item.done && photoBlocks && (
            <div className="mt-2">
              <PhotoAttach
                compact
                label="Снять отчёт"
                disabled={busy}
                onUploaded={onPhoto}
              />
            </div>
          )}
          <PhotoThumbs
            photos={
              item.photo_url ? [{ id: item.id, url: item.photo_url }] : []
            }
          />
          {item.done_at && (
            <div className="mt-1 text-[11px] text-tg-hint">
              закрыто в{" "}
              {new Date(item.done_at).toLocaleTimeString("ru-RU", {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </div>
          )}
          {item.note && (
            <div className="mt-1 rounded-md bg-tg-bg/50 p-2 text-[11px] text-tg-text/90">
              {item.note}
            </div>
          )}
        </div>

        {!item.done && (
          <button
            type="button"
            onClick={onToggleNote}
            className="shrink-0 rounded-lg bg-tg-bg/60 px-2 py-1 text-[11px] text-tg-text"
          >
            {noteOpen ? "Отмена" : "Заметка"}
          </button>
        )}
      </div>

      {noteOpen && (
        <div className="mt-2 rounded-lg bg-tg-bg/60 p-2">
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            maxLength={500}
            placeholder="Например: инвентарь в порядке, не хватило 2 упаковок"
            className="w-full rounded-lg bg-tg-secondary-bg p-2 text-sm text-tg-text"
          />
          <button
            type="button"
            disabled={busy || !note.trim()}
            onClick={() => onSaveNote(note.trim())}
            className="mt-2 min-h-9 w-full rounded-lg bg-tg-button text-xs font-medium text-tg-button-text disabled:opacity-50"
          >
            Сохранить заметку
          </button>
        </div>
      )}
    </div>
  );
}
