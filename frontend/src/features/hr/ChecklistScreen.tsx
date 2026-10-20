import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  completeChecklistItem,
  fetchChecklist,
  type ChecklistKind,
  type HrChecklistItem,
} from "@/api/hr";
import { humanizeApiError } from "@/api/client";
import type { MediaItem } from "@/api/media";
import PhotoAttach, { PhotoThumbs } from "@/components/PhotoAttach";
import ErrorState from "@/components/ErrorState";
import ProgressBar from "@/components/ProgressBar";
import { CardSkeleton } from "@/components/Skeleton";
import { haptic, showAlert } from "@/tg/webapp";

/**
 * SemiTaskBot: «Чек-лист смены».
 *
 * Два режима: первый день (`first_day`) и обычная смена (`shift`). Пункты,
 * требующие фото, закрываются ТОЛЬКО фотографией — и теперь снять её можно
 * здесь же, в приложении: камера или галерея, без перехода в чат с ботом.
 * Фото из чата тоже продолжает работать — сервер принимает оба пути.
 */
export default function ChecklistScreen() {
  const qc = useQueryClient();
  const [kind, setKind] = useState<ChecklistKind>("shift");
  const [noteFor, setNoteFor] = useState<number | null>(null);

  const q = useQuery({
    queryKey: ["hr-checklist", kind],
    queryFn: () => fetchChecklist(kind),
  });

  const complete = useMutation({
    mutationFn: (body: {
      item_id: number;
      note?: string | null;
      photo_file_id?: string;
      media_id?: number | null;
    }) => completeChecklistItem(body),
    onSuccess: (data) => {
      haptic("success");
      qc.setQueryData(["hr-checklist", kind], data);
      void qc.invalidateQueries({ queryKey: ["hr-feed"] });
      setNoteFor(null);
    },
    onError: (e) => void showAlert(humanizeApiError(e)),
  });

  if (q.isError)
    return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const data = q.data;

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-tg-secondary-bg px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h1 className="text-lg font-semibold text-tg-text">Чек-лист смены</h1>
          {data && (
            <span className="text-xs text-tg-hint">{data.progress_text}</span>
          )}
        </div>
        <div className="mt-3 flex gap-1.5">
          {[
            { v: "shift" as const, label: "Смена" },
            { v: "first_day" as const, label: "Первый день" },
          ].map((o) => (
            <button
              key={o.v}
              type="button"
              onClick={() => {
                haptic("light");
                setKind(o.v);
              }}
              className={[
                "min-h-8 rounded-full px-3 text-xs transition-colors",
                kind === o.v
                  ? "bg-tg-button text-tg-button-text"
                  : "bg-tg-secondary-bg text-tg-hint",
              ].join(" ")}
            >
              {o.label}
            </button>
          ))}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        {q.isLoading && (
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        )}

        {data && data.items.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="text-4xl" aria-hidden>
              🗒
            </div>
            <div className="mt-2 text-sm font-medium text-tg-text">
              Чек-лист не назначен
            </div>
            <div className="mt-1 text-xs text-tg-hint">
              Попроси руководителя назначить шаблон{" "}
              {kind === "shift" ? "смены" : "первого дня"}.
            </div>
          </div>
        )}

        {data && data.items.length > 0 && (
          <ProgressBar
            value={data.done}
            total={data.total}
            label={data.template_title ?? "Чек-лист"}
          />
        )}

        {data?.items.map((item) => (
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

        {data?.status === "done" && (
          <div className="rounded-xl bg-status-free/10 p-3 text-center text-xs text-status-free">
            ✓ Смена закрыта. Спасибо за работу!
          </div>
        )}
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
              📷 {item.done ? "фотоотчёт приложен" : "нужен фотоотчёт: снимок с камеры или из галереи"}
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
              item.photo_url
                ? [{ id: item.id, url: item.photo_url }]
                : []
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
