import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { humanizeApiError } from "@/api/client";
import { mediaUrl, uploadPhoto, type MediaItem } from "@/api/media";
import { haptic, showAlert } from "@/tg/webapp";
import Icon, { InlineIcon } from "@/components/Icon";

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
    ? "min-h-11 rounded-tile bg-tg-secondary-bg px-2.5 text-xs text-tg-text"
    : "min-h-11 flex-1 rounded-tile bg-tg-secondary-bg px-3 text-sm text-tg-text";

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
        {upload.isPending ? (
          "Загружаю…"
        ) : (
          <>
            <InlineIcon name="camera" />
            {compact ? "Снять" : label}
          </>
        )}
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
        <InlineIcon name="image" />
        {compact ? "Галерея" : "Из галереи"}
      </button>
    </div>
  );
}

/**
 * Картинка с двумя повторами.
 *
 * Зачем: на мобильной сети ответ может оборваться, а Cloudflare/HF иногда
 * отдают 502 на первом запросе после простоя. Без повтора человек видит
 * навсегда «сломанное» фото и не понимает, что с этим делать. Повтор идёт с
 * параметром `retry` — подпись считается только по id, поэтому URL остаётся
 * валидным.
 */
function ImgWithRetry({
  src,
  alt,
  size,
  className,
  style,
}: {
  src: string;
  alt: string;
  size?: number;
  className?: string;
  style?: React.CSSProperties;
}) {
  const [attempt, setAttempt] = useState(0);
  if (attempt > 2) {
    return (
      <span
        className="grid place-items-center bg-tg-secondary-bg px-1 text-center text-2xs leading-tight text-tg-hint"
        style={size ? { width: size, height: size } : undefined}
      >
        Фото не открылось
      </span>
    );
  }
  const url = attempt
    ? `${src}${src.includes("?") ? "&" : "?"}retry=${attempt}`
    : src;
  return (
    <img
      key={attempt}
      src={url}
      alt={alt}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      width={size}
      height={size}
      className={className}
      style={style}
      onError={() => setAttempt((current) => current + 1)}
    />
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
              className="overflow-hidden rounded-tile bg-tg-bg/60"
              aria-label="Открыть фото"
            >
              <ImgWithRetry
                src={src}
                alt="Фотоотчёт"
                size={size}
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
              className="grid min-h-11 min-w-11 place-items-center rounded-tile bg-white/10 text-white"
              onClick={() => setOpen(null)}
              aria-label="Закрыть"
            >
              <Icon name="close" size={18} />
            </button>
          </div>
          <div className="flex flex-1 items-center justify-center p-3">
            <ImgWithRetry
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
