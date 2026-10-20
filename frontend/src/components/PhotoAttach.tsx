import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { humanizeApiError } from "@/api/client";
import { mediaUrl, uploadPhoto, type MediaItem } from "@/api/media";
import { haptic, showAlert } from "@/tg/webapp";

export interface PhotoView {
  id: number;
  url: string;
  width?: number | null;
  height?: number | null;
}

/**
 * Прикрепление снимка прямо в приложении: камера или галерея.
 *
 * Раньше пункт с 📷 требовал выйти в чат с ботом, нажать там «Фотоотчёт» и
 * прислать снимок — формально «работает», практически люди теряли задачу на
 * середине. Теперь две кнопки здесь же: `capture="environment"` на телефоне
 * открывает камеру сразу, без выбора файла.
 */
export default function PhotoAttach({
  onUploaded,
  label = "Прикрепить фото",
  compact = false,
  disabled = false,
}: {
  onUploaded: (media: MediaItem) => void;
  label?: string;
  /** Компактный вариант для карточки списка. */
  compact?: boolean;
  disabled?: boolean;
}) {
  const cameraRef = useRef<HTMLInputElement>(null);
  const galleryRef = useRef<HTMLInputElement>(null);

  const upload = useMutation({
    mutationFn: (file: File) => uploadPhoto(file),
    onSuccess: (media) => {
      haptic("success");
      onUploaded(media);
    },
    onError: (e) => {
      haptic("error");
      void showAlert(humanizeApiError(e));
    },
  });

  const pick = (file: File | undefined) => {
    if (!file) return;
    upload.mutate(file);
  };

  // VISUAL_AUDIT P0.2: даже компактные «Снять / Галерея» — не меньше 44px.
  const buttonClass = compact
    ? "min-h-11 rounded-lg bg-tg-secondary-bg px-2.5 text-[12px] text-tg-text"
    : "min-h-11 flex-1 rounded-lg bg-tg-secondary-bg px-3 text-sm text-tg-text";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        aria-label="Сделать фото"
        onChange={(e) => {
          pick(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <input
        ref={galleryRef}
        type="file"
        accept="image/*"
        className="hidden"
        aria-label="Выбрать фото из галереи"
        onChange={(e) => {
          pick(e.target.files?.[0]);
          e.target.value = "";
        }}
      />

      <button
        type="button"
        disabled={disabled || upload.isPending}
        onClick={() => {
          haptic("light");
          cameraRef.current?.click();
        }}
        className={`${buttonClass} disabled:opacity-50`}
      >
        {upload.isPending ? "⏳ Загружаю…" : `📷 ${compact ? "Снять" : label}`}
      </button>
      <button
        type="button"
        disabled={disabled || upload.isPending}
        onClick={() => {
          haptic("light");
          galleryRef.current?.click();
        }}
        className={`${buttonClass} disabled:opacity-50`}
      >
        🖼 {compact ? "Галерея" : "Из галереи"}
      </button>
    </div>
  );
}

/** Превью снимков с полноэкранным просмотром по тапу. */
export function PhotoThumbs({
  photos,
  size = 72,
}: {
  photos: PhotoView[];
  size?: number;
}) {
  const [open, setOpen] = useState<PhotoView | null>(null);
  if (photos.length === 0) return null;

  return (
    <>
      <div className="mt-2 flex flex-wrap gap-2">
        {photos.map((photo) => {
          const src = mediaUrl(photo.url);
          if (!src) return null;
          return (
            <button
              key={photo.id}
              type="button"
              onClick={() => {
                haptic("light");
                setOpen(photo);
              }}
              className="overflow-hidden rounded-lg bg-tg-bg/60"
              aria-label="Открыть фото"
            >
              <img
                src={src}
                alt="Фотоотчёт"
                loading="lazy"
                width={size}
                height={size}
                className="object-cover"
                style={{ width: size, height: size }}
              />
            </button>
          );
        })}
      </div>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Просмотр фото"
          className="fixed inset-0 z-50 flex flex-col bg-black/90"
          onClick={() => setOpen(null)}
        >
          <div className="flex justify-end p-3">
            <button
              type="button"
              className="min-h-11 min-w-11 rounded-lg bg-white/10 text-lg text-white"
              onClick={() => setOpen(null)}
              aria-label="Закрыть"
            >
              ✕
            </button>
          </div>
          <div className="flex flex-1 items-center justify-center p-3">
            <img
              src={mediaUrl(open.url) ?? ""}
              alt="Фотоотчёт"
              className="max-h-full max-w-full object-contain"
            />
          </div>
        </div>
      )}
    </>
  );
}
